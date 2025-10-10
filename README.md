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

## Новые эндпоинты

1) Создание заказа (Yandex Pay):
```bash
curl -X POST http://localhost:8000/create_order \
  -F "email=user@example.com" \
  -F "price_rub=199" \
  -F "files=@/path/one.png" -F "files=@/path/two.jpg" \
  -F 'prompts=["Animate softly","Make it cinematic"]'
```
Ответ: `{ "orderId": "...", "paymentUrl": "..." }`

2) Webhook Yandex Pay (для sandbox через ngrok):
```bash
curl -X POST https://<ngrok>/yandex-pay/webhook -H "X-Signature: <sig>" -d '{"orderId":"...","status":"PAID"}'
```

## Переменные окружения (дополнено)

- YANDEX_PAY_API_KEY
- YANDEX_PAY_MERCHANT_ID
- YANDEX_PAY_CREATE_URL (опционально; по умолчанию sandbox)
- YANDEX_PAY_WEBHOOK_SECRET (секрет для подписи webhook)
- SMTP_EMAIL, SMTP_PASSWORD, SMTP_HOST, SMTP_PORT

