from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from app.utils.file_utils import save_upload_to_temp, save_multiple_uploads_to_temp, JsonOrderStore
from app.services.fal_service import upload_file_and_generate, generate_multiple
from app.services.yandex_pay_service import create_payment_link
from typing import List, Optional
import uuid
import hmac, hashlib, base64
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.services.email_service import send_email_with_links

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
			"provider": "tinkoff",
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
	orders.save(order_record)
	return {
		"orderId": request_id,
		"paymentStatus": "gateway_pending",
		"generationStatus": "waiting_payment",
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
