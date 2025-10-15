from email.message import EmailMessage
import ssl
import smtplib
from typing import List, Tuple, Optional, Any

from app.config import settings


def _smtp_conn():
	host = settings.smtp_server or settings.smtp_host
	port = settings.smtp_port
	return smtplib.SMTP_SSL(host, port, context=ssl.create_default_context())


def send_email_with_links(recipient_email: str, links: List[Any], request_id: Optional[str] = None) -> None:
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

	# Определяем ссылку для кнопки: приоритетно ссылка на фронтенд с request_id
	cta_url: Optional[str] = None
	base = settings.frontend_return_url_base or ""
	if base and request_id:
		cta_url = f"{base}/result.html?request_id={request_id}"
	elif base:
		cta_url = f"{base}/result.html"
	elif public_links:
		cta_url = public_links[0]

	# Текстовая версия (fallback для клиентов без HTML)
	text_body_lines = [
		"🎉 Ваше фото ожило! Посмотрите результат 🎬",
		"",
		"Здравствуйте! 💛",
		"",
		"Мы с радостью сообщаем — ваше фото ожило и превратилось в настоящее видео!",
		"Магия технологий и немного тепла сделали прошлое чуть ближе — теперь вы можете снова увидеть",
		"улыбки, взгляды и моменты, дорогие вашему сердцу.",
		"",
		"👉 Нажмите на кнопку ниже, чтобы посмотреть и скачать ожившее видео:",
	]
	if cta_url:
		text_body_lines.append(cta_url)
	text_body_lines.extend([
		"",
		"Пусть это маленькое чудо подарит вам немного ностальгии и вдохновения 🌿",
		"",
		"С любовью,",
		"Команда ОживиФото.online",
	])
	if public_links:
		text_body_lines.append("")
		text_body_lines.append("Ссылки на видео:")
		text_body_lines.extend(public_links)
	text_body = "\n".join(text_body_lines)

	# HTML-версия письма
	html_cta = (
		f'<a href="{cta_url}" target="_blank" rel="noopener" '
		f'style="display:inline-block; background:#2563eb; color:#ffffff; text-decoration:none; '
		f'padding:14px 22px; border-radius:10px; font-weight:600;">Посмотреть видео</a>'
		if cta_url else ""
	)
	html_body = f"""
	<div style="background:#f8fafc; padding:24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'Apple Color Emoji', 'Segoe UI Emoji', sans-serif; color:#0f172a;">
		<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"max-width:640px; margin:0 auto; background:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 4px 16px rgba(2, 6, 23, 0.08);\">
			<tr>
				<td style=\"padding:28px 28px 8px 28px; text-align:center;\">
					<div style=\"font-size:22px; font-weight:700;\">🎉 Ваше фото ожило! Посмотрите результат 🎬</div>
				</td>
			</tr>
			<tr>
				<td style=\"padding:8px 28px 0 28px; font-size:16px; line-height:1.6;\">
					<p style=\"margin:0 0 12px 0;\">Здравствуйте! 💛</p>
					<p style=\"margin:0 0 12px 0;\">Мы с радостью сообщаем — ваше фото ожило и превратилось в настоящее видео! Магия технологий и немного тепла сделали прошлое чуть ближе — теперь вы можете снова увидеть улыбки, взгляды и моменты, дорогие вашему сердцу.</p>
					<p style=\"margin:0 0 16px 0;\">👉 Нажмите на кнопку ниже, чтобы посмотреть и скачать ожившее видео:</p>
					<div style=\"text-align:center; margin:18px 0 6px 0;\">{html_cta}</div>
					<p style=\"margin:18px 0 6px 0;\">Пусть это маленькое чудо подарит вам немного ностальгии и вдохновения 🌿</p>
					<p style=\"margin:0 0 24px 0;\">С любовью,<br/>Команда ОживиФото.online</p>
				</td>
			</tr>
		</table>
		<div style=\"max-width:640px; margin:12px auto 0 auto; text-align:center; color:#64748b; font-size:12px;\">
			© {settings.frontend_return_url_base or 'ОживиФото.online'}
		</div>
	</div>
	"""

	msg = EmailMessage()
	msg["Subject"] = "🎉 Ваше фото ожило! Посмотрите результат 🎬"
	msg["From"] = settings.smtp_email or settings.smtp_username
	msg["To"] = recipient_email
	msg.set_content(text_body)
	msg.add_alternative(html_body, subtype="html")
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
