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
	smtp_port: int = Field(465, alias="SMTP_PORT")
	smtp_email: str | None = Field(None, alias="SMTP_EMAIL")
	smtp_password: str | None = Field(None, alias="SMTP_PASSWORD")

	model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", populate_by_name=True)

settings = Settings()


