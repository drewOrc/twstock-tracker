"""Notification channels: console log, LINE Messaging API push, SMTP email."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from ..config import settings

log = logging.getLogger("notify")

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class Notifier:
    def channels(self) -> dict[str, bool]:
        return {
            "console": settings.notify_console,
            "line": settings.line_enabled,
            "email": settings.email_enabled,
        }

    def send(self, title: str, message: str) -> dict[str, str]:
        """Send to every enabled channel; returns {channel: 'ok' | 'error: ...'}."""
        results: dict[str, str] = {}
        if settings.notify_console:
            log.info("[%s] %s", title, message)
            results["console"] = "ok"
        if settings.line_enabled:
            results["line"] = self._line(f"{title}\n{message}")
        if settings.email_enabled:
            results["email"] = self._email(title, message)
        return results

    # ------------------------------------------------------------------ LINE
    @staticmethod
    def _line(text: str) -> str:
        try:
            r = httpx.post(
                LINE_PUSH_URL,
                headers={
                    "Authorization": f"Bearer {settings.line_channel_access_token}",
                    "Content-Type": "application/json",
                },
                json={"to": settings.line_user_id, "messages": [{"type": "text", "text": text[:5000]}]},
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
    def _email(subject: str, body: str) -> str:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.email_from
        msg["To"] = ", ".join(settings.email_recipients)
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
