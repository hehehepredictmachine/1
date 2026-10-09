"""E-mail delivery. Production: SMTP (STARTTLS, certificate verified). Development: an explicitly labelled
DEV OUTBOX (table mail_outbox, visible to the admin in MQC_ENV=dev only). Production never silently skips sending."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from .security import new_id

log = logging.getLogger("mqcentral.mail")


class Mailer:
    def __init__(self, settings, db, clock):
        self.s, self.db, self.clock = settings, db, clock

    def send(self, to: str, subject: str, body: str) -> None:
        if self.s.mail_mode == "dev-outbox":
            if not self.s.dev:
                raise RuntimeError("DEV_OUTBOX_NOT_ALLOWED_IN_PRODUCTION")
            self.db.x("INSERT INTO mail_outbox(id, created_at, to_addr, subject, body) VALUES (?,?,?,?,?)",
                      (new_id(), self.clock.now(), to, "[DEV OUTBOX – nie wysłano] " + subject, body))
            log.info("[DEV OUTBOX] e-mail do %s: %s", to, subject)
            return
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, to, subject
        msg.set_content(body)
        ctx = ssl.create_default_context()
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=20) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls(context=ctx)
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)


def verify_mail(url: str) -> tuple[str, str]:
    return ("MasterQUO – potwierdź adres e-mail",
            f"Aby potwierdzić adres e-mail konta MasterQUO, otwórz link (ważny 24 h, jednorazowy):\n\n{url}\n\n"
            "Jeżeli to nie Ty zakładałeś konto, zignoruj tę wiadomość.")


def reset_mail(url: str) -> tuple[str, str]:
    return ("MasterQUO – ustawienie nowego hasła",
            f"Otrzymaliśmy prośbę o ustawienie nowego hasła. Link (ważny 1 h, jednorazowy):\n\n{url}\n\n"
            "Jeżeli to nie Ty, zignoruj wiadomość – hasło się nie zmieni.")


def invite_mail(url: str) -> tuple[str, str]:
    return ("MasterQUO – zaproszenie do konta",
            f"Administrator utworzył dla Ciebie konto MasterQUO. Ustaw własne hasło (link ważny 72 h, jednorazowy):\n\n{url}\n")


def exists_mail() -> tuple[str, str]:
    return ("MasterQUO – próba rejestracji",
            "Ktoś próbował założyć konto na ten adres, ale konto już istnieje. Jeżeli nie pamiętasz hasła, użyj opcji "
            "„Nie pamiętam hasła”. Jeżeli to nie Ty – zignoruj wiadomość.")
