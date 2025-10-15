from typing import Any, Dict, List, Optional
import os
import fal_client
import requests
import logging
import json as _json

from app.config import settings
from app.utils.s3_utils import parse_s3_url, get_file_url_with_expiry


logger = logging.getLogger("livephoto.fal")

# Ensure API key is set for fal_client
os.environ.setdefault("FAL_KEY", settings.fal_key)


def upload_file_and_generate(image_path: str, prompt: str, sync_mode: bool = True) -> Dict[str, Any]:
	logger.info(f"fal.sdk upload_file path={image_path}")
	uploaded_url = fal_client.upload_file(image_path)
	logger.info(f"fal.sdk upload_file -> url={uploaded_url}")
	logger.info(f"fal.sdk subscribe model={settings.fal_endpoint} args={{'prompt': <len={len(prompt)}>, 'image_url': '<uploaded>', 'sync_mode': {sync_mode}}}")
	result = fal_client.subscribe(
		settings.fal_endpoint,
		arguments={
			"prompt": prompt,
			"image_url": uploaded_url,
			"sync_mode": sync_mode,
		},
		with_logs=True,
	)
	logger.info(f"fal.sdk subscribe -> result={_json.dumps(result)[:2000]}")
	return result


def generate_multiple(image_paths: List[str], prompts: List[str] | None = None, sync_mode: bool = True) -> List[Dict[str, Any]]:
	results: List[Dict[str, Any]] = []
	for idx, path in enumerate(image_paths):
		prompt = prompts[idx] if prompts and idx < len(prompts) else "Animate this image"
		results.append(upload_file_and_generate(path, prompt=prompt, sync_mode=sync_mode))
	return results


def generate_from_url(image_url: str, prompt: str, sync_mode: bool = True) -> Dict[str, Any]:
	"""Генерация по внешнему URL изображения (presigned S3)."""
	# Если передан s3:// — преобразуем в публичный presigned URL
	try:
		if image_url.startswith("s3://"):
			b, k = parse_s3_url(image_url)
			image_url, _ = get_file_url_with_expiry(b, k)
	except Exception:
		pass
	logger.info(f"fal.sdk subscribe model={settings.fal_endpoint} args={{'prompt': <len={len(prompt)}>, 'image_url': '<url>', 'sync_mode': {sync_mode}}}")
	result = fal_client.subscribe(
		settings.fal_endpoint,
		arguments={
			"prompt": prompt,
			"image_url": image_url,
			"sync_mode": sync_mode,
		},
		with_logs=True,
	)
	logger.info(f"fal.sdk subscribe -> result={_json.dumps(result)[:2000]}")
	return result


def submit_generation(image_url: str, prompt: str, order_id: str, item_index: int, anon_user_id: str | None = None) -> Dict[str, Any]:
	"""Поставить задачу в очередь fal.ai с вебхуком и вернуть request_id.

	Идемпотентность обеспечиваем на уровне нашего заказа (не запускаем повторно, если есть request_id).
	"""
	webhook_url = f"{settings.public_api_base_url}/fal/webhook?order_id={order_id}&item_index={item_index}"
	if settings.fal_webhook_token:
		webhook_url += f"&token={settings.fal_webhook_token}"

	# Убедимся, что image_url публичный (presigned), если пришёл как s3://
	try:
		if image_url.startswith("s3://"):
			b, k = parse_s3_url(image_url)
			image_url, _ = get_file_url_with_expiry(b, k)
	except Exception:
		pass

	# HTTP Queue API (без использования fal_client.queue)
	queue_url = f"https://queue.fal.run/{settings.fal_endpoint}"
	headers = {
		"Authorization": f"Key {settings.fal_key}",
		"Content-Type": "application/json",
	}
	payload = {
		"prompt": prompt,
		"image_url": image_url,
		"webhook_url": webhook_url,
	}
	log_headers = {**headers, "Authorization": "Key ****"}
	logger.info(f"fal.http POST {queue_url} headers={log_headers} json={_json.dumps(payload)[:2000]}")
	resp = requests.post(queue_url, json=payload, headers=headers, timeout=30)
	resp.raise_for_status()
	data = resp.json()
	logger.info(f"fal.http <- {resp.status_code} body={_json.dumps(data)[:2000]}")
	request_id = data.get("request_id") or data.get("id") or data.get("requestId")
	if not request_id:
		raise ValueError("fal.ai queue: request_id not found in response")
	# Сохраним base model id (namespace/model) для последующих запросов
	parts = (settings.fal_endpoint or "").split("/")
	base_model = "/".join(parts[:2]) if len(parts) >= 2 else settings.fal_endpoint
	return {"request_id": request_id, "model_id": base_model}


