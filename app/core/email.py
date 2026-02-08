import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.core.config import settings


def send_reset_email(to_email: str, reset_token: str):
    reset_link = f"{settings.FRONTEND_URL}/#/reset-password-token?token={reset_token}"

    subject = "Reset your University Portal password"

    html = f"""
    <h2>Password Reset Request</h2>
    <p>You requested to reset your password.</p>
    <p>Click the link below to create a new password:</p>
    <a href="{reset_link}">{reset_link}</a>
    <p>This link expires in 30 minutes.</p>
    <p>If you did not request this, ignore this email.</p>
    """

    msg = MIMEMultipart()
    msg["From"] = settings.FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.send_message(msg)
