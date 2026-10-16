from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_templated_email(
    *, subject: str, template: str, context: dict, from_email: str, recipient: str
):
    text_body = render_to_string(f"{template}.txt", context).strip()
    html_body = render_to_string(f"{template}.html", context).strip()
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[recipient],
    )
    message.attach_alternative(html_body, "text/html")
    return message.send()
