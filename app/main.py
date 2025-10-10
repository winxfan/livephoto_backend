from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from app.utils.file_utils import save_upload_to_temp
from app.services.fal_service import upload_file_and_generate

app = FastAPI()

@app.post("/generate_video")
async def generate_video(
	image: UploadFile = File(...),
	prompt: str = Form("Animate this image"),
	sync_mode: bool = Form(True),
):
	tmp_path = await save_upload_to_temp(image)
	try:
		result = upload_file_and_generate(tmp_path, prompt=prompt, sync_mode=sync_mode)
		return JSONResponse(content=result)
	except HTTPException:
		raise
	except Exception as exc:
		raise HTTPException(status_code=500, detail=str(exc))
	finally:
		import os
		if tmp_path and os.path.exists(tmp_path):
			os.remove(tmp_path)
