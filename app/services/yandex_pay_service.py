import uuid
import requests
from typing import Any, Dict

from app.config import settings


def create_payment_link(order_id: str, items_count: int, total_amount_rub: float) -> Dict[str, Any]:
	"""Создать заказ в Yandex Pay и вернуть paymentUrl + сырой ответ.

	Raises: requests.HTTPError if non-2xx
	"""
	if not settings.yandex_pay_api_key or not settings.yandex_pay_merchant_id:
		raise RuntimeError("Yandex Pay settings are not configured")

	order_payload = {
		"orderId": order_id,
		"merchantId": settings.yandex_pay_merchant_id,
		"currencyCode": "RUB",
		"cart": {
			"items": [
				{
					"productId": "gen-video",
					"title": f"Video generation x{items_count}",
					"quantity": {"count": str(items_count)},
					"total": f"{total_amount_rub:.2f}",
				}
			],
			"total": {"amount": f"{total_amount_rub:.2f}"},
		},
		"availablePaymentMethods": ["CARD"],
		"ttl": 1800,
	}

	headers = {
		"Content-Type": "application/json",
		"Authorization": f"Api-Key {settings.yandex_pay_api_key}",
	}
	resp = requests.post(settings.yandex_pay_create_url, json=order_payload, headers=headers, timeout=20)
	resp.raise_for_status()
	data = resp.json()
	# Ожидаем структуру data["data"]["paymentUrl"], но делаем безопасно
	payment_url = (
		data.get("data", {}).get("paymentUrl")
		or data.get("paymentUrl")
	)
	if not payment_url:
		raise ValueError("Yandex Pay: paymentUrl not found in response")
	return {"paymentUrl": payment_url, "raw": data}


