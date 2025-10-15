from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from app.utils.file_utils import save_upload_to_temp, save_multiple_uploads_to_temp, JsonOrderStore
from app.services.fal_service import upload_file_and_generate, generate_multiple
from app.services.yookassa_service import create_payment as yk_create_payment
from typing import List, Optional
import uuid
import hmac, hashlib, base64
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.services.email_service import send_email_with_links
from app.services.email_service import send_payment_receipt
from app.services.email_service import send_email_with_attachments
from app.services.fal_service import generate_from_url, submit_generation

# new imports
from app.utils.s3_utils import upload_bytes, s3_key_for_upload, get_file_url_with_expiry
import os
import json
import logging

app = FastAPI()

# CORS
app.add_middleware(
	CORSMiddleware,
	allow_origins=["https://xn--e1aybc.xn--b1ahgb0aea5aq.online"],
	allow_credentials=False,
	allow_methods=["*"],
	allow_headers=["*"],
)

orders = JsonOrderStore()
import threading, time

# Логгер для поллинга
logger = logging.getLogger("livephoto.polling")
if not logger.handlers:
	h = logging.StreamHandler()
	formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
	h.setFormatter(formatter)
	logger.addHandler(h)
	logger.setLevel(logging.INFO)

@app.post("/generate_video")
async def generate_video(
	image: UploadFile = File(...),
	prompt: str = Form("Animate this image"),
	sync_mode: bool = Form(True),
):
	tmp_path = await save_upload_to_temp(image)
	try:
		result = upload_file_and_generate(tmp_path, prompt=prompt, sync_mode=sync_mode)
		return JSONResponse(content=result)
	except HTTPException:
		raise
	except Exception as exc:
		raise HTTPException(status_code=500, detail=str(exc))
	finally:
		import os
		if tmp_path and os.path.exists(tmp_path):
			os.remove(tmp_path)


@app.post("/create_order")
async def create_order(
	email: str = Form(...),
	price_rub: float = Form(...),
	files: List[UploadFile] | None = None,
	prompts: Optional[str] = Form(None),  # JSON-строка с массивом промптов или один общий
	anonUserId: str = Form(...),
):
	# 1) сохраняем входные файлы в S3
	request_id = f"order-{uuid.uuid4().hex[:8]}"
	images_meta = []
	files = files or []
	prompts_list: Optional[List[str]] = None
	if prompts:
		try:
			prompts_list = json.loads(prompts)
		except Exception:
			prompts_list = None
	for idx, upload in enumerate(files):
		# читаем весь файл в память; для больших файлов лучше стримить по частям
		content = await upload.read()
		filename = upload.filename or f"file_{idx}"
		key = s3_key_for_upload(anonUserId, request_id, filename)
		upload_bytes(settings.s3_bucket_name or "", key, content, content_type=upload.content_type)
		s3_url = f"s3://{settings.s3_bucket_name}/{key}"
		public_url, exp = get_file_url_with_expiry(settings.s3_bucket_name or "", key)
		prompt_val = (prompts_list[idx] if prompts_list and idx < len(prompts_list) else "Animate this image")
		images_meta.append({
			"s3_url": s3_url,
			"prompt": prompt_val,
			"image_url": s3_url,
			"public_image_url": public_url,
			"expires_in": exp,
		})

	# 2) записываем заказ в JSON-хранилище
	order_record = {
		"order_id": request_id,
		"request_id": request_id,
		"anonUserId": anonUserId,
		"email": email,
		"price_rub": price_rub,
		"payment": {
			"provider": "yookassa",
			"status": "gateway_pending",
		},
		"generation": {
			"status": "waiting_payment",
			"items": [
				{
					"image_url": im.get("image_url"),
					"public_image_url": im.get("public_image_url"),
					"expires_in": im.get("expires_in"),
					"prompt": im["prompt"],
					"status": "pending",
					# по требованию: в input_s3_url кладём публичный URL
					"input_s3_url": im.get("public_image_url"),
				}
				for im in images_meta
			],
		},
	}
	# создаем платёж в YooKassa и сохраняем payment_id + paymentUrl
	try:
		payment = yk_create_payment(
			order_id=request_id,
			amount_rub=price_rub,
			description=f"Video generation {len(images_meta)} item(s)",
			return_url=f"{settings.frontend_return_url_base}/payment/success?orderId={request_id}",
			email=email,
			anon_user_id=anonUserId,
		)
		order_record["payment"].update({
			"payment_id": payment["payment_id"],
			"payment_url": payment["payment_url"],
		})
	except Exception as e:
		# если не удалось создать платёж, остаемся в gateway_pending без URL
		order_record["payment"].update({"error": str(e)})

	orders.save(order_record)
	return {
		"orderId": request_id,
		"paymentStatus": order_record["payment"]["status"],
		"generationStatus": order_record["generation"]["status"],
		"paymentUrl": order_record["payment"].get("payment_url"),
		"paymentError": order_record["payment"].get("error"),
	}


def _verify_webhook_signature(raw_body: bytes, header_signature: str | None) -> bool:
	secret = settings.yandex_pay_webhook_secret or ""
	if not secret or not header_signature:
		return False
	expected = base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()).decode()
	return hmac.compare_digest(expected, header_signature)


