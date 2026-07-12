import os

import resend
from django.conf import settings


class ResendEmailSender:
    def send(self, to: str, subject: str, body: str) -> None:
        resend.api_key = os.environ["RESEND_API_KEY"]
        from_email = settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER
        if not from_email:
            raise ValueError("DEFAULT_FROM_EMAIL (or EMAIL_USERNAME) is required for Resend")

        resend.Emails.send(
            {
                "from": from_email,
                "to": [to],
                "subject": subject,
                "text": body,
            }
        )
