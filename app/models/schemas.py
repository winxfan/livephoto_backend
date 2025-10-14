from pydantic import BaseModel
from typing import Optional

class ErrorResponse(BaseModel):
	error: str
	details: Optional[str] = None

class FalResult(BaseModel):
	status: str
	response_url: Optional[str] = None
	# Accept pass-through fields from fal.ai without strict validation
	# Using extra allowed would be ideal in Pydantic v2 via model_config
	class Config:
		extra = "allow"

