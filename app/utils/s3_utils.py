import os
import mimetypes
from typing import BinaryIO, Optional
import boto3

from app.config import settings


def _s3_client():
	return boto3.client(
		"s3",
		endpoint_url=settings.s3_endpoint_url,
		aws_access_key_id=settings.s3_access_key_id,
		aws_secret_access_key=settings.s3_secret_access_key,
		region_name=settings.s3_region_name,
	)


def s3_key_for_upload(anon_user_id: str, request_id: str, filename: str) -> str:
	return f"{settings.uploads_prefix}{anon_user_id}/{request_id}/{filename}"


def s3_key_for_video(anon_user_id: str, request_id: str, index: int, ext: str = ".mp4") -> str:
	return f"{settings.videos_prefix}{anon_user_id}/{request_id}/{index}{ext}"


def upload_bytes(bucket: str, key: str, data: bytes, content_type: Optional[str] = None) -> None:
	client = _s3_client()
	ct = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
	client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=ct)


def presigned_get_url(bucket: str, key: str, expires: Optional[int] = None) -> str:
	client = _s3_client()
	exp = expires or settings.s3_presign_ttl_seconds
	return client.generate_presigned_url(
		"get_object",
		Params={"Bucket": bucket, "Key": key},
		ExpiresIn=exp,
	)


def get_file_url(bucket: str, key: str, expires: Optional[int] = None) -> str:
	"""Возвращает публичную presigned-ссылку на объект."""
	return presigned_get_url(bucket, key, expires)


def get_file_url_with_expiry(bucket: str, key: str, expires: Optional[int] = None) -> tuple[str, int]:
	"""Возвращает (url, expires_in секунд)."""
	exp = expires or settings.s3_presign_ttl_seconds
	return presigned_get_url(bucket, key, exp), exp


def get_files_url(bucket: str, object_names: list[str], expires: Optional[int] = None) -> list[str]:
	"""Возвращает список публичных presigned-ссылок для нескольких ключей."""
	urls: list[str] = []
	for name in object_names:
		urls.append(get_file_url(bucket, name, expires))
	return urls


def parse_s3_url(url: str) -> tuple[str, str]:
	"""Парсит строки вида s3://bucket/key -> (bucket, key)."""
	if not url.startswith("s3://"):
		raise ValueError("not an s3 url")
	rem = url[5:]
	bucket, _, key = rem.partition("/")
	if not bucket or not key:
		raise ValueError("invalid s3 url")
	return bucket, key