@app.post("/yandex-pay/webhook")
async def yandex_pay_webhook(request: Request):
	raw = await request.body()
	sign = request.headers.get("X-Signature") or request.headers.get("Signature")
	if not _verify_webhook_signature(raw, sign):
		return Response(status_code=400)
	payload = await request.json()
	order_id = payload.get("orderId") or payload.get("merchantOrderId")
	status = payload.get("status")
	if order_id:
		if status in ("PAID", "CAPTURED", "COMPLETED"):
			orders.update_status(order_id, "PAID")
			# простая синхронная обработка (для MVP); в продакшн вынести в очередь
			order = orders.load(order_id)
			if order:
				prompts = None
				try:
					import json as _json
					prompts = _json.loads(order.get("prompts") or "null")
				except Exception:
					prompts = None
				results = generate_multiple(order.get("files") or [], prompts=prompts or None, sync_mode=True)
				links: List[str] = []
				for r in results:
					url = r.get("response_url") or r.get("url") or r.get("video_url")
					if url:
						links.append(url)
				if order.get("email") and links:
					send_email_with_links(order["email"], links)
				orders.update_status(order_id, "COMPLETED")
		else:
			orders.update_status(order_id, f"STATUS_{status}")
	return {"ok": True}


# YooKassa webhook: подтверждение оплаты -> генерация -> письма

@app.post("/yookassa/webhook")
async def yookassa_webhook(payload: dict, request: Request):
	# Опциональная проверка подписи, если настроен секрет
	try:
		secret = settings.yookassa_webhook_secret
		if secret:
			raw = await request.body()
			import hmac, hashlib
			signature = request.headers.get("Webhook-Signature") or request.headers.get("X-Webhook-Signature")
			if not signature:
				return {"ok": False}
			expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
			if not hmac.compare_digest(expected, signature):
				return {"ok": False}
	except Exception:
		pass
	# YooKassa шлет объект payment в поле object
	obj = payload.get("object") or {}
	status = obj.get("status")
	payment_id = obj.get("id")
	amount = obj.get("amount", {}).get("value")
	metadata = obj.get("metadata") or {}
	order_id = metadata.get("order_id")
	if not order_id:
		return {"ok": True}

	order = orders.load(order_id) or {}
	if status == "succeeded":
		# фиксация оплаты
		order.setdefault("payment", {})
		order["payment"].update({"status": "paid", "payment_id": payment_id})
		orders.save(order)
		# отправка квитанции
		try:
			if order.get("email"):
				send_payment_receipt(order["email"], float(amount or 0), order_id, payment_id)
		except Exception:
			pass
		# Идемпотентность: если генерация уже шла/завершилась — ничего не делаем
		gen = order.get("generation") or {}
		if gen.get("status") in ("in_progress", "completed"):
			return {"ok": True}
		# генерация по каждому инпуту: ставим задачи с вебхуком fal.ai
		items = gen.get("items") or []
		from app.utils.s3_utils import parse_s3_url, get_file_url_with_expiry
		for idx, it in enumerate(items):
			if it.get("request_id") or it.get("status") in ("running", "succeeded"):
				continue
			try:
				# Предпочитаем заранее сохранённую публичную ссылку
				img_url = it.get("public_image_url")
				if not img_url:
					bucket, key = parse_s3_url(it.get("input_s3_url", ""))
					img_url, exp = get_file_url_with_expiry(bucket, key)
					it["public_image_url"] = img_url
					it["expires_in"] = exp
				sub = submit_generation(img_url, it.get("prompt") or "Animate this image", order_id, idx, order.get("anonUserId"))
				it["status"] = "running"
				it["request_id"] = sub.get("request_id")
			except Exception as _e:
				it["status"] = "failed"
				it["error"] = str(_e)
		order.setdefault("generation", {})["status"] = "in_progress"
		order["generation"]["items"] = items
		orders.save(order)
	return {"ok": True}


