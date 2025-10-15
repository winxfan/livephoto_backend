import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
	fal_key: str = Field(..., alias="FAL_KEY")
	fal_endpoint: str = Field("fal-ai/flux-pro", alias="FAL_ENDPOINT")
	port: int = Field(8000, alias="PORT")

	# Yandex Pay
	yandex_pay_api_key: str | None = Field(None, alias="YANDEX_PAY_API_KEY")
	yandex_pay_merchant_id: str | None = Field(None, alias="YANDEX_PAY_MERCHANT_ID")
	yandex_pay_create_url: str = Field(
		"https://sandbox.pay.yandex.ru/api/merchant/v1/orders",
		alias="YANDEX_PAY_CREATE_URL",
	)
	yandex_pay_webhook_secret: str | None = Field(None, alias="YANDEX_PAY_WEBHOOK_SECRET")

	# SMTP (Yandex)
	smtp_host: str = Field("smtp.yandex.ru", alias="SMTP_HOST")
	# поддержка альтернативного имени переменной SMTP_SERVER
	smtp_server: str | None = Field(None, alias="SMTP_SERVER")
	smtp_port: int = Field(465, alias="SMTP_PORT")
	# поддержка альтернативного имени пользователя SMTP_USERNAME
	smtp_email: str | None = Field(None, alias="SMTP_EMAIL")
	smtp_username: str | None = Field(None, alias="SMTP_USERNAME")
	smtp_password: str | None = Field(None, alias="SMTP_PASSWORD")

	# S3 (Yandex Cloud Object Storage)
	s3_endpoint_url: str | None = Field(None, alias="S3_ENDPOINT_URL")
	s3_access_key_id: str | None = Field(None, alias="S3_ACCESS_KEY_ID")
	s3_secret_access_key: str | None = Field(None, alias="S3_SECRET_ACCESS_KEY")
	s3_bucket_name: str | None = Field(None, alias="S3_BUCKET_NAME")
	s3_region_name: str | None = Field(None, alias="S3_REGION_NAME")
	s3_presign_ttl_seconds: int = Field(259200, alias="S3_PRESIGN_TTL_SECONDS")
	uploads_prefix: str = Field("uploads/", alias="UPLOADS_PREFIX")
	videos_prefix: str = Field("video/", alias="VIDEOS_PREFIX")

	# Frontend
	frontend_return_url_base: str = Field("https://xn--e1aybc.xn--b1ahgb0aea5aq.online", alias="FRONTEND_RETURN_URL_BASE")

	# Public API base (для внешних вебхуков fal.ai)
	public_api_base_url: str = Field("https://xn--80aqu.xn--b1ahgb0aea5aq.online", alias="PUBLIC_API_BASE_URL")

	# Секрет подписи вебхука fal.ai (опционально)
	fal_webhook_token: str | None = Field(None, alias="FAL_WEBHOOK_TOKEN")

	# YooKassa
	yookassa_shop_id: str | None = Field(None, alias="YOOKASSA_SHOP_ID")
	yookassa_api_key: str | None = Field(None, alias="YOOKASSA_API_KEY")
	yookassa_api_base: str = Field("https://api.yookassa.ru", alias="YOOKASSA_API_BASE")
	yookassa_webhook_secret: str | None = Field(None, alias="YOOKASSA_WEBHOOK_SECRET")

	model_config = SettingsConfigDict(
		env_file=".env",
		env_file_encoding="utf-8",
		populate_by_name=True,
		extra="ignore",
	)

settings = Settings()


