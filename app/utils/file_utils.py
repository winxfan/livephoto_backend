import os
import tempfile
from fastapi import UploadFile, HTTPException
from typing import List
import json
from datetime import datetime

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

async def save_upload_to_temp(upload: UploadFile) -> str:
	# Stream to disk and enforce size limit
	suffix = os.path.splitext(upload.filename or "")[1]
	handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
	path = handle.name
	try:
		written = 0
		while True:
			chunk = await upload.read(1024 * 1024)
			if not chunk:
				break
			written += len(chunk)
			if written > MAX_FILE_SIZE_BYTES:
				handle.close()
				os.remove(path)
				raise HTTPException(status_code=413, detail="File too large (limit 50MB)")
			handle.write(chunk)
		return path
	finally:
		handle.close()


def save_multiple_uploads_to_temp(uploads: List[UploadFile]) -> List[str]:
	paths: List[str] = []
	for upload in uploads or []:
		# NB: UploadFile.read is async; для синхронной упаковки используем .file
		suffix = os.path.splitext(upload.filename or "")[1]
		handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
		path = handle.name
		written = 0
		try:
			upload.file.seek(0)
			while True:
				chunk = upload.file.read(1024 * 1024)
				if not chunk:
					break
				written += len(chunk)
				if written > MAX_FILE_SIZE_BYTES:
					handle.close()
					os.remove(path)
					raise HTTPException(status_code=413, detail="File too large (limit 50MB)")
				handle.write(chunk)
			paths.append(path)
		finally:
			handle.close()
	return paths


class JsonOrderStore:
	"""Простое файловое хранилище заказов для демо/локального режима."""

	def __init__(self, base_dir: str = "/tmp/yapay_orders") -> None:
		self.base_dir = base_dir
		os.makedirs(self.base_dir, exist_ok=True)

	def _path(self, order_id: str) -> str:
		return os.path.join(self.base_dir, f"{order_id}.json")

	def save(self, order: dict) -> None:
		order.setdefault("created_at", datetime.utcnow().isoformat())
		with open(self._path(order["order_id"]), "w", encoding="utf-8") as f:
			json.dump(order, f, ensure_ascii=False, indent=2)

	def load(self, order_id: str) -> dict | None:
		path = self._path(order_id)
		if not os.path.exists(path):
			return None
		with open(path, "r", encoding="utf-8") as f:
			return json.load(f)

	def update_status(self, order_id: str, status: str) -> None:
		order = self.load(order_id) or {"order_id": order_id}
		order["status"] = status
		self.save(order)

