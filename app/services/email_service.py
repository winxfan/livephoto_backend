from email.message import EmailMessage
import ssl
import smtplib
from typing import List, Tuple, Optional, Any

from app.config import settings


def _smtp_conn():
	host = settings.smtp_server or settings.smtp_host
	port = settings.smtp_port
	return smtplib.SMTP_SSL(host, port, context=ssl.create_default_context())


def send_email_with_links(recipient_email: str, links: List[Any]) -> None:
	# Преобразуем входные элементы к публичным ссылкам
	from app.utils.s3_utils import parse_s3_url, get_file_url_with_expiry

	def _to_public_url(item: Any) -> Optional[str]:
		# Поддержка словарей с известными полями
		if isinstance(item, dict):
			if item.get("public_video_url"):
				return item["public_video_url"]
			url = item.get("result_s3_url") or item.get("video_url") or item.get("image_url") or item.get("input_s3_url")
			if isinstance(url, str):
				try:
					if url.startswith("s3://"):
						b, k = parse_s3_url(url)
						pub, _ = get_file_url_with_expiry(b, k)
						return pub
					return url
				except Exception:
					return None
			return None
		# Строка: может быть уже публичным URL или s3://
		if isinstance(item, str):
			try:
				if item.startswith("s3://"):
					b, k = parse_s3_url(item)
					pub, _ = get_file_url_with_expiry(b, k)
					return pub
				return item
			except Exception:
				return None
		return None

	public_links: List[str] = []
	for it in links:
		pu = _to_public_url(it)
		if pu:
			public_links.append(pu)

	msg = EmailMessage()
	msg["Subject"] = "Ваши видео готовы"
	msg["From"] = settings.smtp_email or settings.smtp_username
	msg["To"] = recipient_email
	body = "Ссылки на видео:\n" + "\n".join(public_links)
	msg.set_content(body)
	with _smtp_conn() as smtp:
		user = settings.smtp_email or settings.smtp_username
		if user and settings.smtp_password:
			smtp.login(user, settings.smtp_password)
		smtp.send_message(msg)


def send_payment_receipt(recipient_email: str, amount_rub: float, order_id: str, payment_id: str) -> None:
	msg = EmailMessage()
	msg["Subject"] = "Оплата получена"
	msg["From"] = settings.smtp_email or settings.smtp_username
	msg["To"] = recipient_email
	body = (
		f"Спасибо за оплату!\n\n"
		f"Сумма: {amount_rub:.2f} RUB\n"
		f"Заказ: {order_id}\n"
		f"Платеж: {payment_id}\n"
	)
	msg.set_content(body)
	with _smtp_conn() as smtp:
		user = settings.smtp_email or settings.smtp_username
		if user and settings.smtp_password:
			smtp.login(user, settings.smtp_password)
		smtp.send_message(msg)


def send_email_with_attachments(
	recipient_email: str,
	subject: str,
	body_text: str,
	attachments: List[Tuple[str, bytes, Optional[str]]],  # (filename, content, content_type)
) -> None:
	msg = EmailMessage()
	msg["Subject"] = subject
	msg["From"] = settings.smtp_email or settings.smtp_username
	msg["To"] = recipient_email
	msg.set_content(body_text)
	for filename, content, content_type in attachments:
		maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
		msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
	with _smtp_conn() as smtp:
		user = settings.smtp_email or settings.smtp_username
		if user and settings.smtp_password:
			smtp.login(user, settings.smtp_password)
		smtp.send_message(msg)
