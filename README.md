# fal-video-backend

Минимальный FastAPI-сервис для проксирования изображений в fal.ai и возврата видео-результата.

## Переменные окружения
Скопируйте `.env.example` в `.env` и задайте значения:

- FAL_KEY — ключ API fal.ai
- FAL_ENDPOINT — модель/эндпоинт, по умолчанию `fal-ai/flux-pro`
- PORT — порт запуска (по умолчанию 8000)

## Установка и запуск
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Пример запроса
```bash
curl -X POST http://localhost:8000/generate_video \
  -F "image=@/path/to/image.png" \
  -F "prompt=Animate this image into a cinematic short loop"
```

