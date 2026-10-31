from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "TW Stock Tracker"
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'twstock.db').as_posix()}"
    timezone: str = "Asia/Taipei"

    # logging: also write rotating files to data/logs/engine.log (needed when running as a service)
    log_to_file: bool = True

    # accounts & sessions (local accounts; the first admin is created from these or via `cli.py users create`)
    admin_username: str = ""
    admin_password: str = ""
    session_days: int = 30
    cookie_name: str = "tw_session"
    cookie_secure: bool = False  # set true behind HTTPS (Cloudflare Tunnel)
    login_max_failures: int = 5  # per username+ip within login_lockout_minutes
    login_lockout_minutes: int = 10

    # scheduler
    scheduler_enabled: bool = True
    realtime_interval_seconds: int = 10
    backfill_months: int = 6

    # Stock CRM backend proxied under /api/crm/* (separate process, separate repo)
    crm_base_url: str = "http://127.0.0.1:8765"
    crm_timeout: float = 30.0
    crm_facade_token: str = ""  # shared secret sent as X-Facade-Token so the CRM trusts X-User-Id
    crm_sync_alerts: bool = True  # mirror CRM target / stop prices as alert rules
    crm_proposals: bool = True  # write fired alerts back to CRM as interaction proposals
    crm_alert_kind: str = "alert"  # interaction kind for those proposals ("news" if the CRM lacks "alert")

    # http
    http_timeout: float = 20.0
    request_delay_seconds: float = 1.5  # TWSE throttles ~3 requests / 5 seconds

    # notifications
    notify_console: bool = True
    line_channel_access_token: str = ""
    line_user_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = ""
    email_to: str = ""  # comma separated

    @property
    def email_recipients(self) -> list[str]:
        return [x.strip() for x in self.email_to.split(",") if x.strip()]

    @property
    def line_enabled(self) -> bool:
        return bool(self.line_channel_access_token and self.line_user_id)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.email_from and self.email_recipients)


settings = Settings()
