import os
import tempfile
from fastapi import UploadFile, HTTPException
from typing import List
import json
from datetime import datetime
import glob

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
	"""Файловое хранилище: одна дата = один JSON-файл в текущей директории.

	Структура файла: массив объектов-заявок за день.
	Имена файлов: YYYY-MM-DD.json
	"""

	def __init__(self, base_dir: str = "logs") -> None:
		self.base_dir = base_dir  # относительный путь (текущая директория по умолчанию)
		os.makedirs(self.base_dir, exist_ok=True)

	def _date_file(self, date_str: str) -> str:
		return os.path.join(self.base_dir, f"{date_str}.json")

	def _list_day_files(self) -> List[str]:
		pattern = os.path.join(self.base_dir, "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json")
		return sorted(glob.glob(pattern))

	def _read_day(self, path: str) -> List[dict]:
		if not os.path.exists(path):
			return []
		with open(path, "r", encoding="utf-8") as f:
			try:
				data = json.load(f)
				return data if isinstance(data, list) else []
			except Exception:
				return []

	def _write_day(self, path: str, items: List[dict]) -> None:
		with open(path, "w", encoding="utf-8") as f:
			json.dump(items, f, ensure_ascii=False, indent=2)

	def save(self, order: dict) -> None:
		# Определяем дату по created_at или текущую (UTC)
		created_at = order.get("created_at") or datetime.utcnow().isoformat()
		order["created_at"] = created_at
		date_str = created_at[:10]
		path = self._date_file(date_str)
		day_items = self._read_day(path)
		# Удаляем старую запись с тем же order_id, если есть, и добавляем актуальную
		order_id = order.get("order_id") or order.get("request_id")
		day_items = [it for it in day_items if (it.get("order_id") or it.get("request_id")) != order_id]
		day_items.append(order)
		self._write_day(path, day_items)

	def load(self, order_id: str) -> dict | None:
		# Поиск по всем дневным файлам (от новых к старым)
		files = self._list_day_files()[::-1]
		for path in files:
			for it in self._read_day(path):
				if (it.get("order_id") or it.get("request_id")) == order_id:
					return it
		return None

	def update_status(self, order_id: str, status: str) -> None:
		files = self._list_day_files()[::-1]
		for path in files:
			items = self._read_day(path)
			updated = False
			for it in items:
				if (it.get("order_id") or it.get("request_id")) == order_id:
					it["status"] = status
					it["updated_at"] = datetime.utcnow().isoformat()
					updated = True
					break
			if updated:
				self._write_day(path, items)
				return

	def list_recent_orders(self, max_files: int = 7) -> List[dict]:
		"""Возвращает список заявок из последних max_files дневных файлов (от новых к старым)."""
		result: List[dict] = []
		files = self._list_day_files()[::-1][:max_files]
		for path in files:
			result.extend(self._read_day(path))
		return result

