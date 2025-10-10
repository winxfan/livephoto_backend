from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from app.utils.file_utils import save_upload_to_temp, save_multiple_uploads_to_temp, JsonOrderStore
from app.services.fal_service import upload_file_and_generate, generate_multiple
from app.services.yandex_pay_service import create_payment_link
from typing import List, Optional
import uuid
import hmac, hashlib, base64
from fastapi import Request, Response
from app.config import settings
from app.services.email_service import send_email_with_links

app = FastAPI()

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
):
	# сохраняем входные файлы временно (в реале — лучше сразу в S3)
	paths = save_multiple_uploads_to_temp(files or [])
	order_id = f"order-{uuid.uuid4().hex[:8]}"
	items_count = len(paths)
	# записываем заказ в файловое хранилище
	orders.save({
		"order_id": order_id,
		"email": email,
		"status": "CREATED",
		"files": paths,
		"prompts": prompts,
		"price_rub": price_rub,
	})
	# создаем платежную ссылку
	payment = create_payment_link(order_id, items_count=items_count or 1, total_amount_rub=price_rub)
	orders.update_status(order_id, "PAYMENT_CREATED")
	return {"orderId": order_id, "paymentUrl": payment["paymentUrl"]}


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
					import json
					prompts = json.loads(order.get("prompts") or "null")
				except Exception:
					prompts = None
				results = generate_multiple(order.get("files") or [], prompts=prompts or None, sync_mode=True)
				# извлекаем URL'ы (зависит от модели fal.ai; оставим как pass-through)
				links: List[str] = []
				for r in results:
					url = r.get("response_url") or r.get("url") or r.get("video_url")
					if url:
						links.append(url)
				# отправляем письмо
				if order.get("email") and links:
					send_email_with_links(order["email"], links)
				orders.update_status(order_id, "COMPLETED")
		else:
			orders.update_status(order_id, f"STATUS_{status}")
	return {"ok": True}
