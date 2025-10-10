from typing import Any, Dict, List
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


def generate_multiple(image_paths: List[str], prompts: List[str] | None = None, sync_mode: bool = True) -> List[Dict[str, Any]]:
	results: List[Dict[str, Any]] = []
	for idx, path in enumerate(image_paths):
		prompt = prompts[idx] if prompts and idx < len(prompts) else "Animate this image"
		results.append(upload_file_and_generate(path, prompt=prompt, sync_mode=sync_mode))
	return results
