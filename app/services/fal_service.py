from typing import Any, Dict, List
import os
import fal_client
import requests

from app.config import settings

# Ensure API key is set for fal_client
os.environ.setdefault("FAL_KEY", settings.fal_key)


def upload_file_and_generate(image_path: str, prompt: str, sync_mode: bool = True) -> Dict[str, Any]:
	uploaded_url = fal_client.upload_file(image_path)
	result = fal_client.subscribe(
		settings.fal_endpoint,
		arguments={
			"prompt": prompt,
			"image_url": uploaded_url,
			"sync_mode": sync_mode,
		},
		with_logs=True,
	)
	return result


def generate_multiple(image_paths: List[str], prompts: List[str] | None = None, sync_mode: bool = True) -> List[Dict[str, Any]]:
	results: List[Dict[str, Any]] = []
	for idx, path in enumerate(image_paths):
		prompt = prompts[idx] if prompts and idx < len(prompts) else "Animate this image"
		results.append(upload_file_and_generate(path, prompt=prompt, sync_mode=sync_mode))
	return results


def generate_from_url(image_url: str, prompt: str, sync_mode: bool = True) -> Dict[str, Any]:
	"""Генерация по внешнему URL изображения (presigned S3)."""
	result = fal_client.subscribe(
		settings.fal_endpoint,
		arguments={
			"prompt": prompt,
			"image_url": image_url,
			"sync_mode": sync_mode,
		},
		with_logs=True,
	)
	return result


def submit_generation(image_url: str, prompt: str, order_id: str, item_index: int, anon_user_id: str | None = None) -> Dict[str, Any]:
	"""Поставить задачу в очередь fal.ai с вебхуком и вернуть request_id.

	Идемпотентность обеспечиваем на уровне нашего заказа (не запускаем повторно, если есть request_id).
	"""
	webhook_url = f"{settings.public_api_base_url}/fal/webhook?order_id={order_id}&item_index={item_index}"
	if settings.fal_webhook_token:
		webhook_url += f"&token={settings.fal_webhook_token}"

	# HTTP Queue API (без использования fal_client.queue)
	queue_url = f"https://queue.fal.run/{settings.fal_endpoint}"
	headers = {
		"Authorization": f"Key {settings.fal_key}",
		"Content-Type": "application/json",
	}
	payload = {
		"prompt": prompt,
		"imageUrl": image_url,
		"webhookUrl": webhook_url,
		"imageUrl": image_url,
		"webhookUrl": webhook_url,
	}
	resp = requests.post(queue_url, json=payload, headers=headers, timeout=30)
	resp.raise_for_status()
	data = resp.json()
	request_id = data.get("request_id") or data.get("id") or data.get("requestId")
	if not request_id:
		raise ValueError("fal.ai queue: request_id not found in response")
	return {"request_id": request_id}
