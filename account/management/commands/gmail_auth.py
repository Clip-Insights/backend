import os

from django.core.management.base import BaseCommand
from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
# Fixed port so a Web OAuth client can list an exact Authorized redirect URI.
# Desktop clients don't need this; Web clients do (port=0 → random → mismatch).
LOCAL_REDIRECT_PORT = 8080


class Command(BaseCommand):
    help = "Obtain Gmail API refresh token for Cloud Run (run once locally)."

    def handle(self, *args, **options):
        secrets_file = os.environ.get("GMAIL_CLIENT_SECRETS_FILE", "client_secrets.json")
        if not os.path.isfile(secrets_file):
            self.stderr.write(
                f"Missing {secrets_file}. Download OAuth Web (or Desktop) credentials "
                "from Google Cloud Console or set GMAIL_CLIENT_SECRETS_FILE."
            )
            return

        redirect_uri = f"http://localhost:{LOCAL_REDIRECT_PORT}/"
        self.stdout.write(
            f"Using redirect {redirect_uri} — add it to the OAuth client's "
            "Authorized redirect URIs if it isn't there already."
        )

        flow = InstalledAppFlow.from_client_secrets_file(
            secrets_file,
            scopes=[GMAIL_SEND_SCOPE],
        )
        creds = flow.run_local_server(port=LOCAL_REDIRECT_PORT)

        self.stdout.write(self.style.SUCCESS("Add these to Cloud Run / .env:"))
        self.stdout.write(f"GMAIL_CLIENT_ID={creds.client_id}")
        self.stdout.write(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
        self.stdout.write(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