def get_request_status(request_id: str, logs: bool = False, model_id: str | None = None) -> Dict[str, Any]:
	"""Получить статус задачи очереди fal.ai."""
	# Для статуса и ответа нельзя включать subpath — только базовый model_id (namespace/model)
	parts = (model_id or settings.fal_endpoint or "").split("/")
	base_model = "/".join(parts[:2]) if len(parts) >= 2 else (model_id or settings.fal_endpoint)
	status_url = f"https://queue.fal.run/{base_model}/requests/{request_id}/status"
	params = {"logs": 1} if logs else None
	headers = {"Authorization": f"Key {settings.fal_key}"}
	logger.info(f"fal.http GET {status_url} headers={{'Authorization': 'Key ****'}} params={params}")
	resp = requests.get(status_url, headers=headers, params=params, timeout=30)
	resp.raise_for_status()
	data = resp.json()
	logger.info(f"fal.http <- {resp.status_code} body={_json.dumps(data)[:2000]}")
	return data


def get_request_response(request_id: str, model_id: str | None = None) -> Dict[str, Any]:
	"""Получить результат задачи очереди fal.ai."""
	parts = (model_id or settings.fal_endpoint or "").split("/")
	base_model = "/".join(parts[:2]) if len(parts) >= 2 else (model_id or settings.fal_endpoint)
	resp_url = f"https://queue.fal.run/{base_model}/requests/{request_id}"
	headers = {"Authorization": f"Key {settings.fal_key}"}
	logger.info(f"fal.http GET {resp_url} headers={{'Authorization': 'Key ****'}}")
	resp = requests.get(resp_url, headers=headers, timeout=60)
	resp.raise_for_status()
	data = resp.json()
	logger.info(f"fal.http <- {resp.status_code} body={_json.dumps(data)[:2000]}")
	return data


def extract_media_url(payload: Dict[str, Any]) -> Optional[str]:
	"""Пытается извлечь URL видео из ответа fal (учитывая разные модели/форматы).

	Возвращает первую найденную строку, похожую на URL, обходя популярные поля и структуры.
	"""
	def _pick_from_dict(data: Dict[str, Any]) -> Optional[str]:
		# Прямые кандидаты
		for k in ("video_url", "url", "response_url"):
			v = data.get(k)
			if isinstance(v, str) and v:
				return v
		# Популярные вложенные объекты
		for nk in ("video", "output", "result", "data", "media"):
			v = data.get(nk)
			if isinstance(v, dict):
				u = _pick_from_dict(v)
				if u:
					return u
			elif isinstance(v, list):
				for it in v:
					if isinstance(it, dict):
						u = _pick_from_dict(it)
						if u:
							return u
					elif isinstance(it, str) and it:
						return it
		# Массивы выходов
		for ak in ("videos", "outputs", "files"):
			arr = data.get(ak)
			if isinstance(arr, list):
				for it in arr:
					if isinstance(it, dict):
						u = _pick_from_dict(it)
						if u:
							return u
					elif isinstance(it, str) and it:
						return it
		return None

	root = payload or {}
	# Часто всё лежит в response
	resp_obj = root.get("response") if isinstance(root, dict) else None
	if isinstance(resp_obj, dict):
		u = _pick_from_dict(resp_obj)
		if u:
			logger.info(f"fal.util extract_media_url -> {u}")
			return u
	# Пробуем на верхнем уровне
	if isinstance(root, dict):
		u = _pick_from_dict(root)
		if u:
			logger.info(f"fal.util extract_media_url -> {u}")
			return u
	return None


def fetch_queue_json(url: str) -> Dict[str, Any]:
	"""Авторизованный GET к queue.fal.run с логированием тела ответа."""
	headers = {"Authorization": f"Key {settings.fal_key}"}
	logger.info(f"fal.http GET {url} headers={{'Authorization': 'Key ****'}}")
	resp = requests.get(url, headers=headers, timeout=60)
	resp.raise_for_status()
	data = resp.json()
	logger.info(f"fal.http <- {resp.status_code} body={_json.dumps(data)[:2000]}")
	return data


def fetch_bytes(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 180) -> bytes:
	"""GET байтов по URL с логом статуса и длины."""
	mask_headers = dict(headers or {})
	if "Authorization" in mask_headers:
		mask_headers["Authorization"] = "****"
	logger.info(f"fal.http GET {url} headers={mask_headers}")
	resp = requests.get(url, headers=headers, timeout=timeout)
	resp.raise_for_status()
	content_len = resp.headers.get("Content-Length") or len(resp.content)
	logger.info(f"fal.http <- {resp.status_code} bytes={content_len}")
	return resp.content
