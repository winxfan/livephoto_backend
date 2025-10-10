import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
	fal_key: str = Field(..., alias="FAL_KEY")
	fal_endpoint: str = Field("fal-ai/flux-pro", alias="FAL_ENDPOINT")
	port: int = Field(8000, alias="PORT")

	model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", populate_by_name=True)

settings = Settings()


