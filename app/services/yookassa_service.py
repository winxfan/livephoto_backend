import base64
import requests
from typing import Any, Dict
import uuid

from app.config import settings


def _auth_header() -> str:
	if not settings.yookassa_shop_id or not settings.yookassa_api_key:
		raise RuntimeError("YooKassa credentials not configured")
	basic = f"{settings.yookassa_shop_id}:{settings.yookassa_api_key}".encode()
	return "Basic " + base64.b64encode(basic).decode()


def create_payment(order_id: str, amount_rub: float, description: str, return_url: str, email: str | None = None, anon_user_id: str | None = None) -> Dict[str, Any]:
	"""Создать платеж и получить confirmation_url.
	Документация YooKassa: POST /v3/payments
	"""
	url = f"{settings.yookassa_api_base}/v3/payments"
	payload = {
		"amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
		"capture": True,
		"description": description,
		"metadata": {"order_id": order_id, "email": email, "anonUserId": anon_user_id},
		"confirmation": {"type": "redirect", "return_url": return_url},
	}
	# Добавим чек, если есть email
	if email:
		payload["receipt"] = {
			"customer": {"email": email},
			"tax_system_code": 1,
			"items": [
				{
					"description": description[:128] or "Video generation",
					"amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
					"quantity": "1.00",
					"vat_code": 1,
					"payment_subject": "service",
					"payment_mode": "full_payment",
				}
			]
		}
	headers = {
		"Authorization": _auth_header(),
		# уникальный ключ на каждый запрос (а не order_id)
		"Idempotence-Key": str(uuid.uuid4()),
		"Content-Type": "application/json",
	}
	resp = requests.post(url, json=payload, headers=headers, timeout=20)
	if not resp.ok:
		# вернём подробности ошибки вызывающей стороне
		try:
			return {"error": {"status": resp.status_code, "text": resp.text}}
		except Exception:
			resp.raise_for_status()
	data = resp.json()
	confirmation_url = data.get("confirmation", {}).get("confirmation_url")
	payment_id = data.get("id")
	if not confirmation_url or not payment_id:
		raise ValueError("YooKassa: confirmation_url or payment id missing")
	return {"payment_id": payment_id, "payment_url": confirmation_url, "raw": data}


