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
from app.services.fal_service import generate_from_url

# new imports
from app.utils.s3_utils import upload_bytes, s3_key_for_upload
import os
import json

app = FastAPI()

# CORS
app.add_middleware(
	CORSMiddleware,
	allow_origins=["http://localhost:3000"],
	allow_credentials=False,
	allow_methods=["*"],
	allow_headers=["*"],
)

orders = JsonOrderStore()

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
		prompt_val = (prompts_list[idx] if prompts_list and idx < len(prompts_list) else "Animate this image")
		images_meta.append({"s3_url": s3_url, "prompt": prompt_val})

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
				{"input_s3_url": im["s3_url"], "prompt": im["prompt"], "status": "pending"}
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
		# генерация по каждому инпуту: используем presigned URL к S3 как image_url
		items = (order.get("generation") or {}).get("items") or []
		links: List[str] = []
		from app.utils.s3_utils import parse_s3_url, presigned_get_url
		for idx, it in enumerate(items):
			try:
				bucket, key = parse_s3_url(it.get("input_s3_url", ""))
				img_url = presigned_get_url(bucket, key)
				# Генерируем по URL, чтобы не читать локальные файлы
				res = generate_from_url(img_url, prompt=it.get("prompt") or "Animate this image", sync_mode=True)
				url = res.get("response_url") or res.get("url") or res.get("video_url")
				if url:
					# Заливаем видео в S3/videos и формируем presigned ссылку
					try:
						import requests as _rq
						video_resp = _rq.get(url, timeout=120)
						video_resp.raise_for_status()
						video_bytes = video_resp.content
						from app.utils.s3_utils import s3_key_for_video, upload_bytes, presigned_get_url as _pres
						video_key = s3_key_for_video(order.get("anonUserId") or "user", order_id, idx, ".mp4")
						upload_bytes(settings.s3_bucket_name or "", video_key, video_bytes, content_type="video/mp4")
						links.append(_pres(settings.s3_bucket_name or "", video_key))
					except Exception:
						# fallback: оставить оригинальную ссылку fal.ai
						links.append(url)
			except Exception:
				continue
		# отправка ссылок на видео
		try:
			if order.get("email") and links:
				send_email_with_links(order["email"], links)
		except Exception:
			pass
		# финальный статус
		order.setdefault("generation", {}).update({"status": "completed"})
		orders.save(order)
	return {"ok": True}


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
