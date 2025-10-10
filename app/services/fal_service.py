from typing import Any, Dict
import os
import fal_client

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
