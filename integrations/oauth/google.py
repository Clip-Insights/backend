import os
import time

from django.conf import settings
from google.auth.exceptions import TransportError
from google.auth.transport import requests
from google.oauth2 import id_token


def _google_client_ids() -> list[str]:
    ids: list[str] = []
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_EXTENSION_CLIENT_ID"):
        value = getattr(settings, key, None) or os.environ.get(key)
        if value and value not in ids:
            ids.append(value)
    return ids


class GoogleOAuthVerifier:
    def verify(self, token: str) -> dict:
        client_ids = _google_client_ids()
        if not client_ids:
            raise ValueError("No Google client IDs configured")

        last_error: ValueError | None = None
        http_request = requests.Request()

        for client_id in client_ids:
            max_retries = 3
            retry_delay = 1

            for attempt in range(max_retries):
                try:
                    idinfo = id_token.verify_oauth2_token(
                        token,
                        http_request,
                        client_id,
                    )
                    return {
                        "email": idinfo["email"],
                        "name": idinfo.get("name", ""),
                    }
                except TransportError:
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(retry_delay)
                    retry_delay *= 2
                except ValueError as exc:
                    last_error = exc
                    break

        raise last_error or ValueError("Invalid Google token")
