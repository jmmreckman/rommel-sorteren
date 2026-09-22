import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger("rommel")


def stuur_mail(onderwerp: str, tekst: str) -> None:
    """Verstuurt een mail via gewone SMTP. Mist een van de instellingen
    (bv. mail niet geconfigureerd), dan wordt er gewoon niks gedaan - en
    een verzendfout mag nooit de rest van de app laten breken."""
    host = os.environ.get("SMTP_HOST")
    ontvanger = os.environ.get("NOTIFY_EMAIL")
    if not host or not ontvanger:
        return

    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        gebruiker = os.environ.get("SMTP_USER")
        wachtwoord = os.environ.get("SMTP_PASSWORD")
        afzender = os.environ.get("SMTP_FROM") or gebruiker or ontvanger

        msg = EmailMessage()
        msg["Subject"] = onderwerp
        msg["From"] = afzender
        msg["To"] = ontvanger
        msg.set_content(tekst)

        context = ssl.create_default_context()
        if port == 465:
            # Poort 465: direct versleuteld vanaf de eerste byte (SMTPS).
            with smtplib.SMTP_SSL(host, port, timeout=10, context=context) as server:
                if gebruiker and wachtwoord:
                    server.login(gebruiker, wachtwoord)
                server.send_message(msg)
        else:
            # Poort 587 (of 25): eerst plain, dan opwaarderen met STARTTLS.
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.starttls(context=context)
                if gebruiker and wachtwoord:
                    server.login(gebruiker, wachtwoord)
                server.send_message(msg)
    except Exception:
        logger.exception("Kon meldingsmail niet versturen")