@app.post("/fal/webhook")
async def fal_webhook(request: Request):
	# Валидация подписи (если используется)
	params = dict(request.query_params)
	order_id = params.get("order_id")
	item_index_str = params.get("item_index")
	token = params.get("token")
	if settings.fal_webhook_token and token != settings.fal_webhook_token:
		return Response(status_code=401)
	if not order_id or item_index_str is None:
		return Response(status_code=400)
	item_index = int(item_index_str)
	payload = await request.json()
	status = payload.get("status") or payload.get("state")
	# В payload должна быть ссылка на видео, структура зависит от модели
	video_url = payload.get("response_url") or payload.get("url") or payload.get("video_url")

	order = orders.load(order_id) or {}
	items = (order.get("generation") or {}).get("items") or []
	if item_index < 0 or item_index >= len(items):
		return {"ok": True}
	item = items[item_index]
	links: List[str] = []
	if status in ("succeeded", "COMPLETED", "completed") and video_url:
		# Скачиваем и перекладываем в S3/videos, сохраняем ссылку
		try:
			import requests as _rq
			video_resp = _rq.get(video_url, timeout=180)
			video_resp.raise_for_status()
			video_bytes = video_resp.content
			from app.utils.s3_utils import s3_key_for_video, upload_bytes, get_file_url_with_expiry as _gfue, parse_s3_url as _parse
			video_key = s3_key_for_video(order.get("anonUserId") or "user", order_id, item_index, ".mp4")
			upload_bytes(settings.s3_bucket_name or "", video_key, video_bytes, content_type="video/mp4")
			item["status"] = "succeeded"
			item["result_s3_url"] = f"s3://{settings.s3_bucket_name}/{video_key}"
			# Сохраняем публичную ссылку и TTL
			pub_url, exp = _gfue(settings.s3_bucket_name or "", video_key)
			item["public_video_url"] = pub_url
			item["expires_in"] = exp
			# Дублируем поле s3 для симметрии с изображениями
			item["video_url"] = item["result_s3_url"]
		except Exception as _e:
			item["status"] = "failed"
			item["error"] = str(_e)
	else:
		item["status"] = "failed"
		item["error"] = payload.get("error") or "unknown"
	# Сохраняем прогресс
	order.setdefault("generation", {})["items"] = items
	# Если все items завершены успешно/неуспешно — отправим письма и финальный статус
	all_done = all(it.get("status") in ("succeeded", "failed") for it in items)
	if all_done:
		order["generation"]["status"] = "completed"
		# Собираем публичные ссылки и шлём письмо
		try:
			from app.utils.s3_utils import parse_s3_url as _parse, get_file_url_with_expiry as _gfue
			for it in items:
				if it.get("public_video_url"):
					links.append(it["public_video_url"])
				elif it.get("result_s3_url"):
					b, k = _parse(it["result_s3_url"])
					url, exp = _gfue(b, k)
					it["public_video_url"] = url
					it["expires_in"] = exp
					links.append(url)
			if order.get("email") and links:
				send_email_with_links(order["email"], links)
		except Exception:
			pass
	orders.save(order)
	return {"ok": True}


# Периодическая задача: опрос статусов очереди и сохранение response_url
def _poll_worker():
    while True:
        try:
            logger.info("poll: tick start")
            all_orders = orders.list_recent_orders(max_files=7)
            logger.info(f"poll: loaded recent orders: {len(all_orders)}")
            for order in all_orders:
                gen = order.get("generation") or {}
                items = gen.get("items") or []
                order_id = order.get("order_id") or order.get("request_id")
                changed = False
                for idx, it in enumerate(items):
                    if it.get("status") in ("succeeded", "failed"):
                        continue
                    req_id = it.get("request_id")
                    if not req_id:
                        continue
                    from app.services.fal_service import get_request_status, get_request_response
                    try:
                        st = get_request_status(req_id, logs=False)
                        st_status = (st.get("status") or "").upper()
                        logger.info(f"poll: order={order_id} item={idx} req={req_id} status={st_status}")
                        if st_status == "COMPLETED":
                            resp = get_request_response(req_id)
                            response_url = (
                                resp.get("response_url")
                                or st.get("response_url")
                                or resp.get("response", {}).get("response_url")
                            )
                            if response_url:
                                it["status"] = "succeeded"
                                it["fal_response_url"] = response_url
                                logger.info(f"poll: COMPLETED saved response_url for order={order_id} item={idx}")
                                changed = True
                            else:
                                it["status"] = "failed"
                                it["error"] = "no response_url"
                                logger.warning(f"poll: COMPLETED but no response_url order={order_id} item={idx}")
                                changed = True
                    except Exception as _e:
                        it["status"] = "failed"
                        it["error"] = str(_e)
                        logger.exception(f"poll: error processing order={order_id} item={idx} req={req_id}")
                        changed = True
                if changed:
                    order.setdefault("generation", {})["items"] = items
                    all_done = all(x.get("status") in ("succeeded", "failed") for x in items)
                    if all_done:
                        order["generation"]["status"] = "completed"
                        try:
                            lnks: List[str] = []
                            for x in items:
                                if x.get("fal_response_url"):
                                    lnks.append(x["fal_response_url"])
                            if order.get("email") and lnks:
                                send_email_with_links(order["email"], lnks)
                                logger.info(f"poll: sent email with {len(lnks)} link(s) to {order['email']}")
                        except Exception:
                            pass
                    orders.save(order)
            logger.info("poll: tick end")
        except Exception:
            pass
        time.sleep(20)

@app.on_event("startup")
def start_poll_thread() -> None:
    t = threading.Thread(target=_poll_worker, name="fal-poll", daemon=True)
    t.start()
    logger.info("poll: background thread started")


# статус запроса
@app.get("/request/{request_id}")
async def get_request_status(request_id: str, anonUserId: str):
	rec = orders.load(request_id)
	if not rec:
		raise HTTPException(status_code=404, detail="request not found")
	if rec.get("anonUserId") != anonUserId:
		raise HTTPException(status_code=403, detail="forbidden")
	return {
		"orderId": rec.get("request_id") or rec.get("order_id"),
		"payment": rec.get("payment"),
		"generation": rec.get("generation"),
		"email": rec.get("email"),
	}
