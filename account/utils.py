from django.core.mail import EmailMessage


class Util:
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
        email = EmailMessage(
            subject=data['subject'],
            body=body,
            from_email='hello@clipinsights.com',
            to=[data['to_email']]
        )
        email.send()

def convert_to_bytes(mbs):
    return mbs * 1024 * 1024