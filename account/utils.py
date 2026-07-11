import os
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from integrations.registry import get_email


class Util:
    @staticmethod
    def verification_email_data(user):
        uid = urlsafe_base64_encode(force_bytes(str(user.id)))
        token = PasswordResetTokenGenerator().make_token(user)
        domain = os.getenv("EMAIL_URL_DOMAIN", "http://localhost:3000/")
        link = domain + "verify-email/" + uid + "/" + token
        return {
            "subject": "Verify Your Email Address",
            "link": link,
            "username": user.name,
            "to_email": user.email,
        }

    @staticmethod
    def send_verification_email(user):
        Util.send_email(Util.verification_email_data(user))

    @staticmethod
    def send_email(data):
        if data['subject'] == "Verify Your Email Address":
            body = f"""
Dear {data['username']},
Thank you for registering with ClipInsights! Please verify your email address by clicking the link below:
{data['link']}

If you did not create an account, please ignore this email. This link will expire in 1 hour.

Best regards,
The ClipInsights Team
"""
        else:
            body = f"""
Dear {data['username']},
We received a request to reset your password for your ClipInsights account. Please click the link below to reset your password:
{data['link']}

If you did not make this request, no action is needed. Please note that this link will expire in 1 hour.

Best regards,
The ClipInsights Team
"""
        get_email().send(to=data["to_email"], subject=data["subject"], body=body)