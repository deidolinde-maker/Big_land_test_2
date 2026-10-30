from __future__ import annotations

import json
import os
from urllib.parse import quote, urlsplit, urlunsplit

import requests


def _build_telegram_proxy_url() -> str:
    raw_proxy_url = (os.getenv("TELEGRAM_PROXY_URL") or "").strip()
    if not raw_proxy_url:
        return ""

    if not raw_proxy_url.startswith(("http://", "https://")):
        raw_proxy_url = f"http://{raw_proxy_url}"

    auth_secret = (os.getenv("TELEGRAM_PROXY_AUTH_SECRET") or "").strip()
    if auth_secret.startswith(("http://", "https://")):
        return auth_secret

    parsed = urlsplit(raw_proxy_url)
    if not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return raw_proxy_url

    proxy_user = (os.getenv("TELEGRAM_PROXY_USER") or "").strip()
    proxy_pass = (os.getenv("TELEGRAM_PROXY_PASS") or "").strip()
    proxy_creds = (os.getenv("TELEGRAM_PROXY_CREDS") or "").strip()
    if proxy_creds and not (proxy_user or proxy_pass) and ":" in proxy_creds:
        proxy_user, proxy_pass = (part.strip() for part in proxy_creds.split(":", 1))

    if proxy_user or proxy_pass:
        auth_part = f"{quote(proxy_user, safe='')}:{quote(proxy_pass, safe='')}"
    else:
        auth_part = auth_secret.strip().strip("@")
    if not auth_part:
        return raw_proxy_url

    return urlunsplit(
        (parsed.scheme, f"{auth_part}@{parsed.netloc}", parsed.path, parsed.query, parsed.fragment)
    )


def send_telegram_alert(text: str, alert_type: str = "tech") -> bool:
    """Send an alert through the configured Telegram endpoint or HTTP proxy."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    proxy_url = (os.getenv("TELEGRAM_PROXY_URL") or "").strip()
    proxy_auth_secret = (os.getenv("TELEGRAM_PROXY_AUTH_SECRET") or "").strip()
    proxy_creds = (os.getenv("TELEGRAM_PROXY_CREDS") or "").strip()

    def send_via_proxy_endpoint() -> bool:
        if not (proxy_url and proxy_auth_secret and proxy_creds):
            return False
        print(f"[TELEGRAM][{alert_type}] Sending via proxy endpoint")
        payload = {
            "title": f"Everyday_test [{alert_type}]",
            "text": text,
            "creds": proxy_creds,
            "parse_mode": "HTML",
            "disable_notification": False,
        }
        try:
            response = requests.post(
                proxy_url,
                headers={"Content-Type": "application/json", "X-Authentication": proxy_auth_secret},
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=15,
            )
            if response.ok:
                print(f"[TELEGRAM][{alert_type}] Sent via proxy endpoint (status={response.status_code})")
                return True
            body = (response.text or "").strip().replace("\n", " ")
            print(f"[TELEGRAM][{alert_type}] Proxy endpoint failed (status={response.status_code}): {body[:180]}")
        except Exception as exc:
            print(f"[TELEGRAM][{alert_type}] Proxy endpoint exception: {exc}")
        return False

    if not token or not chat_id:
        if send_via_proxy_endpoint():
            return True
        print(f"[TELEGRAM][{alert_type}] Skip send: Telegram token/chat are missing")
        return False

    try:
        runtime_proxy_url = _build_telegram_proxy_url()
        request_kwargs = {"data": {"chat_id": chat_id, "text": text}, "timeout": 10}
        if runtime_proxy_url:
            request_kwargs["proxies"] = {"http": runtime_proxy_url, "https": runtime_proxy_url}
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", **request_kwargs)
        if response.ok:
            print(f"[TELEGRAM][{alert_type}] Sent successfully (status={response.status_code})")
            return True
        body = (response.text or "").strip().replace("\n", " ")
        print(f"[TELEGRAM][{alert_type}] Send failed (status={response.status_code}): {body[:180]}")
    except Exception as exc:
        print(f"[TELEGRAM][{alert_type}] Direct send exception: {exc}")
    return send_via_proxy_endpoint()
