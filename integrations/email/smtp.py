from django.conf import settings
from django.core.mail import EmailMessage


class SMTPEmailSender:
    def send(self, to: str, subject: str, body: str) -> None:
        from_email = settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER
        EmailMessage(subject=subject, body=body, from_email=from_email, to=[to]).send()
