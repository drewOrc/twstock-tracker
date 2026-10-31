"""Notification channels: console log, LINE Messaging API push, SMTP email.

Per-user routing: when a User is given, LINE goes to that user's line_user_id and email to that
user's address (falling back to the global .env targets when the user has none). Global sends
(screener digest, test from the admin) use the .env targets."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from ..config import settings
from ..models import User

log = logging.getLogger("notify")

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class Notifier:
    def channels(self, user: User | None = None) -> dict[str, bool]:
        line_to = (user.line_user_id if user and user.line_user_id else settings.line_user_id)
        email_to = [user.email] if user and user.email else settings.email_recipients
        return {
            "console": settings.notify_console,
            "line": bool(settings.line_channel_access_token and line_to),
            "email": bool(settings.smtp_host and settings.email_from and email_to),
        }

    def send(self, title: str, message: str, user: User | None = None) -> dict[str, str]:
        """Send to every enabled channel; returns {channel: 'ok' | 'error: ...'}."""
        results: dict[str, str] = {}
        who = f"@{user.username} " if user else ""
        if settings.notify_console:
            log.info("%s[%s] %s", who, title, message)
            results["console"] = "ok"
        line_to = user.line_user_id if user and user.line_user_id else settings.line_user_id
        if settings.line_channel_access_token and line_to:
            results["line"] = self._line(f"{title}\n{message}", line_to)
        email_to = [user.email] if user and user.email else settings.email_recipients
        if settings.smtp_host and settings.email_from and email_to:
            results["email"] = self._email(title, message, email_to)
        return results

    # ------------------------------------------------------------------ LINE
    @staticmethod
    def _line(text: str, to: str) -> str:
        try:
            r = httpx.post(
                LINE_PUSH_URL,
                headers={
                    "Authorization": f"Bearer {settings.line_channel_access_token}",
                    "Content-Type": "application/json",
                },
                json={"to": to, "messages": [{"type": "text", "text": text[:5000]}]},
                timeout=15,
            )
            if r.status_code >= 300:
                return f"error: HTTP {r.status_code} {r.text[:200]}"
            return "ok"
        except Exception as exc:  # noqa: BLE001
            log.warning("LINE push failed: %s", exc)
            return f"error: {exc}"

    # ------------------------------------------------------------------ email
    @staticmethod
    def _email(subject: str, body: str, recipients: list[str]) -> str:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.email_from
        msg["To"] = ", ".join(recipients)
        msg.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
                if settings.smtp_use_tls:
                    s.starttls()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
            return "ok"
        except Exception as exc:  # noqa: BLE001
            log.warning("email failed: %s", exc)
            return f"error: {exc}"


notifier = Notifier()
