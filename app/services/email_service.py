from email.message import EmailMessage
import ssl
import smtplib
from typing import List

from app.config import settings


def _smtp_conn():
	host = settings.smtp_server or settings.smtp_host
	port = settings.smtp_port
	return smtplib.SMTP_SSL(host, port, context=ssl.create_default_context())


def send_email_with_links(recipient_email: str, links: List[str]) -> None:
	msg = EmailMessage()
	msg["Subject"] = "Ваши видео готовы"
	msg["From"] = settings.smtp_email or settings.smtp_username
	msg["To"] = recipient_email
	body = "Ссылки на видео:\n" + "\n".join(links)
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
