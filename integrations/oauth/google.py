import os
import time

from django.conf import settings
from google.auth.exceptions import TransportError
from google.auth.transport import requests
from google.oauth2 import id_token


class GoogleOAuthVerifier:
    def verify(self, token: str) -> dict:
        max_retries = 3
        retry_delay = 1
        idinfo = None

        for attempt in range(max_retries):
            try:
                idinfo = id_token.verify_oauth2_token(
                    token,
                    requests.Request(),
                    settings.GOOGLE_CLIENT_ID or os.environ.get("GOOGLE_CLIENT_ID"),
                )
                break
            except TransportError:
                if attempt == max_retries - 1:
                    raise
                time.sleep(retry_delay)
                retry_delay *= 2

        return {"email": idinfo["email"], "name": idinfo.get("name", "")}
