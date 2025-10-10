from email.message import EmailMessage
import ssl
import smtplib
from typing import List

from app.config import settings


def send_email_with_links(recipient_email: str, links: List[str]) -> None:
	msg = EmailMessage()
	msg["Subject"] = "Ваши видео готовы"
	msg["From"] = settings.smtp_email
	msg["To"] = recipient_email
	body = "Ссылки на видео:\n" + "\n".join(links)
	msg.set_content(body)
	context = ssl.create_default_context()
	with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context) as smtp:
		if settings.smtp_email and settings.smtp_password:
			smtp.login(settings.smtp_email, settings.smtp_password)
		smtp.send_message(msg)
