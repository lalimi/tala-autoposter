"""Shared browser helpers for the Playwright automation (scraper + commenter).

Routing the web-UI automation through a proxy is the main anti-ban lever: posting
goes through the official API (low risk), but scraping and commenting drive the
web UI from the VPS's datacenter IP, which is the flaggable part. Set SCRAPER_PROXY
to send that traffic through a residential/mobile proxy instead.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse


def proxy_launch_kwargs() -> dict:
    """Playwright launch kwargs for the proxy, or {} when none is configured.

    SCRAPER_PROXY accepts a full URL or host:port, e.g.
      http://user:pass@gate.provider.com:8000
      socks5://user:pass@host:1080
      1.2.3.4:8000
    """
    # Import settings so its load_dotenv() has run — otherwise SCRAPER_PROXY from
    # .env isn't in os.environ yet when the scraper is started standalone.
    try:
        from config import settings  # noqa: F401
    except Exception:
        pass
    raw = (os.getenv("SCRAPER_PROXY") or "").strip()
    if not raw:
        return {}
    if "://" not in raw:
        raw = "http://" + raw
    u = urlparse(raw)
    if not u.hostname:
        return {}
    server = f"{u.scheme}://{u.hostname}"
    if u.port:
        server += f":{u.port}"
    proxy = {"server": server}
    if u.username:
        proxy["username"] = u.username
    if u.password:
        proxy["password"] = u.password
    return {"proxy": proxy}
