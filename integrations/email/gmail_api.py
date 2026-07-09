import base64
import os
from email.mime.text import MIMEText

from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailApiEmailSender:
    def __init__(self):
        self._service = None

    def _credentials(self) -> Credentials:
        return Credentials(
            token=None,
            refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
            token_uri=TOKEN_URI,
            client_id=os.environ["GMAIL_CLIENT_ID"],
            client_secret=os.environ["GMAIL_CLIENT_SECRET"],
            scopes=[GMAIL_SEND_SCOPE],
        )

    def _get_service(self):
        if self._service is None:
            self._service = build(
                "gmail",
                "v1",
                credentials=self._credentials(),
                cache_discovery=False,
            )
        return self._service

    def send(self, to: str, subject: str, body: str) -> None:
        from_email = settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER
        message = MIMEText(body)
        message["to"] = to
        message["from"] = from_email
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        self._get_service().users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
