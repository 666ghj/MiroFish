"""Email service: ACS amb dev fallback (log URL a consola)."""
import logging
from flask import current_app

logger = logging.getLogger('mirofish.email')


def send_invitation_email(to_email: str, to_name: str, accept_url: str) -> bool:
    subject = "Invitació a MiroFish"
    body = (
        f"Hola {to_name},\n\n"
        f"Has estat convidat/da a MiroFish.\n\n"
        f"Estableix la teva contrasenya accedint a:\n{accept_url}\n\n"
        f"Aquest enllaç caduca en {current_app.config['ACS_INVITATION_TTL_HOURS']} hores.\n"
    )
    return _send(to_email, subject, body)


def send_reset_password_email(to_email: str, reset_url: str) -> bool:
    subject = "Restabliment de contrasenya MiroFish"
    body = (
        f"Has sol·licitat restablir la contrasenya de MiroFish.\n\n"
        f"Accedeix a:\n{reset_url}\n\n"
        f"Aquest enllaç caduca en {current_app.config['ACS_RESET_PASSWORD_TTL_HOURS']} hora/es.\n"
        f"Si no has fet aquesta sol·licitud, ignora aquest missatge.\n"
    )
    return _send(to_email, subject, body)


def _send(to_email: str, subject: str, body: str) -> bool:
    conn_str = current_app.config.get('ACS_CONNECTION_STRING', '')
    sender = current_app.config.get('ACS_SENDER_ADDRESS', '')

    if not conn_str:
        logger.warning(
            "[EMAIL DEV — ACS no configurat]\n"
            f"  To:      {to_email}\n"
            f"  Subject: {subject}\n"
            f"  Body:\n{body}"
        )
        return True

    try:
        from azure.communication.email import EmailClient
        client = EmailClient.from_connection_string(conn_str)
        message = {
            "senderAddress": sender,
            "recipients": {"to": [{"address": to_email}]},
            "content": {"subject": subject, "plainText": body},
        }
        poller = client.begin_send(message)
        poller.result()
        return True
    except Exception as exc:
        logger.error(f"ACS send failed to {to_email}: {exc}")
        return False
