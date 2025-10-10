import os
import tempfile
from fastapi import UploadFile, HTTPException

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
