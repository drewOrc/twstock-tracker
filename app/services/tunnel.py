"""Where the engine is reachable from outside.

A quick Cloudflare tunnel (no domain) gets a new *.trycloudflare.com address every time it starts;
scripts/run_quick_tunnel.ps1 writes the current one to data/tunnel-url.txt. /api/health shows it and
the `tunnel_watch` job pushes it through the notification channels whenever it changes, so the
family can always find the door. A named tunnel (own domain) has a fixed hostname and needs none of
this; set PUBLIC_URL then.
"""
from __future__ import annotations

import logging
from datetime import datetime

from ..config import BASE_DIR, settings

log = logging.getLogger(__name__)
URL_FILE = BASE_DIR / "data" / "tunnel-url.txt"
SEEN_FILE = BASE_DIR / "data" / "tunnel-url.notified"


def current() -> dict | None:
    """{url, since, kind} or None when nothing is exposed."""
    if settings.public_url:
        return {"url": settings.public_url.rstrip("/"), "kind": "fixed", "since": None}
    try:
        lines = URL_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not lines or not lines[0].startswith("https://"):
        return None
    return {"url": lines[0].strip(), "kind": "temporary", "since": lines[1].strip() if len(lines) > 1 else None}


def watch(db=None) -> dict:
    """Job: announce a new temporary URL once."""
    cur = current()
    if cur is None or cur["kind"] != "temporary":
        return {"skipped": "no temporary tunnel"}
    try:
        seen = SEEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        seen = ""
    if seen == cur["url"]:
        return {"unchanged": cur["url"]}
    from .notifier import notifier

    result = notifier.send(
        "對外網址已更新",
        f"台股追蹤引擎現在的對外網址：{cur['url']}\n（臨時隧道，重啟後會變；{datetime.now():%m/%d %H:%M}）",
    )
    SEEN_FILE.write_text(cur["url"], encoding="utf-8")
    log.info("public url changed -> %s", cur["url"])
    return {"announced": cur["url"], "delivery": result}
