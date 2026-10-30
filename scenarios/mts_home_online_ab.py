"""Independent mts_home_online_ab scenario.

The scope is fixed in this module and URL cases are loaded only from
urls/brand_scopes/mts_home_online_ab.txt.
"""

import pytest
from playwright.sync_api import Page, expect
import allure
import os
import requests
import time
import sys
import json
from urllib.parse import quote, urlsplit, urlunsplit
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from site_configs import select_site_configs
from config.url_loader import (
    available_url_brands,
    build_site_configs_from_brand_scope,
    build_site_configs_from_all_urls,
    build_site_configs_from_urls,
)
from config.brand_scope import available_brand_scopes
from alert_events import queue_alert_event

try:
    # Avoid UnicodeEncodeError on Windows consoles with cp1251.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REALLY_SUBMIT = True # True — реально отправлять заявки
SUPPRESS_TECH_ALERTS = True

# ---------------------------------------------------------------------------
# Таблица ошибок → причин для Telegram-алертов
# ---------------------------------------------------------------------------

ERROR_REASONS = {
    "navigation_failed": ("Навигация на сайт не удалась", "Сайт не открылся в пределах таймаута"),
    "popup_not_found":  ("Попап не распознан",           "Попап не открылся после клика"),
    "form_not_filled":  ("Форма не заполнена",            "Поле недоступно или перекрыто оверлеем"),
    "submit_not_found": ("Кнопка отправки не найдена",    "Форма не в ожидаемом состоянии"),
    "no_confirmation":  ("Подтверждение не получено",     "Сайт не перешёл на /thanks"),
    "thanks_return_failed": ("Не выполнено закрытие страницы Спасибо", "Не удалось вернуться на главную без региона"),
    "click_failed":     ("Клик по кнопке не удался",      "Элемент не виден или не существует"),
    "city_not_found":   ("Город не найден в списке",      "Список городов не загрузился"),
    "city_no_redirect": ("Переход на город не произошёл", "URL не изменился после клика"),
}

ERROR_STEP_NAMES = {
    "navigation_failed": "Открытие страницы лендинга",
    "popup_not_found": "Появился попап заявки",
    "form_not_filled": "Заполнение формы заявки",
    "submit_not_found": "Отправка заявки после клика на кнопку отправки",
    "no_confirmation": "Отправка заявки после клика на кнопку отправки",
    "thanks_return_failed": "Закрытие страницы Спасибо и переход на главную без региона",
    "click_failed": "Клик по кнопке открытия формы",
    "city_not_found": "Изменить город в попапе заявки",
    "city_no_redirect": "Изменить город в попапе заявки",
}

SOFT_HOUSE_RETRY_VALUES = ("1", "2", "7")
SOFT_HOUSE_RETRY_URLS = {
    "https://beeline-internet.online/krasnodar",
    "https://beeline-ru.pro/moskovskaya_oblast",
    "https://shcherbinka.mts-home.online/address/ul-rabocaja-id10443",
    "https://shcherbinka.mts-home.online/address/ul-rabocaja-id104433",
    "https://shcherbinka.mts-home.online/address/ul-rabochaya-d-2-id203432",
}
SOFT_HOUSE_RETRY_VALUES_BY_URL = {
    "https://shcherbinka.mts-home.online/address/ul-rabocaja-id10443": ("2", "7", "1"),
    "https://shcherbinka.mts-home.online/address/ul-rabocaja-id104433": ("2", "7", "1"),
    "https://shcherbinka.mts-home.online/address/ul-rabochaya-d-2-id203432": ("2", "7", "1"),
}
HOUSE_SUGGEST_EXTENDED_TIMEOUT_URLS = {
    "https://mts-internet.online/sankt-peterburg",
    "https://mts-internet.online/sankt-peterburg/jk-ogni-zaliva",
}
HOUSE_SUGGEST_EXTENDED_TIMEOUT_PREFIXES = (
    "https://mts-internet.online/sankt-peterburg/",
)
STREET_VALUE_BY_URL = {
    "https://shcherbinka.mts-home.online/address/ul-rabocaja-id10443": "Чехова",
    "https://shcherbinka.mts-home.online/address/ul-rabocaja-id104433": "Чехова",
    "https://shcherbinka.mts-home.online/address/ul-rabochaya-d-2-id203432": "Чехова",
    "https://beeline-ru.pro/moskovskaya_oblast": "Чехова",
    "https://mts-internet.online/sankt-peterburg/jk-ogni-zaliva": "Ленсовета",
}
STREET_VALUE_BY_PREFIX = {
    "https://mts-internet.online/sankt-peterburg": "Ленсовета",
    "https://mts-internet.online/sankt-peterburg/": "Ленсовета",
}


def _normalize_runtime_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.netloc or "").lower()
    if not scheme or not host:
        return raw.rstrip("/")
    path = (parsed.path or "").rstrip("/")
    return f"{scheme}://{host}{path}"


def _is_beeline_runtime_url(url: str) -> bool:
    host = (urlsplit(_normalize_runtime_url(url)).netloc or "").lower()
    if not host:
        return False
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in (
            "beeline-ru.online",
            "online-beeline.ru",
            "beeline-internet.online",
            "beeline-ru.pro",
            "beeline-home.online",
            "beelline-internet.ru",
        )
    )


SUPPRESS_BEELINE_CHECKADDRESS_ALERTS = True
SUPPRESS_MTS_CHECKADDRESS_ALERTS = True


def _is_mts_runtime_url(url: str) -> bool:
    host = (urlsplit(_normalize_runtime_url(url)).netloc or "").lower()
    if not host:
        return False
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in (
            "mts-home.online",
            "mts-home-online.ru",
            "mts-home-gpon.ru",
            "internet-mts-home.online",
            "mts-internet.online",
        )
    )


def _is_mts_internet_runtime_url(url: str) -> bool:
    host = (urlsplit(_normalize_runtime_url(url)).netloc or "").lower()
    return host == "mts-internet.online"


def _use_soft_house_retry(page: Page, form_type: str) -> bool:
    if form_type not in {"profit", "connection", "checkaddress", "moving", "express-connection"}:
        return False
    current_url = _normalize_runtime_url(page.url or "")
    return current_url in SOFT_HOUSE_RETRY_URLS


def _soft_house_retry_values(page: Page) -> tuple[str, ...]:
    current_url = _normalize_runtime_url(page.url or "")
    return SOFT_HOUSE_RETRY_VALUES_BY_URL.get(current_url, SOFT_HOUSE_RETRY_VALUES)


def _house_suggest_timeout_ms(page: Page, base_timeout_ms: int) -> int:
    current_url = _normalize_runtime_url(page.url or "")
    if (
        current_url in HOUSE_SUGGEST_EXTENDED_TIMEOUT_URLS
        or any(current_url.startswith(prefix) for prefix in HOUSE_SUGGEST_EXTENDED_TIMEOUT_PREFIXES)
    ):
        return max(base_timeout_ms, 6000)
    return base_timeout_ms


def _street_value_for_url(page: Page) -> str:
    current_url = _normalize_runtime_url(page.url or "")
    if current_url in STREET_VALUE_BY_URL:
        return STREET_VALUE_BY_URL[current_url]
    for prefix, value in STREET_VALUE_BY_PREFIX.items():
        if current_url.startswith(prefix):
            return value
    return "Ленина"


def _now_msk_str() -> str:
    try:
        dt = datetime.now(ZoneInfo("Europe/Moscow"))
    except Exception:
        # Windows-среды без tzdata: fallback к фиксированному UTC+3.
        dt = datetime.now(timezone(timedelta(hours=3)))
    return dt.strftime("%Y-%m-%d %H:%M:%S (MSK)")


def _normalize_alert_text(text: str, max_len: int = 900) -> str:
    value = " ".join((text or "").split()).strip()
    if len(value) > max_len:
        return value[: max_len - 3] + "..."
    return value


def _build_form_alert_message(
    site_label: str,
    url: str,
    error_text: str,
    details: str = "",
    *,
    critical: bool = False,
) -> str:
    header = "🚨 Критическая ошибка автотеста формы" if critical else "🚨 Ошибка автотеста формы"
    report_url = os.getenv("ALLURE_URL", "").strip() or os.getenv("RUN_URL", "").strip()

    lines = [
        header,
        "",
        f"🕒 Время: {_now_msk_str()}",
        f"🌐 Лендинг: {site_label}",
    ]
    if url:
        lines.append(f"🔗 URL: {url}")
    lines.append(f"❌ Ошибка: {error_text}")
    if details:
        lines.append(f"🔎 Детали: {details}")
    if report_url:
        lines.append(f"🔗 Отчёт: {report_url}")

    return "\n".join(lines)


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

    # URL already has creds: http://user:pass@host:port
    if parsed.username or parsed.password:
        return raw_proxy_url

    proxy_user = (os.getenv("TELEGRAM_PROXY_USER") or "").strip()
    proxy_pass = (os.getenv("TELEGRAM_PROXY_PASS") or "").strip()

    proxy_creds = (os.getenv("TELEGRAM_PROXY_CREDS") or "").strip()
    if proxy_creds and not (proxy_user or proxy_pass):
        if ":" in proxy_creds:
            user_part, pass_part = proxy_creds.split(":", 1)
            proxy_user = user_part.strip()
            proxy_pass = pass_part.strip()

    auth_part = ""
    if proxy_user or proxy_pass:
        auth_part = f"{quote(proxy_user, safe='')}:{quote(proxy_pass, safe='')}"
    elif auth_secret:
        auth_part = auth_secret.strip().strip("@")

    if not auth_part:
        return raw_proxy_url

    netloc = f"{auth_part}@{parsed.netloc}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def send_telegram_alert(text: str, alert_type: str = "tech") -> bool:
    """Отправляет сообщение в Telegram и логирует результат отправки."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    proxy_url = (os.getenv("TELEGRAM_PROXY_URL") or "").strip()
    proxy_auth_secret = (os.getenv("TELEGRAM_PROXY_AUTH_SECRET") or "").strip()
    proxy_creds = (os.getenv("TELEGRAM_PROXY_CREDS") or "").strip()

    def _send_via_proxy_endpoint() -> bool:
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
            resp = requests.post(
                proxy_url,
                headers={
                    "Content-Type": "application/json",
                    "X-Authentication": proxy_auth_secret,
                },
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=15,
            )
            if resp.ok:
                print(f"[TELEGRAM][{alert_type}] Sent via proxy endpoint (status={resp.status_code})")
                return True
            body = (resp.text or "").strip().replace("\n", " ")
            print(f"[TELEGRAM][{alert_type}] Proxy endpoint failed (status={resp.status_code}): {body[:180]}")
            return False
        except Exception as e:
            print(f"[TELEGRAM][{alert_type}] Proxy endpoint exception: {e}")
            return False

    # Primary path for Jenkins proxy-only setup.
    if not token or not chat_id:
        if _send_via_proxy_endpoint():
            return True
        print(
            f"[TELEGRAM][{alert_type}] Skip send: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are missing "
            "and proxy endpoint is not usable"
        )
        return False

    print(f"[TELEGRAM][{alert_type}] Send attempt")
    try:
        runtime_proxy_url = _build_telegram_proxy_url()
        request_kwargs = {"data": {"chat_id": chat_id, "text": text}, "timeout": 10}
        if runtime_proxy_url:
            request_kwargs["proxies"] = {"http": runtime_proxy_url, "https": runtime_proxy_url}
            print(f"[TELEGRAM][{alert_type}] HTTP proxy enabled")

        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            **request_kwargs,
        )
        if resp.ok:
            print(f"[TELEGRAM][{alert_type}] Sent successfully (status={resp.status_code})")
            return True
        body = (resp.text or "").strip().replace("\n", " ")
        print(f"[TELEGRAM][{alert_type}] Send failed (status={resp.status_code}): {body[:180]}")

        # If direct send failed and proxy endpoint is configured, try it as fallback.
        return _send_via_proxy_endpoint()
    except Exception as e:
        print(f"[TELEGRAM][{alert_type}] Direct send exception: {e}")
        return _send_via_proxy_endpoint()


def mark_step_not_applicable(site_label: str, step_no: str, step_name: str, reason: str):
    text = f"[{site_label}] Шаг {step_no}: {step_name} — неприменим ({reason})"
    print(f"  ℹ️ {text}")
    allure.attach(
        text,
        name=f"Шаг {step_no}: {step_name} — пропуск",
        attachment_type=allure.attachment_type.TEXT,
    )


def send_step_alert(site_label: str, step_no: str, step_name: str, reason: str, page: "Page" = None):
    url = page.url if page else ""
    error_text = f'Не выполнен шаг "{step_name}"'
    details = _normalize_alert_text(reason)
    print(f"[STEP-ALERT] [{site_label}] Шаг {step_no}: {step_name} | {reason} | {url}")
    queue_alert_event(
        alert_type="step",
        site_label=site_label,
        page_url=url,
        step_name=step_name,
        error_text=error_text,
        details=details,
    )


class SiteUnavailableError(RuntimeError):
    """Сайт недоступен/не отвечает — текущий сайт нужно пропустить."""


def send_critical_alert(site_label: str, step_no: str, step_name: str, reason: str, page: "Page" = None):
    url = page.url if page else ""
    error_text = f'Не выполнен шаг "{step_name}"'
    details = _normalize_alert_text(reason)
    text = _build_form_alert_message(
        site_label,
        url,
        error_text,
        details,
        critical=True,
    )

    print(f"[CRITICAL] [{site_label}] Шаг {step_no}: {step_name} | {reason} | {url}")
    allure.attach(
        text,
        name=f"CRITICAL: Шаг {step_no} {step_name}",
        attachment_type=allure.attachment_type.TEXT,
    )
    queue_alert_event(
        alert_type="critical",
        site_label=site_label,
        page_url=url,
        step_name=step_name,
        error_text=error_text,
        details=details,
    )


def skip_site_due_unavailability(
    site_label: str,
    step_no: str,
    step_name: str,
    reason: str,
    page: "Page" = None,
):
    send_critical_alert(site_label, step_no, step_name, reason, page)
    pytest.skip(f"[{site_label}] {step_name}: {reason}")


def goto_or_handle_step(
    page: "Page",
    url: str,
    site_label: str,
    step_no: str,
    step_name: str,
):
    ok, is_critical, nav_reason = safe_goto(page, url)
    if ok:
        return

    reason = f"не удалось открыть {url} | {nav_reason}"
    if is_critical:
        skip_site_due_unavailability(site_label, step_no, step_name, reason, page)

    send_step_alert(site_label, step_no, step_name, reason, page)
    pytest.fail(f"[{site_label}] Шаг {step_no}: {step_name} | {reason}")



def log_error(error_code: str, page: "Page", site_label: str, extra: str = ""):
    """
    Печатает ошибку в консоль и мгновенно шлёт Telegram-алерт.

    error_code — ключ из ERROR_REASONS
    page       — для получения текущего URL
    site_label — домен сайта
    extra      — дополнительный контекст (опционально)
    """
    error_msg, reason = ERROR_REASONS.get(
        error_code, (error_code, "Неизвестная причина")
    )
    url  = page.url if page else ""

    # Консоль
    print(f"  ❌ {error_msg} | {reason} | {url}")

    step_name = ERROR_STEP_NAMES.get(error_code, error_msg)
    error_text = f'Не выполнен шаг "{step_name}"'
    if error_code == "no_confirmation":
        error_text += ", не произошел редирект на страницу Спасибо"

    detail_parts = [_normalize_alert_text(reason, max_len=300)]
    if extra:
        detail_parts.append(_normalize_alert_text(extra, max_len=500))
    details = " | ".join(p for p in detail_parts if p)

    message = _build_form_alert_message(site_label, url, error_text, details)
    if SUPPRESS_TECH_ALERTS:
        print("  [TELEGRAM][tech] Suppressed for current step")
    else:
        send_telegram_alert(message, alert_type="tech")

# ---------------------------------------------------------------------------
# Конфигурация форм (CSS-классы полей)
# ---------------------------------------------------------------------------

FORM_CONFIGS = {
    "checkaddress": {
        "street":     ".checkaddress_address_street",
        "house":      ".checkaddress_address_house",
        "phone":      ".checkaddress_address_phone",
        "submit":     ".checkaddress_address_button_send",
        "no_house":   False,
        "no_suggest": False,
    },
    "connection": {
        "street":     ".connection_address_street, [name='AddresStreet'], #city[placeholder='Адрес'], #city",
        "house":      ".connection_address_house, [name='AddresHouse']",
        "phone":      ".connection_address_phone, [name='Phone']",
        "submit":     ".connection_address_button_send, #submit.connection_address_button_send, #submit",
        "no_house":   False,
        "no_suggest": False,
    },
    "profit": {
        "street":     ".profit_address_street",
        "house":      ".profit_address_house",
        "phone":      ".profit_address_phone",
        "submit":     ".profit_address_button_send",
        "no_house":   False,
        "no_suggest": False,
    },
    "express-connection": {
        "street":     ".express-connection_address_street",
        "house":      ".express-connection_address_house",
        "phone":      ".express-connection_address_phone",
        "submit":     ".express-connection_address_button_send",
        "no_house":   False,
        "no_suggest": False,
    },
    "undecided": {
        "street":     ".undecided_address_street, .checkaddress_address_street",
        "house":      ".undecided_address_house, .checkaddress_address_house",
        "phone":      ".undecided_address_phone, .checkaddress_address_phone",
        "submit":     ".undecided_address_button_send, .checkaddress_address_button_send",
        "no_house":   False,
        "no_suggest": False,
    },
    "moving": {
        "street":     ".moving_address_street",
        "house":      ".moving_address_house",
        "phone":      ".moving_address_phone",
        "submit":     ".moving_address_button_send",
        "no_house":   False,
        "no_suggest": False,
    },
}

# CSS-классы кнопок, открывающих попапы (по типу формы)
POPUP_BUTTON_CLASSES = {
    "connection":         "#btnup.connection_address_button, .connection_address_button, #btnup",
    "connection_card":    ".connection_address_card_button",
    "checkaddress":       ".checkaddress_address_button, button.checkaddress_address_button, a.checkaddress_address_button, .button-checkaddress, #btncheckaddress, #btncheckaddress.checkaddress_address_button",
    "undecided":          ".checkaddress-undecided",
    "moving":             ".moving_address_button",
    "profit":             ".button-lead-catcher.profit_address_button, button.profit_address_button, a.profit_address_button, .profit_address_button",
    "express-connection": ".express-connection_address_button",
}

# Конфиги сайтов подаются через provider-loader (config/providers + config/loader.py).

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

SUCCESS_URL_MARKERS = ["/tilda/form1/submitted", "/thanks", "/thank_you_page"]
SITE_UNAVAILABLE_THRESHOLD_MS = 60_000
NAV_GOTO_TIMEOUT_MS = 20_000
NAV_RETRIES = 3
SUBMIT_CONFIRM_TIMEOUT_MS = 25_000
SUBMIT_CONFIRM_GRACE_MS = 2_000
CITY_LOADSTATE_TIMEOUT_MS = 7_000
HOUSE_ENABLE_TIMEOUT_MS = 3_500
FIREFOX_HOUSE_ENABLE_TIMEOUT_MS = 5_000
# Единый согласованный тестовый номер.
PHONE_TEST_VALUE = "1111111111"
PHONE_RETRY_VALUE = "1111111111"
PHONE_INPUT_DELAY_MS = 50
FIREFOX_PHONE_INPUT_DELAY_MS = 80
SUGGEST_TIMEOUT_MS = 1_500
FIREFOX_SUGGEST_TIMEOUT_MS = 3_000
CHECKBOX_SCAN_LIMIT = 20
CHECKBOX_CHECK_LIMIT = 4
CHECKBOX_VISIBILITY_TIMEOUT_MS = 250
CHECKBOX_ACTION_TIMEOUT_MS = 1_200
CHECKBOX_AGGRESSIVE_CHECK_LIMIT = 12
FIREFOX_CHECKBOX_VISIBILITY_TIMEOUT_MS = 500
FIREFOX_CHECKBOX_ACTION_TIMEOUT_MS = 1_800
FIREFOX_POPUP_CLICK_SETTLE_MS = 900
FIREFOX_POPUP_WAIT_TIMEOUT_MS = 13_000
FIREFOX_SUBMIT_TIMEOUT_BONUS_MS = 7_000

POPUP_CONTAINER_SELECTORS = [
    "div#popup", "div.popup",
    "[id*='popup']:not(script)",
    "[class*='popup']:not(script)",
    "[class*='modal']:not(script)",
    "[class*='fancybox']:not(script)",
    "[class*='overlay']:not(script)",
]

POPUP_OPEN_KEYWORDS = [
    "подключить", "получить консультацию", "оставить заявку",
    "заказать", "оформить", "узнать подробнее",
]
POPUP_SKIP_KEYWORDS = ["проверить адрес", "сменить город"]
MTS_INTERNET_SKIP_BUTTON_TEXT = "как подключить домашний интернет мтс"
MTS_INTERNET_SKIP_BUTTON_KEYWORDS = (
    "можно ли подключить тв",
    "тв и мобильную связь вместе с интернетом",
)

SUGGESTION_SELECTORS = [
    "[role='option']", "[role='listbox'] li",
    ".suggestions__item", ".suggestion-item",
    ".autocomplete__item", ".autocomplete-item", ".ui-menu-item",
    "[class*='suggest'] li", "[class*='autocomplete'] li",
    "[class*='dropdown'] li",
    "#street-list div", "#street-list li", "#street-list [data-value]",
    "#house-list div", "#house-list li", "#house-list [data-value]",
]

SERVICE_PLACE_VALUES = [
    "В квартиру",
    "В частный дом",
]

REGION_POPUP_DETECT_SELECTORS = [
    "#yesButton",
    "#noButton",
    ".popup-select-region__button.city",
    "button.region-search__button",
    ".region-search__button.button.button-red",
    ".region-search__button.button.button-green",
    ".popup-select-region__content-wrapper .popup__close",
]

MTS_MOBILE_BURGER_HOSTS = {
    "mts-home-gpon.ru",
    "mts-home.online",
    "mts-home-online.ru",
    "moskva.mts-home-online.ru",
    "moskva.mts-home.online",
}

MTS_MOBILE_BURGER_TOGGLE = "input#burger-nav"
MTS_MOBILE_BURGER_OPEN_SELECTORS = [
    "nav.burger-nav__menu",
    "ul.burger-nav__list",
]

DOMRU_MOBILE_CITY_HOSTS = {
    "dom-provider.online",
    "providerdom.ru",
    "moskva.dom-provider.online",
    "moskva.providerdom.ru",
}
DOMRU_MOBILE_CITY_TRIGGER_SELECTORS = [
    "nav.burger-nav__menu .header__city--mobile .city-bold",
    "nav.burger-nav__menu .header__city--mobile a.city",
    ".header__city--mobile .city-bold",
    ".header__city--mobile a.city",
]

THANKS_RETURN_SELECTORS = [
    "a:has-text('На главную')",
    "button:has-text('На главную')",
    "a:has-text('Вернуться')",
    "button:has-text('Вернуться')",
    "a:has-text('Закрыть')",
    "button:has-text('Закрыть')",
    "a:has-text('Продолжить')",
    "button:has-text('Продолжить')",
    ".popup__close",
    ".modal__close",
    ".fancybox-close-small",
    "[aria-label*='close']",
    "[aria-label*='закры']",
]

BUSINESS_NAV_SELECTORS = [
    "header a[href*='/business']",
    "nav a[href*='/business']",
    "a[href*='/business']",
    "header a[href*='business']",
    "nav a[href*='business']",
    "a[href*='business']",
    "a:has-text('\u0414\u043b\u044f \u0431\u0438\u0437\u043d\u0435\u0441\u0430')",
    "button:has-text('\u0414\u043b\u044f \u0431\u0438\u0437\u043d\u0435\u0441\u0430')",
    "a:has-text('\u0411\u0438\u0437\u043d\u0435\u0441')",
    "button:has-text('\u0411\u0438\u0437\u043d\u0435\u0441')",
]
BUSINESS_NAV_CLICK_TIMEOUT_MS = 2_500
BUSINESS_NAV_WAIT_TIMEOUT_MS = 5_000
POPUP_MAX_BUTTONS_PER_TEXT = 3
POPUP_REPEAT_NO_CONFIRMATION_SKIP_THRESHOLD = 2

SERVICE_MODE_ALL = "all"
SERVICE_MODE_CORE = "core"
SERVICE_MODE_CHOICES = {SERVICE_MODE_ALL, SERVICE_MODE_CORE}
def get_execution_profile_name() -> str:
    return (os.getenv("PYTEST_EXECUTION_PROFILE") or "desktop").strip().lower()


def is_mobile_execution_profile() -> bool:
    return get_execution_profile_name().startswith("mobile-")


def normalize_service_mode(value: str | None) -> str:
    mode = (value or SERVICE_MODE_ALL).strip().lower()
    if mode not in SERVICE_MODE_CHOICES:
        return SERVICE_MODE_ALL
    return mode


def get_browser_name_from_page(page: Page | None) -> str:
    if page is None:
        return ""
    try:
        browser = page.context.browser
        if browser and browser.browser_type:
            return (browser.browser_type.name or "").strip().lower()
    except Exception:
        pass
    return ""


def is_firefox_browser(page: Page | None) -> bool:
    return get_browser_name_from_page(page) == "firefox"


def browser_timeout(page: Page | None, default_ms: int, firefox_ms: int) -> int:
    return firefox_ms if is_firefox_browser(page) else default_ms


def popup_wait_timeout_ms(page: Page | None) -> int:
    return browser_timeout(page, 10_000, FIREFOX_POPUP_WAIT_TIMEOUT_MS)


def popup_click_settle_ms(page: Page | None) -> int:
    return browser_timeout(page, 500, FIREFOX_POPUP_CLICK_SETTLE_MS)


# ---------------------------------------------------------------------------
# Базовые утилиты
# ---------------------------------------------------------------------------

def iter_visible(locator):
    for i in range(locator.count()):
        item = locator.nth(i)
        try:
            if item.is_visible():
                yield item
        except Exception:
            pass


def dismiss_region_popup(page: Page):
    """
    Закрывает попап выбора/подтверждения региона на сайтах Beeline.
    Два варианта попапа:
      1. Кнопка "Да" (id=yesButton) — подтверждаем город
      2. Кнопка закрытия .popup__close внутри .popup-select-region__content-wrapper
    Безопасно вызывать на любом сайте — если попапа нет, просто ничего не делает.
    """
    # Ждём чуть — попап появляется с небольшой задержкой после загрузки
    page.wait_for_timeout(600)

    # Вариант 1: явные кнопки управления регионом (Да/Нет/Выбрать город)
    region_action_buttons = [
        ("#yesButton", "кнопка 'Да'"),
        ("#noButton", "кнопка 'Нет'"),
        (".popup-select-region__button.city", "кнопка выбора города (.popup-select-region__button.city)"),
        ("button.region-search__button", "кнопка выбора города (.region-search__button)"),
        (".region-search__button.button.button-red", "кнопка выбора города (red)"),
        (".region-search__button.button.button-green", "кнопка выбора города (green)"),
    ]
    for sel, label in region_action_buttons:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(force=True)
                page.wait_for_timeout(400)
                print(f"  [REGION] Попап региона обработан ({label})")
                return
        except Exception:
            pass

    # Вариант 1b: текстовая кнопка "Выбрать город"
    try:
        choose_btn = page.get_by_role("button", name="Выбрать город").first
        if (
            choose_btn.count() > 0
            and choose_btn.is_visible()
            and not _is_form_city_change_button(choose_btn)
        ):
            choose_btn.click(force=True)
            page.wait_for_timeout(400)
            print("  [REGION] Попап региона обработан (кнопка 'Выбрать город')")
            return
    except Exception:
        pass

    # Вариант 2: кнопка .popup__close внутри .popup-select-region__content-wrapper
    try:
        close_btn = page.locator(
            ".popup-select-region__content-wrapper .popup__close"
        ).first
        if close_btn.count() > 0 and close_btn.is_visible():
            close_btn.click(force=True)
            page.wait_for_timeout(400)
            print("  [REGION] Попап региона закрыт (кнопка .popup__close)")
            return
    except Exception:
        pass


def accept_cookie_banner(page: Page):
    """
    Принимает баннер согласия на cookies.
    Безопасно вызывать на любом сайте — если баннера нет, ничего не делает.
    Ищет кнопку по нескольким вариантам — разные сайты используют разную вёрстку.
    """
    # Ждём — Tilda/Beeline баннеры появляются с задержкой 0.5-1.5с
    page.wait_for_timeout(1500)

    cookie_selectors = [
        "#cookieButton",                       # Beeline: <div id="cookieButton">OK</div>
        "#cookieAccept",                       # РТК: <button id="cookieAccept">
        ".cookie-btn",                         # РТК: <button class="cookie-btn">
        "#cookie-accept",
        ".cookie-accept",
        "[class*='cookie'][class*='btn']",
        "[class*='cookie'][class*='button']",
        "[id*='cookie'][id*='accept']",
        "[id*='cookieAccept']",
        "[id*='cookieButton']",
        ".t886__btn",                          # Tilda cookie banner button
    ]
    for sel in cookie_selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(force=True)
                page.wait_for_timeout(400)
                print(f"  [COOKIE] Баннер принят ({sel})")
                return
        except Exception:
            pass

    # Запасной вариант: любой видимый элемент с текстом OK/Принять
    for sel in ["div", "button", "a", "span"]:
        try:
            elems = page.locator(sel)
            for i in range(min(elems.count(), 30)):
                el = elems.nth(i)
                if not el.is_visible(timeout=500):
                    continue
                text = (el.inner_text() or "").strip().lower()
                if text in {"ok", "ок", "принять", "accept", "agree"}:
                    el.click(force=True)
                    page.wait_for_timeout(400)
                    print(f"  [COOKIE] Баннер принят (текст: '{text}', тег: {sel})")
                    return
        except Exception:
            pass


def close_overlays(page: Page):
    # Шаг 1: попап подтверждения региона (Beeline-сайты) — важен, идёт первым
    dismiss_region_popup(page)

    # Шаг 2: баннер согласия на cookies (РТК и другие)
    accept_cookie_banner(page)
    close_mobile_burger_menu(page)

    try:
        ok = page.get_by_role("button", name="ОК", exact=True)
        if ok.count() > 0:
            ok.first.click(timeout=1000, force=True)
    except Exception:
        pass
    for btn in iter_visible(page.locator(
        "button,[role='button'],.popup__close,.modal__close,.fancybox-close-small"
    )):
        try:
            aria  = (btn.get_attribute("aria-label") or "").lower()
            title = (btn.get_attribute("title") or "").lower()
            text  = (btn.inner_text() or "").strip().lower()
            if ("close" in aria or "закры" in aria or "close" in title
                    or "закры" in title or text in {"x", "×", "✕", "закрыть"}):
                btn.click(timeout=1000, force=True)
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def close_mobile_burger_menu(page: Page):
    """
    Mobile pre-step: закрывает MTS burger menu/overlay, если он открыт.
    Безопасно для desktop: при отсутствии селекторов ничего не делает.
    """
    if not is_mobile_execution_profile():
        return

    try:
        vp = page.viewport_size or {}
        width = int(vp.get("width") or 0)
        if not (0 < width <= 480):
            return
    except Exception:
        return

    try:
        host = (urlsplit(page.url).netloc or "").lower()
    except Exception:
        host = ""

    if not any(host.endswith(h) for h in MTS_MOBILE_BURGER_HOSTS):
        return

    toggle = page.locator(MTS_MOBILE_BURGER_TOGGLE).first

    is_open_by_menu = False
    for sel in MTS_MOBILE_BURGER_OPEN_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                is_open_by_menu = True
                break
        except Exception:
            pass

    is_open_by_toggle = False
    try:
        if toggle.count() > 0 and toggle.is_visible():
            is_open_by_toggle = toggle.is_checked()
    except Exception:
        is_open_by_toggle = False

    if not (is_open_by_menu or is_open_by_toggle):
        return

    try:
        if toggle.count() > 0 and toggle.is_visible():
            toggle.click(force=True)
            page.wait_for_timeout(150)
            print("  [MOBILE] Burger menu closed via #burger-nav toggle")
    except Exception:
        pass

    # Safety net: dismiss residual menu overlays if any.
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(120)
    except Exception:
        pass


def is_domru_mobile_city_context(page: Page) -> bool:
    if not is_mobile_execution_profile():
        return False

    try:
        vp = page.viewport_size or {}
        width = int(vp.get("width") or 0)
        # In CI mobile emulation viewport can be unavailable (0/None).
        # Reject only clearly desktop-like widths.
        if width > 900:
            return False
    except Exception:
        pass

    try:
        host = (urlsplit(page.url).netloc or "").lower()
    except Exception:
        host = ""
    if any(host.endswith(h) for h in DOMRU_MOBILE_CITY_HOSTS):
        return True

    # Fallback: detect by DOM structure if hostname is not informative.
    try:
        if page.locator("input#burger-nav").count() > 0 and page.locator(".header__city--mobile").count() > 0:
            return True
    except Exception:
        pass
    return False


def open_domru_mobile_city_burger(page: Page) -> bool:
    """
    Для mobile Domru город выбирается из burger-меню.
    Возвращает True, если mobile-меню с city trigger видно.
    """
    if not is_domru_mobile_city_context(page):
        return False

    def city_trigger_visible() -> bool:
        for sel in DOMRU_MOBILE_CITY_TRIGGER_SELECTORS:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    return True
            except Exception:
                pass
        return False

    if city_trigger_visible():
        return True

    toggle = page.locator("input#burger-nav").first

    try:
        if toggle.count() > 0:
            changed = toggle.evaluate(
                """el => {
                  el.checked = true;
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  return true;
                }"""
            )
            if changed:
                page.wait_for_timeout(220)
                if city_trigger_visible():
                    print("  [MOBILE][CITY] Burger opened via toggle evaluate")
                    return True
    except Exception:
        pass

    # 1) Предпочитаем label-триггер (классический burger UX).
    for open_sel in ["label[for='burger-nav']", "input#burger-nav"]:
        try:
            opener = page.locator(open_sel).first
            if opener.count() > 0:
                if open_sel != "input#burger-nav" and not opener.is_visible():
                    continue
                opener.click(force=True)
                page.wait_for_timeout(180)
                if city_trigger_visible():
                    print("  [MOBILE][CITY] Burger opened for city selector")
                    return True
        except Exception:
            pass

    # 2) Fallback: программно открыть checkbox burger.
    try:
        changed = page.evaluate(
            """
            () => {
              const el = document.querySelector('input#burger-nav');
              if (!el) return false;
              el.checked = true;
              el.dispatchEvent(new Event('change', { bubbles: true }));
              return true;
            }
            """
        )
        if changed:
            page.wait_for_timeout(220)
            if city_trigger_visible():
                print("  [MOBILE][CITY] Burger opened via JS fallback")
                return True
    except Exception:
        pass

    return False


def close_popup_or_page(page: Page):
    current = page.url.lower()
    if any(m in current for m in SUCCESS_URL_MARKERS):
        return
    for btn in iter_visible(page.locator(
        "button,[role='button'],.popup__close,.modal__close,.fancybox-close-small"
    )):
        try:
            aria  = (btn.get_attribute("aria-label") or "").lower()
            title = (btn.get_attribute("title") or "").lower()
            text  = (btn.inner_text() or "").strip().lower()
            if ("close" in aria or "закры" in aria or "close" in title
                    or "закры" in title or text in {"x", "×", "✕", "закрыть"}):
                btn.click(force=True)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


def safe_goto(
    page: Page,
    url: str,
    retries: int = NAV_RETRIES,
    goto_timeout_ms: int = NAV_GOTO_TIMEOUT_MS,
    outage_threshold_ms: int = SITE_UNAVAILABLE_THRESHOLD_MS,
) -> tuple[bool, bool, str]:
    # Если застряли на странице благодарности — даём браузеру завершить редирект
    try:
        if any(m in page.url.lower() for m in SUCCESS_URL_MARKERS):
            page.wait_for_timeout(2000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(300)

    started_at = time.monotonic()
    last_error = ""

    for attempt in range(1, retries + 1):
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout_ms)
            page.wait_for_timeout(500)

            status = None
            try:
                status = response.status if response else None
            except Exception:
                status = None

            if status is not None and status >= 400:
                reason = f"HTTP {status}"
                print(f"  [NAV] ❌ {url} ({reason})")
                return False, True, reason

            current_url = (page.url or "").lower()
            if current_url.startswith("chrome-error://") or "about:neterror" in current_url:
                last_error = f"browser net error ({current_url})"
                print(f"  [NAV] Попытка {attempt}/{retries}: {last_error}")
                page.wait_for_timeout(1500)
                continue

            print(f"  [NAV] {url}")
            return True, False, ""
        except Exception as e:
            last_error = str(e).replace("\n", " ")[:220]
            print(f"  [NAV] Попытка {attempt}/{retries}: {last_error}")
            page.wait_for_timeout(1500)

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    last_error_upper = (last_error or "").upper()
    critical_nav_markers = (
        "ERR_CERT_DATE_INVALID",
        "ERR_CERT_AUTHORITY_INVALID",
        "ERR_CERT_COMMON_NAME_INVALID",
        "ERR_SSL_PROTOCOL_ERROR",
        "ERR_CONNECTION_TIMED_OUT",
        "ERR_CONNECTION_REFUSED",
        "ERR_CONNECTION_CLOSED",
        "ERR_CONNECTION_RESET",
        "ERR_NAME_NOT_RESOLVED",
    )
    has_critical_nav_marker = any(marker in last_error_upper for marker in critical_nav_markers)
    is_critical = elapsed_ms >= outage_threshold_ms or has_critical_nav_marker
    if is_critical:
        reason = f"timeout {elapsed_ms // 1000}с (>={outage_threshold_ms // 1000}с), last_error={last_error or 'n/a'}"
    else:
        reason = f"nav_failed {elapsed_ms // 1000}с, last_error={last_error or 'n/a'}"
    print(f"  [NAV] ❌ Не удалось перейти на {url} | {reason}")
    return False, is_critical, reason


def _is_success_url(url: str) -> bool:
    return any(m in (url or "").lower() for m in SUCCESS_URL_MARKERS)


def wait_for_success_url(page: Page, timeout_ms: int = SUBMIT_CONFIRM_TIMEOUT_MS) -> bool:
    effective_timeout_ms = timeout_ms + (
        FIREFOX_SUBMIT_TIMEOUT_BONUS_MS if is_firefox_browser(page) else 0
    )
    print(f"  [SUBMIT] Ждём подтверждения (до {effective_timeout_ms // 1000}с)...")
    poll_ms = 300
    elapsed = 0

    while elapsed < effective_timeout_ms:
        current_url = page.url
        if _is_success_url(current_url):
            print(f"  [SUBMIT] ✅ {current_url}")
            return True
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms

    # Грейс-период: часть сайтов делает поздний redirect после сабмита
    page.wait_for_timeout(SUBMIT_CONFIRM_GRACE_MS)
    if _is_success_url(page.url):
        print(f"  [SUBMIT] ✅ {page.url} (grace)")
        return True

    # Редкий кейс: подтверждение открылось в новой вкладке
    for p in page.context.pages:
        try:
            if _is_success_url(p.url):
                print(f"  [SUBMIT] ✅ в новой вкладке: {p.url}")
                return True
        except Exception:
            pass

    print(f"  [SUBMIT] ❌ URL: {page.url}")
    return False


def _is_cf7_feedback_url(url: str) -> bool:
    normalized = (url or "").lower()
    return "/wp-json/contact-form-7/" in normalized and "/feedback" in normalized


def _extract_cf7_feedback_status(response) -> str:
    try:
        payload = response.json()
    except Exception:
        return ""

    status = ""
    if isinstance(payload, dict):
        status = str(payload.get("status") or "").strip().lower()
        if not status and isinstance(payload.get("data"), dict):
            status = str(payload["data"].get("status") or "").strip().lower()
    return status


def wait_for_cf7_feedback_status(page: Page, timeout_ms: int = 2_000) -> str:
    """
    Пытается поймать AJAX-ответ Contact Form 7 feedback.
    Возвращает status (например, mail_sent/validation_failed) или "".
    """
    try:
        response = page.wait_for_response(
            lambda r: _is_cf7_feedback_url(r.url),
            timeout=timeout_ms,
        )
    except Exception:
        return ""

    return _extract_cf7_feedback_status(response)


def _snapshot_submit_network(page: Page) -> set[str]:
    try:
        items = page.evaluate(
            """() => {
                return performance.getEntriesByType("resource")
                    .filter(e => ["fetch", "xmlhttprequest"].includes((e.initiatorType || "").toLowerCase()))
                    .map(e => String(e.name || ""));
            }"""
        )
    except Exception:
        return set()
    return {item for item in (items or []) if item}


TRACKING_REQUEST_MARKERS = (
    "mc.yandex.",
    "metrika.yandex",
    "/clmap/",
    "/webvisor/",
    "metrika",
    "google-analytics",
    "googletagmanager",
    "clarity.ms",
)


def _has_non_tracking_requests(urls: list[str]) -> bool:
    for url in urls:
        normalized = (url or "").lower()
        if not normalized:
            continue
        if any(marker in normalized for marker in TRACKING_REQUEST_MARKERS):
            continue
        return True
    return False


def _compact_request_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        compact = f"{host}{path}"
        return compact[:140] if compact else (url or "")[:140]
    except Exception:
        return (url or "")[:140]


def _trigger_native_form_submit(container) -> bool:
    try:
        return bool(
            container.evaluate(
                """(root) => {
                    const submitEl =
                        root.querySelector("button[type='submit'], input[type='submit'], .wpcf7-submit")
                        || root.querySelector("button, input[type='button']");
                    if (submitEl) {
                        submitEl.click();
                    }

                    const form = root.closest("form") || root.querySelector("form");
                    if (!form) return !!submitEl;
                    if (typeof form.requestSubmit === "function") {
                        form.requestSubmit();
                        return true;
                    }
                    if (typeof form.submit === "function") {
                        form.submit();
                        return true;
                    }
                    return !!submitEl;
                }"""
            )
        )
    except Exception:
        return False


def _is_form_city_change_button(locator) -> bool:
    """Не считать штатную кнопку смены города в address-form региональным popup."""
    try:
        classes = (locator.get_attribute("class") or "").split()
        required = {
            "autocomplete-city-change",
            "button-select-city",
            "checkaddress_address_button_change_city",
        }
        return required.issubset(classes)
    except Exception:
        return False


def detect_visible_region_popup(page: Page) -> str | None:
    for sel in REGION_POPUP_DETECT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return sel
        except Exception:
            pass

    try:
        choose_btn = page.get_by_role("button", name="Выбрать город").first
        if (
            choose_btn.count() > 0
            and choose_btn.is_visible()
            and not _is_form_city_change_button(choose_btn)
        ):
            return "button:has-text('Выбрать город')"
    except Exception:
        pass

    return None


def _wait_until_left_success_url(page: Page, timeout_ms: int = 6000) -> bool:
    poll_ms = 250
    elapsed = 0
    while elapsed < timeout_ms:
        if not _is_success_url(page.url):
            return True
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms
    return not _is_success_url(page.url)


def verify_thanks_close_and_return(
    page: Page,
    return_url: str,
    allow_root_return: bool = False,
) -> tuple[bool, str]:
    with allure.step("Проверка: закрытие Thanks и возврат на главную без региона"):
        if not _is_success_url(page.url):
            return False, f"страница не в состоянии Thanks ({page.url})"

        action = "none"
        for sel in THANKS_RETURN_SELECTORS:
            try:
                btn = page.locator(sel).first
                if btn.count() == 0 or not btn.is_visible():
                    continue
                btn.click(force=True)
                if _wait_until_left_success_url(page, timeout_ms=5000):
                    action = f"click:{sel}"
                    break
            except Exception:
                pass

        if _is_success_url(page.url):
            try:
                page.go_back(wait_until="domcontentloaded", timeout=7000)
                page.wait_for_timeout(500)
                if _wait_until_left_success_url(page, timeout_ms=2500):
                    action = "go_back"
            except Exception:
                pass

        if _is_success_url(page.url):
            try:
                page.goto(return_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(500)
                if _wait_until_left_success_url(page, timeout_ms=2500):
                    action = "goto_return_url"
            except Exception as e:
                return False, f"не удалось вернуться на главную ({e})"

        if _is_success_url(page.url):
            return False, f"после action={action} остались на Thanks ({page.url})"

        expected_host = (urlsplit(return_url).netloc or "").lower()
        current_host = (urlsplit(page.url).netloc or "").lower()
        if expected_host and current_host and expected_host != current_host:
            # Для ряда лендингов допустим возврат с регионального поддомена
            # на базовый домен (например, moskva.site.ru -> site.ru).
            host_fallback_ok = (
                allow_root_return
                and expected_host.endswith("." + current_host)
            )
            if host_fallback_ok:
                print(
                    "  [THANKS] Возврат на базовый домен допустим "
                    f"({expected_host} -> {current_host})"
                )
            else:
                return False, f"возврат на другой хост ({current_host} вместо {expected_host})"

        expected_path = (urlsplit(return_url).path or "").rstrip("/")
        current_path = (urlsplit(page.url).path or "").rstrip("/")
        if expected_path and expected_path != "/" and not current_path.startswith(expected_path):
            if allow_root_return and current_path in ("", "/"):
                print(f"  [THANKS] Возврат на корень допустим для expected={expected_path}")
            else:
                return False, f"возврат на другой путь ({current_path} вместо {expected_path})"

        region_sel = detect_visible_region_popup(page)
        if region_sel:
            return False, f"после возврата виден region-popup ({region_sel})"

        print(f"  [THANKS] ✅ Возврат на главную подтверждён ({action})")
        return True, action


# ---------------------------------------------------------------------------
# Подсказки
# ---------------------------------------------------------------------------

def choose_first_suggestion(
    page: Page,
    timeout_ms: int = SUGGEST_TIMEOUT_MS,
    field=None,
    allow_keyboard_fallback: bool = True,
) -> bool:
    def click_suggestion_item(item) -> bool:
        # Some checkaddress widgets render suggestions inside custom wrappers;
        # try multiple click strategies before giving up.
        try:
            item.scroll_into_view_if_needed()
        except Exception:
            pass
        try:
            item.click(timeout=3000, force=True)
            return True
        except Exception:
            pass
        try:
            item.click(timeout=3000)
            return True
        except Exception:
            pass
        try:
            item.dispatch_event("click")
            return True
        except Exception:
            pass
        return False

    poll_ms = 150
    elapsed = 0
    while elapsed < timeout_ms:
        for sel in SUGGESTION_SELECTORS:
            loc = page.locator(sel)
            for i in range(loc.count()):
                item = loc.nth(i)
                try:
                    if item.is_visible() and (item.inner_text() or "").strip():
                        print(f"  [SUGGEST] '{item.inner_text().strip()[:50]}'")
                        if click_suggestion_item(item):
                            page.wait_for_timeout(300)
                            return True
                except Exception:
                    pass
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms

    if not allow_keyboard_fallback:
        print("  [SUGGEST] No visible suggestions within timeout")
        return False

    print("  [SUGGEST FALLBACK] ArrowDown+Enter")
    try:
        if field is not None:
            try:
                field.scroll_into_view_if_needed()
                field.click(force=True)
            except Exception:
                pass
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(200)
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        return True
    except Exception:
        return False


def _service_place_locator(container, service_value: str):
    return container.locator(f"input[name='Place'][value='{service_value}']")


def detect_service_place_values(container) -> list[str]:
    values = []
    for service_value in SERVICE_PLACE_VALUES:
        try:
            if _service_place_locator(container, service_value).count() > 0:
                values.append(service_value)
        except Exception:
            pass
    return values


def resolve_service_values_for_mode(
    form_type: str,
    detected_service_values: list[str],
    service_mode: str,
) -> list[str | None]:
    mode = normalize_service_mode(service_mode)

    if form_type == "profit":
        return [None]

    if not detected_service_values:
        print("  [FORM] Варианты услуги Place не обнаружены — submit без переключения")
        return [None]

    if mode == SERVICE_MODE_CORE:
        primary_value = detected_service_values[0]
        print(f"  [FORM] CORE: используем базовый вариант услуги: {primary_value}")
        return [primary_value]

    print(f"  [FORM] Найдены варианты услуги: {', '.join(detected_service_values)}")
    return detected_service_values


def select_service_place_value(container, service_value: str) -> bool:
    options = _service_place_locator(container, service_value)
    try:
        count = options.count()
    except Exception:
        count = 0
    if count == 0:
        print(f"  [FORM] Вариант услуги не найден: {service_value}")
        return False

    for idx in range(count):
        option = options.nth(idx)
        try:
            option.check(force=True)
            print(f"  [FORM] Вариант услуги выбран: {service_value}")
            return True
        except Exception:
            try:
                option.click(force=True)
                print(f"  [FORM] Вариант услуги выбран (click): {service_value}")
                return True
            except Exception:
                pass
    print(f"  [FORM] Не удалось выбрать вариант услуги: {service_value}")
    return False


def _check_required_checkboxes_via_dom(container) -> tuple[int, int, int]:
    """
    Быстро отмечает обязательные чекбоксы (required / aria-required=true), включая скрытые input.
    Возвращает: total, required_found, required_checked.
    """
    try:
        data = container.evaluate(
            """(root) => {
                const boxes = Array.from(root.querySelectorAll("input[type='checkbox']"));
                let requiredFound = 0;
                let requiredChecked = 0;
                for (const box of boxes) {
                    const ariaRequired = (box.getAttribute('aria-required') || '').toLowerCase();
                    const isRequired = !!box.required || ariaRequired === 'true';
                    if (!isRequired) continue;
                    requiredFound += 1;
                    if (box.disabled || box.checked) continue;
                    box.checked = true;
                    box.dispatchEvent(new Event('input', { bubbles: true }));
                    box.dispatchEvent(new Event('change', { bubbles: true }));
                    requiredChecked += 1;
                }
                return {
                    total: boxes.length,
                    requiredFound,
                    requiredChecked
                };
            }"""
        )
        total = int((data or {}).get("total", 0))
        required_found = int((data or {}).get("requiredFound", 0))
        required_checked = int((data or {}).get("requiredChecked", 0))
        return total, required_found, required_checked
    except Exception:
        return 0, 0, 0


def apply_form_checkboxes(page: Page, container, aggressive: bool = False):
    """
    Ставит обязательные чекбоксы и ограниченное число дополнительных.
    aggressive=True используется перед retry submit, чтобы шире пройти по чекбоксам.
    """
    total, required_found, required_checked = _check_required_checkboxes_via_dom(container)
    if total <= 0:
        return

    scan_total = min(total, CHECKBOX_SCAN_LIMIT)
    optional_limit = CHECKBOX_AGGRESSIVE_CHECK_LIMIT if aggressive else CHECKBOX_CHECK_LIMIT
    visibility_timeout = browser_timeout(
        page, CHECKBOX_VISIBILITY_TIMEOUT_MS, FIREFOX_CHECKBOX_VISIBILITY_TIMEOUT_MS
    )
    action_timeout = browser_timeout(
        page, CHECKBOX_ACTION_TIMEOUT_MS, FIREFOX_CHECKBOX_ACTION_TIMEOUT_MS
    )
    checked_optional = 0
    checked_required_force = 0
    print(
        f"  [FORM] Checkbox scan: total={total}, scan_limit={scan_total}, "
        f"optional_limit={optional_limit}, required_found={required_found}, "
        f"required_checked={required_checked}, aggressive={aggressive}, "
        f"visibility_timeout={visibility_timeout}ms, action_timeout={action_timeout}ms"
    )

    checkboxes = container.locator("input[type='checkbox']")
    for idx in range(scan_total):
        if checked_optional >= optional_limit:
            print(f"  [FORM] Optional checkbox limit reached: {checked_optional}")
            break

        cb = checkboxes.nth(idx)
        is_required = False
        try:
            is_required = bool(
                cb.evaluate(
                    """(el) => {
                        const ariaRequired = String(el.getAttribute('aria-required') || '').toLowerCase();
                        return !!el.required || ariaRequired === 'true';
                    }"""
                )
            )
        except Exception:
            is_required = False

        if is_required:
            try:
                if cb.is_checked():
                    continue
            except Exception:
                pass
            try:
                cb.check(force=True, timeout=action_timeout)
                checked_required_force += 1
                continue
            except Exception as e:
                err = str(e).replace("\n", " ")[:160]
                print(f"  [FORM] Required checkbox force-check skip #{idx + 1}: {err}")

        try:
            if not aggressive and not cb.is_visible(timeout=visibility_timeout):
                continue
        except Exception:
            continue

        try:
            if cb.is_checked():
                continue
        except Exception:
            pass

        try:
            cb.check(force=True, timeout=action_timeout)
            checked_optional += 1
        except Exception as e:
            err = str(e).replace("\n", " ")[:160]
            print(f"  [FORM] Checkbox skip #{idx + 1}: {err}")

    print(
        f"  [FORM] Checkbox checked: required={required_checked}, "
        f"required_force={checked_required_force}, optional={checked_optional}"
    )


def _collect_invalid_controls(container, limit: int = 5) -> list[str]:
    try:
        raw_items = container.evaluate(
            """([root, maxCount]) => {
                const items = [];
                const controls = Array.from(root.querySelectorAll("input, textarea, select"));
                for (const el of controls) {
                    if (items.length >= maxCount) break;
                    if (typeof el.checkValidity !== "function") continue;
                    if (el.checkValidity()) continue;
                    const isCheck = el.type === "checkbox" || el.type === "radio";
                    items.push({
                        tag: (el.tagName || "").toLowerCase(),
                        type: (el.getAttribute("type") || "").toLowerCase(),
                        name: el.getAttribute("name") || "",
                        id: el.id || "",
                        placeholder: el.getAttribute("placeholder") || "",
                        value: isCheck ? (el.checked ? "checked" : "unchecked") : String(el.value || "").slice(0, 40),
                        msg: String(el.validationMessage || "").slice(0, 120),
                    });
                }
                return items;
            }""",
            [limit],
        )
    except Exception:
        return []

    if not raw_items:
        return []

    details = []
    for item in raw_items:
        tag = (item.get("tag") or "?").strip()
        typ = (item.get("type") or "").strip()
        name = (item.get("name") or "").strip()
        ident = (item.get("id") or "").strip()
        placeholder = (item.get("placeholder") or "").strip()
        value = (item.get("value") or "").strip()
        msg = (item.get("msg") or "").strip()
        label = f"{tag}:{typ or '-'} name='{name}' id='{ident}' ph='{placeholder}' value='{value}'"
        if msg:
            label += f" msg='{msg}'"
        details.append(label[:260])
    return details


def _stabilize_form_before_retry(page: Page, container, form_type: str) -> str:
    """
    Перед повторным submit усиливаем подготовку формы:
    чекбоксы + нормализация телефона + диагностика невалидных полей.
    """
    notes = []
    try:
        apply_form_checkboxes(page, container, aggressive=True)
    except Exception:
        pass

    cfg = FORM_CONFIGS.get(form_type, {})
    phone_sel = cfg.get("phone")
    if phone_sel:
        phone = container.locator(phone_sel).first
        try:
            if phone.count() > 0 and phone.is_visible():
                current_value = phone.input_value() or ""
                current_digits = "".join(ch for ch in current_value if ch.isdigit())
                must_retype = len(current_digits) < 10 or is_firefox_browser(page)
                if must_retype:
                    delay_ms = browser_timeout(page, PHONE_INPUT_DELAY_MS, FIREFOX_PHONE_INPUT_DELAY_MS)
                    phone.scroll_into_view_if_needed()
                    phone.click(force=True)
                    try:
                        phone.press("Control+A")
                    except Exception:
                        pass
                    try:
                        phone.fill("")
                    except Exception:
                        pass
                    phone.press_sequentially(PHONE_RETRY_VALUE, delay=delay_ms)
                    page.wait_for_timeout(browser_timeout(page, 200, 350))
                    try:
                        page.keyboard.press("Tab")
                    except Exception:
                        pass
                    new_digits = "".join(ch for ch in (phone.input_value() or "") if ch.isdigit())
                    notes.append(f"phone_retyped digits={len(current_digits)}->{len(new_digits)}")
        except Exception as e:
            notes.append(f"phone_retype_error={str(e).replace(chr(10), ' ')[:120]}")

    invalid_controls = _collect_invalid_controls(container, limit=5)
    if invalid_controls:
        notes.append("invalid=" + " || ".join(invalid_controls))

    return " | ".join(notes)[:700]


# ---------------------------------------------------------------------------
# Заполнение формы
# ---------------------------------------------------------------------------

def fill_form(page: Page, container, form_type: str,
              has_name_field: bool = False,
              service_place_value: str | None = None) -> bool:
    cfg        = FORM_CONFIGS[form_type]
    no_house   = cfg.get("no_house", False)
    no_suggest = cfg.get("no_suggest", False)
    street_local = container.locator(cfg["street"]).first
    if service_place_value:
        if not select_service_place_value(container, service_place_value):
            return False

    def fill_street_and_pick() -> bool:
        street_value = _street_value_for_url(page)
        if street_local.count() == 0 or not street_local.is_visible():
            print(f"  [FORM] Address field not found ({cfg['street']})")
            return False

        street_local.scroll_into_view_if_needed()
        street_local.click(force=True)
        try:
            street_local.fill("")
        except Exception:
            pass
        street_local.fill(street_value)

        if no_suggest:
            print("  [FORM] Address entered (no suggestion)")
            return True

        print(f"  [FORM] Street '{street_value}' entered, waiting suggestion...")
        suggest_timeout = browser_timeout(page, SUGGEST_TIMEOUT_MS, FIREFOX_SUGGEST_TIMEOUT_MS)
        choose_first_suggestion(page, timeout_ms=suggest_timeout, field=street_local)
        if _is_beeline_runtime_url(page.url or "") and form_type == "checkaddress":
            house_sel = cfg.get("house")
            if house_sel:
                house_probe = container.locator(house_sel).first
                try:
                    expect(house_probe).to_be_enabled(
                        timeout=browser_timeout(page, 1200, 1800)
                    )
                except Exception:
                    print("  [FORM] Beeline checkaddress: street selection did not unlock house, retrying commit")
                    try:
                        street_local.scroll_into_view_if_needed()
                        street_local.click(force=True)
                        page.wait_for_timeout(120)
                        page.keyboard.press("ArrowDown")
                        page.wait_for_timeout(120)
                        page.keyboard.press("Enter")
                        page.wait_for_timeout(250)
                    except Exception:
                        pass
        return True

    def refill_house_value(house_field, house_value: str) -> str:
        house_field.scroll_into_view_if_needed()
        house_field.click(force=True)

        # Некоторые формы не очищают input обычным fill(""),
        # поэтому очищаем более агрессивно перед каждой попыткой.
        for _ in range(2):
            try:
                house_field.press("Control+A")
                house_field.press("Backspace")
            except Exception:
                pass
            try:
                house_field.fill("")
            except Exception:
                pass
            page.wait_for_timeout(80)
            try:
                current = (house_field.input_value() or "").strip()
            except Exception:
                current = ""
            if not current:
                break

        try:
            house_field.press_sequentially(house_value, delay=35)
        except Exception:
            house_field.fill(house_value)

        page.wait_for_timeout(120)
        try:
            return (house_field.input_value() or "").strip()
        except Exception:
            return ""

    def try_mobile_house_tap_and_fill(house_field) -> bool:
        if not is_mobile_execution_profile():
            return False

        execution_profile = get_execution_profile_name()

        # Baseline mobile fallback is kept for checkaddress.
        # For mobile-webkit pilot we also allow the same tap/input fallback
        # in connection forms (observed flake: house stays disabled in city popup).
        allow_mobile_house_fallback = form_type == "checkaddress" or (
            execution_profile == "mobile-webkit" and form_type == "connection"
        )
        if not allow_mobile_house_fallback:
            return False
        print(
            "  [FORM] House activation fallback: tap/input "
            f"(profile={execution_profile}, form={form_type})"
        )

        try:
            house_field.scroll_into_view_if_needed()
            house_field.click(force=True)
            page.wait_for_timeout(120)

            try:
                box = house_field.bounding_box()
                if box:
                    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    page.wait_for_timeout(120)
            except Exception:
                pass

            try:
                house_field.fill("1")
            except Exception:
                try:
                    house_field.press_sequentially("1", delay=20)
                except Exception:
                    try:
                        page.keyboard.type("1", delay=20)
                    except Exception:
                        pass

            try:
                current_house = (house_field.input_value() or "").strip()
            except Exception:
                current_house = ""

            if current_house:
                print("  [FORM] Mobile fallback: house entered via tap/input")
                return True
        except Exception as e:
            print(f"  [FORM] Mobile fallback for house failed: {e}")

        return False

    # Address / Street
    if not fill_street_and_pick():
        return False

    # House
    if no_house:
        print("  [FORM] House field skipped")
    else:
        house_sel = cfg.get("house")
        if house_sel:
            house_ready = False

            for house_attempt in range(1, 3):
                house = container.locator(house_sel).first
                if house.count() == 0 or not house.is_visible():
                    print(f"  [FORM] House field not found/visible ({house_sel}) | attempt {house_attempt}/2")
                else:
                    print(f"  [FORM] Waiting house field enable... attempt {house_attempt}/2")
                    try:
                        house_enable_timeout = browser_timeout(
                            page, HOUSE_ENABLE_TIMEOUT_MS, FIREFOX_HOUSE_ENABLE_TIMEOUT_MS
                        )
                        if _is_beeline_runtime_url(page.url or "") and form_type == "checkaddress":
                            try:
                                expect(house).to_be_enabled(timeout=house_enable_timeout)
                            except Exception:
                                print("  [FORM] Beeline checkaddress: house stayed disabled, retrying street commit")
                                try:
                                    street_local.scroll_into_view_if_needed()
                                    street_local.click(force=True)
                                    page.wait_for_timeout(120)
                                    page.keyboard.press("ArrowDown")
                                    page.wait_for_timeout(120)
                                    page.keyboard.press("Enter")
                                    page.wait_for_timeout(250)
                                except Exception:
                                    pass
                                expect(
                                    house,
                                ).to_be_enabled(timeout=browser_timeout(page, 2500, 4000))
                        else:
                            expect(house).to_be_enabled(timeout=house_enable_timeout)
                        suggest_timeout = browser_timeout(
                            page, SUGGEST_TIMEOUT_MS, FIREFOX_SUGGEST_TIMEOUT_MS
                        )
                        suggest_timeout = _house_suggest_timeout_ms(page, suggest_timeout)

                        if _use_soft_house_retry(page, form_type):
                            print(
                                f"  [FORM] Soft house retry enabled for URL: "
                                f"{_normalize_runtime_url(page.url or '')}"
                            )
                            suggest_picked = False
                            retry_values = _soft_house_retry_values(page)
                            for house_value in retry_values:
                                entered_house = refill_house_value(house, house_value)
                                print(
                                    f"  [FORM] House target='{house_value}', actual='{entered_house}', "
                                    "waiting visible suggestion..."
                                )
                                suggest_picked = choose_first_suggestion(
                                    page,
                                    timeout_ms=suggest_timeout,
                                    field=house,
                                    allow_keyboard_fallback=False,
                                )
                                if suggest_picked:
                                    print(f"  [FORM] House suggestion selected with value '{house_value}'")
                                    break
                            if not suggest_picked:
                                tried_values = "/".join(retry_values)
                                print(
                                    f"  [FORM] No visible house suggestion for {tried_values} -> keyboard fallback"
                                )
                                choose_first_suggestion(
                                    page,
                                    timeout_ms=suggest_timeout,
                                    field=house,
                                    allow_keyboard_fallback=True,
                                )
                        else:
                            house.scroll_into_view_if_needed()
                            house.click(force=True)
                            house.fill("1")
                            print("  [FORM] House entered, waiting suggestion...")
                            house_suggest_picked = choose_first_suggestion(
                                page,
                                timeout_ms=suggest_timeout,
                                field=house,
                                allow_keyboard_fallback=False,
                            )
                            if not house_suggest_picked:
                                print("  [FORM] House suggestion not visible yet, waiting extra...")
                                house_suggest_picked = choose_first_suggestion(
                                    page,
                                    timeout_ms=suggest_timeout,
                                    field=house,
                                    allow_keyboard_fallback=False,
                                )
                            if not house_suggest_picked:
                                print("  [FORM] House suggestion still missing -> keyboard fallback")
                                choose_first_suggestion(
                                    page,
                                    timeout_ms=suggest_timeout,
                                    field=house,
                                    allow_keyboard_fallback=True,
                                )

                        house_ready = True
                        break
                    except Exception as e:
                        print(f"  [FORM] House field did not activate: {e}")
                        if try_mobile_house_tap_and_fill(house):
                            house_ready = True
                            break

                if house_attempt == 1:
                    print("  [FORM] Retry with full refill...")
                    if not fill_street_and_pick():
                        print("  [FORM] Retry failed: address could not be refilled")
                        return False

            if not house_ready:
                print("  [FORM] House field did not activate after retry; mark form as not filled")
                return False

    # Имя (только для RTK-сайтов, has_name_field=True)
    if has_name_field:
        # Поле Имя — ищем по placeholder или name атрибуту
        name_inp = None
        for sel in ['input[name="Name"]', 'input[name="name"]',
                    'input[placeholder*="мя"]', 'input[placeholder*="ame"]']:
            candidate = container.locator(sel).first
            try:
                if candidate.count() > 0 and candidate.is_visible():
                    name_inp = candidate
                    break
            except Exception:
                pass
        if name_inp is not None:
            name_inp.scroll_into_view_if_needed()
            name_inp.click(force=True)
            name_inp.fill("Тестер")
            print("  [FORM] Имя введено: Тестер")
        else:
            print("  [FORM] ⚠️  Поле Имя не найдено (has_name_field=True)")

    # Телефон (обязательное)
    phone = container.locator(cfg["phone"]).first
    if phone.count() == 0 or not phone.is_visible():
        print(f"  [FORM] ❌ Телефон не найден ({cfg['phone']})")
        return False

    phone.scroll_into_view_if_needed()
    phone.click(force=True)
    phone_delay = browser_timeout(page, PHONE_INPUT_DELAY_MS, FIREFOX_PHONE_INPUT_DELAY_MS)
    phone.press_sequentially(PHONE_TEST_VALUE, delay=phone_delay)
    if _is_beeline_runtime_url(page.url or ""):
        # Некоторые Beeline-CF7 маски валидируют номер только после blur / короткой паузы.
        # Это ближе к ручному сценарию и снижает ложные validation_failed на submit.
        try:
            page.wait_for_timeout(browser_timeout(page, 250, 400))
        except Exception:
            pass
        try:
            phone.blur()
        except Exception:
            try:
                page.keyboard.press("Tab")
            except Exception:
                pass
    try:
        phone_digits = "".join(ch for ch in (phone.input_value() or "") if ch.isdigit())
        print(f"  [FORM] Телефон введён ({len(phone_digits)} digits)")
    except Exception:
        print("  [FORM] Телефон введён")

    apply_form_checkboxes(page, container)

    return True


def find_submit(container, form_type: str):
    cfg    = FORM_CONFIGS[form_type]
    submit_selectors = [cfg["submit"]]

    for submit_selector in submit_selectors:
        submit = container.locator(submit_selector).first
        try:
            if submit.count() > 0 and submit.is_visible() and submit.is_enabled():
                print(f"  [SUBMIT] Найдена '{submit_selector}'")
                return submit
        except Exception:
            pass

    print(f"  [SUBMIT] ❌ Не найдена '{' | '.join(submit_selectors)}'")
    return None


def submit_with_confirmation(
    page: Page,
    container,
    form_type: str,
    timeout_ms: int = SUBMIT_CONFIRM_TIMEOUT_MS,
    attempts: int = 2,
) -> bool:
    """
    Пытается отправить форму и дождаться подтверждения.
    Делает повторную попытку submit при редких флаках no_confirmation.
    """
    last_submit = find_submit(container, form_type)
    if last_submit is None:
        return False

    cf7_seen_statuses: list[str] = []

    def _cf7_response_listener(response):
        try:
            if not _is_cf7_feedback_url(response.url):
                return
            status = _extract_cf7_feedback_status(response)
            if status:
                cf7_seen_statuses.append(status)
        except Exception:
            pass

    listener_attached = False
    try:
        try:
            page.on("response", _cf7_response_listener)
            listener_attached = True
        except Exception:
            listener_attached = False

        for attempt in range(1, attempts + 1):
            cf7_status = ""
            network_before = _snapshot_submit_network(page)
            try:
                last_submit.scroll_into_view_if_needed()
                last_submit.click(force=True)
            except Exception:
                # Форма могла перерендериться — пробуем найти submit снова
                last_submit = find_submit(container, form_type)
                if last_submit is None:
                    return False
                last_submit.scroll_into_view_if_needed()
                last_submit.click(force=True)

            cf7_timeout = browser_timeout(page, 1_200, 2_500)
            cf7_status = wait_for_cf7_feedback_status(page, timeout_ms=cf7_timeout)
            if not cf7_status and cf7_seen_statuses:
                cf7_status = cf7_seen_statuses[-1]
                print(f"  [SUBMIT] CF7 feedback status='{cf7_status}' (listener)")
            elif cf7_status:
                print(f"  [SUBMIT] CF7 feedback status='{cf7_status}'")

            if is_firefox_browser(page):
                page.wait_for_timeout(900)
                network_probe = _snapshot_submit_network(page)
                new_probe_requests = sorted(network_probe - network_before)
                if new_probe_requests and not _has_non_tracking_requests(new_probe_requests):
                    native_triggered = _trigger_native_form_submit(container)
                    if native_triggered:
                        print("  [SUBMIT] Firefox fallback: requestSubmit()/native click")
                        page.wait_for_timeout(700)
                        network_before = _snapshot_submit_network(page)
                        cf7_status = wait_for_cf7_feedback_status(page, timeout_ms=2_000) or cf7_status

            ok = wait_for_success_url(page, timeout_ms=timeout_ms)
            if ok:
                return True
            if cf7_status == "mail_sent":
                print("  [SUBMIT] ✅ Подтверждено по CF7 mail_sent (без redirect)")
                return True

            network_after = _snapshot_submit_network(page)
            new_requests = sorted(network_after - network_before)
            if new_requests:
                preview = " | ".join(_compact_request_url(item) for item in new_requests[:3])
                print(f"  [SUBMIT] New XHR/fetch after submit: {preview}")
            else:
                print("  [SUBMIT] New XHR/fetch after submit: none")

            if attempt < attempts:
                print(f"  [SUBMIT] Повторная попытка {attempt + 1}/{attempts}")
                try:
                    print("  [SUBMIT] Стабилизация формы перед retry")
                    retry_notes = _stabilize_form_before_retry(page, container, form_type)
                    if retry_notes:
                        print(f"  [SUBMIT] Retry diagnostics: {retry_notes}")
                except Exception:
                    pass
                page.wait_for_timeout(1200)
    finally:
        if listener_attached:
            try:
                page.remove_listener("response", _cf7_response_listener)
            except Exception:
                try:
                    page.off("response", _cf7_response_listener)
                except Exception:
                    pass

    return False


# ---------------------------------------------------------------------------
# Ожидание попапа
# ---------------------------------------------------------------------------

def wait_for_popup_with_fields(page: Page, timeout_ms: int = 10_000,
                                form_hint=None):
    form_types_to_check = (
        [(form_hint, FORM_CONFIGS[form_hint])]
        if form_hint and form_hint in FORM_CONFIGS
        else list(FORM_CONFIGS.items())
    )
    poll_ms = 300
    elapsed = 0

    while elapsed < timeout_ms:
        for popup_sel in POPUP_CONTAINER_SELECTORS:
            for form_type, cfg in form_types_to_check:
                containers = page.locator(popup_sel)
                for i in range(containers.count()):
                    container = containers.nth(i)
                    try:
                        if not container.is_visible(timeout=300):
                            continue
                        phone = container.locator(cfg["phone"]).first
                        if phone.count() > 0 and phone.is_visible(timeout=300):
                            print(f"  [POPUP] sel='{popup_sel}' type='{form_type}'")
                            return form_type, container
                    except Exception:
                        pass

        for form_type, cfg in form_types_to_check:
            phone_fields = page.locator(cfg["phone"])
            for i in range(phone_fields.count()):
                phone = phone_fields.nth(i)
                try:
                    if not phone.is_visible(timeout=300):
                        continue
                    parent = phone.locator(
                        "xpath=ancestor::div[contains(@class,'popup') or "
                        "contains(@class,'modal') or contains(@id,'popup')]"
                    ).last
                    if parent.count() > 0 and parent.is_visible(timeout=300):
                        print(f"  [POPUP] ancestor type='{form_type}'")
                        return form_type, parent
                    form_parent = phone.locator("xpath=ancestor::form").last
                    if form_parent.count() > 0 and form_parent.is_visible(timeout=300):
                        print(f"  [POPUP] form-ancestor type='{form_type}'")
                        return form_type, form_parent
                except Exception:
                    pass

        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms

    print(f"  [POPUP] ❌ Попап не появился за {timeout_ms // 1000}с")
    return None, None


# ---------------------------------------------------------------------------
# Сбор кнопок
# ---------------------------------------------------------------------------

def find_visible_form_container_by_phone(page: Page, cfg: dict):
    """
    Fallback: некоторые шаблоны раскрывают форму не как popup-контейнер.
    Ищем любой видимый phone-field формы и поднимаемся к ближайшему form/section/div.
    """
    try:
        phone_fields = page.locator(cfg["phone"])
        for i in range(phone_fields.count()):
            phone = phone_fields.nth(i)
            try:
                if not phone.is_visible():
                    continue
                for xpath in ("ancestor::form", "ancestor::section", "ancestor::div"):
                    parent = phone.locator(f"xpath={xpath}").last
                    if parent.count() > 0 and parent.is_visible():
                        return parent
            except Exception:
                continue
    except Exception:
        pass
    return None


def resolve_checkaddress_container_after_click(page: Page, timeout_ms: int = 12_000):
    detected_form, popup_container = wait_for_popup_with_fields(
        page,
        timeout_ms=timeout_ms,
        form_hint="checkaddress",
    )
    if detected_form == "checkaddress" and popup_container is not None:
        return detected_form, popup_container

    cfg = FORM_CONFIGS["checkaddress"]
    poll_ms = 250
    elapsed = 0
    while elapsed < 3_500:
        container = find_visible_form_container_by_phone(page, cfg)
        if container is not None:
            print("  [CHECKADDRESS] fallback: detected visible form container by phone field")
            return "checkaddress", container
        page.wait_for_timeout(poll_ms)
        elapsed += poll_ms
    return detected_form, popup_container


def collect_popup_buttons(
    page: Page,
    *,
    allowed_form_hints: set[str] | None = None,
    include_generic_buttons: bool = True,
    dedupe_css_by_text: bool = True,
) -> list:
    """
    Сбор триггеров попапов.
    По умолчанию: generic-кнопки + кнопки по CSS-классам.
    Для form-suite режима можно ограничить набор form_hint и отключить generic.
    """
    all_btns = page.locator("button")
    total    = all_btns.count()
    result   = []
    seen_idx = set()
    text_counters = {}

    print(f"\n[COLLECT] Кнопок на странице: {total}")

    # По ключевым словам (connection и др.)
    if include_generic_buttons:
        for i in range(total):
            btn = all_btns.nth(i)
            try:
                if not btn.is_visible() or not btn.is_enabled():
                    continue
                text = (btn.inner_text() or "").strip().lower()
                if not any(kw in text for kw in POPUP_OPEN_KEYWORDS):
                    continue
                if any(kw in text for kw in POPUP_SKIP_KEYWORDS):
                    continue
                if (
                    _is_mts_internet_runtime_url(page.url)
                    and (
                        MTS_INTERNET_SKIP_BUTTON_TEXT in text
                        or any(keyword in text for keyword in MTS_INTERNET_SKIP_BUTTON_KEYWORDS)
                    )
                ):
                    print(f"  [COLLECT] SKIP MTS internet FAQ button '{text}'")
                    continue
                text_key = ("generic", text)
                current_count = text_counters.get(text_key, 0)
                if current_count >= POPUP_MAX_BUTTONS_PER_TEXT:
                    print(
                        f"  [COLLECT] SKIP duplicate text '{text}' "
                        f"(limit={POPUP_MAX_BUTTONS_PER_TEXT})"
                    )
                    continue
                seen_idx.add(i)
                result.append(
                    {
                        "index": i,
                        "text": text,
                        "form_hint": None,
                        "css": None,
                        "trigger_kind": "generic",
                    }
                )
                text_counters[text_key] = current_count + 1
                print(f"  [COLLECT] #{len(result)} index={i} '{text}'")
            except Exception:
                pass

    # По CSS-классам (profit, express-connection)
    for form_hint, css_class in POPUP_BUTTON_CLASSES.items():
        if form_hint == "business":
            continue   # бизнес собирается отдельно
        if allowed_form_hints is not None:
            effective_hint_for_filter = "connection" if form_hint == "connection_card" else form_hint
            if effective_hint_for_filter not in allowed_form_hints:
                continue
        btns = page.locator(css_class)
        effective_form_hint = "connection" if form_hint == "connection_card" else form_hint
        trigger_kind = "connection_card" if form_hint == "connection_card" else form_hint
        for i in range(btns.count()):
            btn = btns.nth(i)
            try:
                if not btn.is_visible() or not btn.is_enabled():
                    continue
                global_idx = btn.evaluate(
                    "el => Array.from(document.querySelectorAll('button')).indexOf(el)"
                )
                if isinstance(global_idx, int) and global_idx >= 0 and global_idx in seen_idx:
                    continue
                text = (btn.inner_text() or "").strip().lower()
                if dedupe_css_by_text:
                    text_key = (effective_form_hint, text)
                    current_count = text_counters.get(text_key, 0)
                    if current_count >= POPUP_MAX_BUTTONS_PER_TEXT:
                        print(
                            f"  [COLLECT] SKIP duplicate text '{text}' ({effective_form_hint}) "
                            f"(limit={POPUP_MAX_BUTTONS_PER_TEXT})"
                        )
                        continue
                    text_counters[text_key] = current_count + 1
                if isinstance(global_idx, int) and global_idx >= 0:
                    seen_idx.add(global_idx)
                result.append(
                    {
                        "index": global_idx,
                        "text": text,
                        "form_hint": effective_form_hint,
                        "css": css_class,
                        "trigger_kind": trigger_kind,
                    }
                )
                print(f"  [COLLECT] #{len(result)} index={global_idx} "
                      f"'{text}' ({effective_form_hint})")
            except Exception:
                pass

    print(f"[COLLECT] Итого: {len(result)}\n")
    return result


def dismiss_profit_popup(page: Page):
    """
    Закрывает автоматически всплывший попап 'Выгодное спецпредложение'
    если он появился сам (мешает другим шагам).
    Не заполняет форму — просто закрывает. Безопасно вызывать в любой момент.
    """
    try:
        phone = page.locator(FORM_CONFIGS["profit"]["phone"]).first
        if phone.count() == 0 or not phone.is_visible():
            return
        for close_sel in [
            ".popup__close", ".fancybox-close-small", ".modal__close",
            "[aria-label*='close']", "[aria-label*='закры']",
        ]:
            btn = page.locator(close_sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(force=True)
                page.wait_for_timeout(300)
                print("  [PROFIT] Автоматический profit-попап закрыт")
                return
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        print("  [PROFIT] Profit-попап закрыт (Escape)")
    except Exception:
        pass


def process_auto_profit_popup(
    page: Page,
    base_url: str,
    has_name_field: bool = False,
    service_mode: str = SERVICE_MODE_ALL,
    allow_root_return_after_thanks: bool = False,
) -> tuple[int, int, str | None, bool]:
    """
    Проверяет автопоявляющийся profit-попап как полноценную форму:
    fill -> submit -> confirm.

    Возвращает:
      success, failed, first_fail, auto_popup_tested
    """
    site_label = base_url.replace("https://", "").replace("http://", "").strip("/")
    sep = "=" * 55
    print(f"\n{sep}\n[AUTO-PROFIT] Проверка автопопапа\n{sep}")

    nav_ok, nav_critical, nav_reason = safe_goto(page, base_url)
    if not nav_ok:
        if nav_critical:
            raise SiteUnavailableError(
                f"AUTO-PROFIT: сайт недоступен ({base_url}) | {nav_reason}"
            )
        log_error("navigation_failed", page, site_label, extra=nav_reason[:180])
        first_fail = f"AUTO-PROFIT code=navigation_failed | {nav_reason[:180]}"
        return 0, 1, first_fail[:220], False

    # Для корректного ожидания авто-попапа закрываем только region/cookie.
    dismiss_region_popup(page)
    accept_cookie_banner(page)
    close_mobile_burger_menu(page)

    form_type, container = wait_for_popup_with_fields(
        timeout_ms=browser_timeout(page, 12_000, 16_000),
        page=page,
        form_hint="profit",
    )
    if form_type is None:
        print("  [AUTO-PROFIT] Автопопап не появился — продолжаем обычный цикл")
        allure.attach(
            "Автопопап profit не появился за 12с. Сценарий пропущен как неприменимый.",
            name=f"AUTO-PROFIT skip ({site_label})",
            attachment_type=allure.attachment_type.TEXT,
        )
        return 0, 0, None, False

    print("  [AUTO-PROFIT] Попап появился автоматически, запускаем полный submit-сценарий")
    if not fill_form(page, container, form_type, has_name_field=has_name_field):
        log_error("form_not_filled", page, site_label, extra="auto profit popup")
        return 0, 1, "AUTO-PROFIT code=form_not_filled"[:220], True

    submit = find_submit(container, form_type)
    if submit is None:
        log_error("submit_not_found", page, site_label, extra="auto profit popup")
        return 0, 1, "AUTO-PROFIT code=submit_not_found"[:220], True

    if REALLY_SUBMIT:
        return_url_before_submit = page.url or base_url
        ok = submit_with_confirmation(
            page,
            container,
            form_type,
            timeout_ms=SUBMIT_CONFIRM_TIMEOUT_MS,
            attempts=2,
        )
        if ok:
            print("  [AUTO-PROFIT] ✅ Заявка принята")
            thanks_ok, thanks_reason = verify_thanks_close_and_return(
                page,
                return_url_before_submit,
                allow_root_return=allow_root_return_after_thanks,
            )
            if not thanks_ok:
                print(
                    "  [AUTO-PROFIT] ⚠️ Submit подтверждён, "
                    f"но возврат после Thanks не завершён: {thanks_reason}"
                )
                return 1, 0, None, True
            return 1, 0, None, True

        log_error("no_confirmation", page, site_label, extra="auto profit popup")
        return 0, 1, "AUTO-PROFIT code=no_confirmation"[:220], True

    print("  [AUTO-PROFIT] ✅ Форма готова (REALLY_SUBMIT=False)")
    close_popup_or_page(page)
    return 1, 0, None, True


def process_unexpected_auto_profit_popup(
    page: Page,
    base_url: str,
    has_name_field: bool = False,
    context: str = "",
    allow_root_return_after_thanks: bool = False,
) -> tuple[bool, bool, str]:
    """
    Подстраховка: если auto-profit всплыл во время проверки другой формы,
    закрываем его и возвращаемся к исходному сценарию (без submit).

    Возвращает:
      handled, ok, fail_code
    """
    site_label = base_url.replace("https://", "").replace("http://", "").strip("/")
    form_type, container = wait_for_popup_with_fields(
        page=page,
        timeout_ms=browser_timeout(page, 2_000, 3_500),
        form_hint="profit",
    )
    if form_type is None:
        return False, True, ""

    print(f"  [AUTO-PROFIT] Неожиданное появление во время '{context}' — закрываем без submit")
    dismiss_profit_popup(page)
    return True, True, ""


def _run_popup_cycle(page: Page, buttons: list, base_url: str,
                     btn_locator_fn, label: str = "POPUP",
                     has_name_field: bool = False,
                     service_mode: str = SERVICE_MODE_ALL,
                     allow_root_return_after_thanks: bool = False,
                     expected_form_types: set[str] | None = None,
                     stop_after_first_expected_form: bool = False) -> tuple[int, int, str | None, set[str], set[str]]:
    success    = 0
    failed     = 0
    first_fail = None
    fail_details = []
    tested_form_types: set[str] = set()
    successful_form_types: set[str] = set()
    tested_trigger_kinds: set[str] = set()
    stop_after_mts_internet_form_failure = False
    site_label = base_url.replace("https://", "").replace("http://", "").strip("/")
    no_confirmation_by_text = {}

    for num, entry in enumerate(buttons, 1):
        if stop_after_mts_internet_form_failure:
            print(
                f"  [{label}] Остановка цикла: mts-internet уже получил "
                "ошибку заполнения формы"
            )
            break
        if (
            stop_after_first_expected_form
            and expected_form_types
            and successful_form_types.intersection(expected_form_types)
        ):
            print(f"  [{label}] Целевая форма уже проверена, останавливаем цикл кнопок")
            break

        text      = entry.get("text", "")
        form_hint = entry.get("form_hint")
        trigger_kind = str(entry.get("trigger_kind") or "generic")
        if (
            expected_form_types
            and form_hint
            and form_hint not in expected_form_types
        ):
            print(f"  [{label}] Пропуск кнопки hint='{form_hint}': не в expected_form_types")
            continue
        text_key = (form_hint or "generic", (text or "").strip().lower())
        if no_confirmation_by_text.get(text_key, 0) >= POPUP_REPEAT_NO_CONFIRMATION_SKIP_THRESHOLD:
            print(
                f"  [{label}] SKIP: повторный no_confirmation для '{text}' "
                f"(threshold={POPUP_REPEAT_NO_CONFIRMATION_SKIP_THRESHOLD})"
            )
            continue
        sep       = "=" * 55
        print(f"\n{sep}\n[{label} {num}/{len(buttons)}] '{text}' hint={form_hint}\n{sep}")

        def register_failure(code: str, details: str = ""):
            nonlocal failed, first_fail, stop_after_mts_internet_form_failure
            failed += 1
            current_url = ""
            try:
                current_url = page.url
            except Exception:
                current_url = "n/a"
            entry_line = (
                f"{label} {num}/{len(buttons)} text='{text}' hint={form_hint} "
                f"code={code} url={current_url}"
            )
            if details:
                entry_line += f" | {details}"
            fail_details.append(entry_line[:600])
            if first_fail is None:
                first_fail = entry_line[:220]
            print(f"  [FAIL-DETAIL] {entry_line}")
            if (
                _is_mts_internet_runtime_url(base_url)
                and not form_hint
                and code == "form_not_filled"
            ):
                stop_after_mts_internet_form_failure = True

        def recover_from_unexpected_profit(current_context: str) -> str:
            # Когда целевая форма сама profit — это не "неожиданное" появление.
            if form_hint == "profit":
                return "none"

            handled, ok, fail_code = process_unexpected_auto_profit_popup(
                page,
                base_url,
                has_name_field=has_name_field,
                context=current_context,
                allow_root_return_after_thanks=allow_root_return_after_thanks,
            )
            if not handled:
                return "none"
            if not ok:
                register_failure(fail_code or "auto_profit_failed", f"context={current_context}")
                return "failed"

            # Возобновляем исходный сценарий: повторно открываем целевую форму.
            try:
                if form_hint == "business":
                    nav_ok_after_profit, nav_critical_after_profit, nav_reason_after_profit = safe_goto(page, base_url)
                    if not nav_ok_after_profit:
                        if nav_critical_after_profit:
                            raise SiteUnavailableError(
                                f"{label}: сайт недоступен после auto-profit ({base_url}) | {nav_reason_after_profit}"
                            )
                        raise RuntimeError(
                            f"не удалось вернуться на {base_url} после auto-profit: {nav_reason_after_profit}"
                        )
                    accept_cookie_banner(page)
                    close_mobile_burger_menu(page)
                retry_btn = btn_locator_fn(page, entry)
                retry_btn.scroll_into_view_if_needed()
                retry_btn.click(force=True)
                page.wait_for_timeout(popup_click_settle_ms(page))
                print(f"  [{label}] Возобновляем проверку после AUTO-PROFIT")
                return "reopened"
            except Exception as e:
                if form_hint == "business":
                    try:
                        fallback_btns = page.locator(POPUP_BUTTON_CLASSES["business"])
                        for idx in range(fallback_btns.count()):
                            candidate = fallback_btns.nth(idx)
                            if candidate.count() > 0 and candidate.is_visible() and candidate.is_enabled():
                                candidate.scroll_into_view_if_needed()
                                candidate.click(force=True)
                                page.wait_for_timeout(popup_click_settle_ms(page))
                                print("  [BUSINESS] Fallback-клик при recover_from_unexpected_profit выполнен")
                                return "reopened"
                    except Exception:
                        pass
                err = str(e).replace("\n", " ")[:180]
                log_error("click_failed", page, site_label, extra=f"reopen after auto-profit | {err}")
                register_failure("click_failed", f"reopen after auto-profit | {err}")
                return "failed"

        def reopen_target_popup(current_context: str):
            nav_ok_local, nav_critical_local, nav_reason_local = safe_goto(page, base_url)
            if not nav_ok_local:
                if nav_critical_local:
                    raise SiteUnavailableError(
                        f"{label}: сайт недоступен при повторном открытии формы ({base_url}) | {nav_reason_local}"
                    )
                log_error("navigation_failed", page, site_label, extra=nav_reason_local[:180])
                register_failure("navigation_failed", f"{current_context} | {nav_reason_local[:180]}")
                return None, None, "failed"

            accept_cookie_banner(page)
            close_mobile_burger_menu(page)
            try:
                retry_btn = btn_locator_fn(page, entry)
                retry_btn.scroll_into_view_if_needed()
                retry_btn.click(force=True)
                page.wait_for_timeout(popup_click_settle_ms(page))
            except Exception as e:
                if form_hint == "business":
                    try:
                        fallback_btns = page.locator(POPUP_BUTTON_CLASSES["business"])
                        clicked = False
                        for idx in range(fallback_btns.count()):
                            candidate = fallback_btns.nth(idx)
                            if candidate.count() > 0 and candidate.is_visible() and candidate.is_enabled():
                                candidate.scroll_into_view_if_needed()
                                candidate.click(force=True)
                                page.wait_for_timeout(popup_click_settle_ms(page))
                                clicked = True
                                print("  [BUSINESS] Fallback-клик после auto-profit выполнен")
                                break
                        if clicked:
                            e = None
                        else:
                            raise RuntimeError("fallback-кнопка business не найдена")
                    except Exception as fb_err:
                        err = str(fb_err).replace("\n", " ")[:180]
                        log_error("click_failed", page, site_label, extra=f"{current_context} | {err}")
                        register_failure("click_failed", f"{current_context} | {err}")
                        return None, None, "failed"
                else:
                    err = str(e).replace("\n", " ")[:180]
                    log_error("click_failed", page, site_label, extra=f"{current_context} | {err}")
                    register_failure("click_failed", f"{current_context} | {err}")
                    return None, None, "failed"

            reopened_form_type, reopened_container = wait_for_popup_with_fields(
                page,
                timeout_ms=popup_wait_timeout_ms(page),
                form_hint=form_hint,
            )
            if reopened_form_type is None:
                recover_status_local = recover_from_unexpected_profit(
                    f"{current_context}: ожидание целевого попапа"
                )
                if recover_status_local == "reopened":
                    reopened_form_type, reopened_container = wait_for_popup_with_fields(
                        page,
                        timeout_ms=popup_wait_timeout_ms(page),
                        form_hint=form_hint,
                    )
                elif recover_status_local == "failed":
                    return None, None, "failed"

            if reopened_form_type is None:
                log_error("popup_not_found", page, site_label, extra=current_context)
                register_failure("popup_not_found", current_context)
                return None, None, "failed"

            return reopened_form_type, reopened_container, "ok"

        nav_ok, nav_critical, nav_reason = safe_goto(page, base_url)
        if not nav_ok:
            if nav_critical:
                raise SiteUnavailableError(
                    f"{label}: сайт недоступен на этапе {num}/{len(buttons)} ({base_url}) | {nav_reason}"
                )
            log_error("navigation_failed", page, site_label, extra=nav_reason[:180])
            register_failure("navigation_failed", nav_reason[:180])
            continue
        accept_cookie_banner(page)
        close_mobile_burger_menu(page)

        try:
            btn = btn_locator_fn(page, entry)
            btn.scroll_into_view_if_needed()
            btn.click(force=True)
            page.wait_for_timeout(popup_click_settle_ms(page))
        except Exception as e:
            log_error("click_failed", page, site_label, extra=str(e)[:150])
            register_failure("click_failed", str(e).replace("\n", " ")[:180])
            continue

        form_type, container = wait_for_popup_with_fields(
            page,
            timeout_ms=popup_wait_timeout_ms(page),
            form_hint=form_hint,
        )
        if form_type is None:
            recover_status = recover_from_unexpected_profit("ожидание целевого попапа")
            if recover_status == "reopened":
                form_type, container = wait_for_popup_with_fields(
                    page,
                    timeout_ms=popup_wait_timeout_ms(page),
                    form_hint=form_hint,
                )
            elif recover_status == "failed":
                continue
        if form_type is None:
            log_error("popup_not_found", page, site_label)
            register_failure("popup_not_found")
            continue

        reported_form_type = form_type
        if expected_form_types and form_type not in expected_form_types:
            print(f"  [{label}] Пропуск формы '{form_type}': не в expected_form_types")
            close_popup_or_page(page)
            continue

        if reported_form_type in successful_form_types:
            print(
                f"  [{label}] Пропуск формы '{reported_form_type}': "
                "тип уже успешно проверен"
            )
            close_popup_or_page(page)
            continue
        tested_form_types.add(reported_form_type)
        detected_service_values = []
        if form_type not in ("profit", "business"):
            detected_service_values = detect_service_place_values(container)

        service_values = resolve_service_values_for_mode(
            form_type=form_type,
            detected_service_values=detected_service_values,
            service_mode=service_mode,
        )
        if not service_values:
            print(f"  [{label}] Пропуск формы: нет применимых вариантов для режима '{service_mode}'")
            continue

        for service_idx, service_value in enumerate(service_values, start=1):
            service_label = service_value if service_value else "без выбора варианта"
            print(
                f"  [{label}] Вариант submit {service_idx}/{len(service_values)}: {service_label}"
            )

            if not fill_form(
                page,
                container,
                form_type,
                has_name_field=has_name_field,
                service_place_value=service_value,
            ):
                recover_status = recover_from_unexpected_profit(
                    f"заполнение целевой формы ({service_label})"
                )
                if recover_status == "reopened":
                    form_type, container = wait_for_popup_with_fields(page, form_hint=form_hint)
                    if form_type is None:
                        log_error("popup_not_found", page, site_label, extra="after auto-profit recovery")
                        register_failure("popup_not_found", f"after auto-profit recovery | service={service_label}")
                        continue
                    if fill_form(
                        page,
                        container,
                        form_type,
                        has_name_field=has_name_field,
                        service_place_value=service_value,
                    ):
                        pass
                    else:
                        log_error("form_not_filled", page, site_label, extra=f"service={service_label}")
                        register_failure("form_not_filled", f"service={service_label}")
                        continue
                elif recover_status == "failed":
                    continue
                else:
                    log_error("form_not_filled", page, site_label, extra=f"service={service_label}")
                    register_failure("form_not_filled", f"service={service_label}")
                    continue

            submit = find_submit(container, form_type)
            if submit is None:
                recover_status = recover_from_unexpected_profit(
                    f"поиск submit в целевой форме ({service_label})"
                )
                if recover_status == "reopened":
                    form_type, container = wait_for_popup_with_fields(page, form_hint=form_hint)
                    if form_type is None:
                        log_error("popup_not_found", page, site_label, extra="after auto-profit recovery")
                        register_failure("popup_not_found", f"after auto-profit recovery | service={service_label}")
                        continue
                    submit = find_submit(container, form_type)
                    if submit is None:
                        log_error("submit_not_found", page, site_label, extra=f"service={service_label}")
                        register_failure("submit_not_found", f"service={service_label}")
                        continue
                elif recover_status == "failed":
                    continue
                else:
                    log_error("submit_not_found", page, site_label, extra=f"service={service_label}")
                    register_failure("submit_not_found", f"service={service_label}")
                    continue

            submit.scroll_into_view_if_needed()

            if REALLY_SUBMIT:
                return_url_before_submit = page.url or base_url
                ok = submit_with_confirmation(
                    page, container, form_type,
                    timeout_ms=SUBMIT_CONFIRM_TIMEOUT_MS, attempts=2
                )
                if ok:
                    print(f"  [{label}] ✅ Заявка принята ({service_label})")
                    tested_trigger_kinds.add(trigger_kind)
                    thanks_ok, thanks_reason = verify_thanks_close_and_return(
                        page,
                        return_url_before_submit,
                        allow_root_return=allow_root_return_after_thanks,
                    )
                    if not thanks_ok:
                        print(
                            f"  [{label}] ⚠️ Submit подтверждён ({service_label}), "
                            f"но возврат после Thanks не завершён: {thanks_reason}"
                        )
                        success += 1
                        successful_form_types.add(reported_form_type)
                        continue
                    success += 1
                    successful_form_types.add(reported_form_type)
                else:
                    log_error("no_confirmation", page, site_label, extra=f"service={service_label}")
                    register_failure("no_confirmation", f"service={service_label}")
                    no_confirmation_by_text[text_key] = no_confirmation_by_text.get(text_key, 0) + 1
                    continue
            else:
                print(f"  [{label}] ✅ Форма готова (REALLY_SUBMIT=False, {service_label})")
                tested_trigger_kinds.add(trigger_kind)
                close_popup_or_page(page)
                success += 1
                successful_form_types.add(reported_form_type)

            if service_idx < len(service_values):
                form_type, container, reopen_status = reopen_target_popup(
                    f"переоткрытие формы для варианта услуги ({service_label})"
                )
                if reopen_status != "ok":
                    break

    if fail_details:
        allure.attach(
            "\n".join(fail_details),
            name=f"{label} failure details ({site_label})",
            attachment_type=allure.attachment_type.TEXT,
        )

    sep = "=" * 55
    total_attempts = success + failed
    print(
        f"\n{sep}\n[{label} RESULT] ✅ {success}  ❌ {failed}  "
        f"Submit-попыток: {total_attempts}\n{sep}\n"
    )
    return success, failed, first_fail, tested_form_types, tested_trigger_kinds


def process_all_popups(page: Page, base_url: str,
                        has_name_field: bool = False,
                        service_mode: str = SERVICE_MODE_ALL,
                        allow_root_return_after_thanks: bool = False,
                        expected_form_types: set[str] | None = None,
                        expect_connection_cards: bool = False) -> tuple[int, int, str | None, set[str], set[str]]:
    target_form_mode = bool(expected_form_types) and len(expected_form_types) == 1
    if target_form_mode:
        target_text = ", ".join(sorted(expected_form_types or set()))
        print(f"[POPUP] Target form mode: {target_text}")

    should_check_auto_profit = expected_form_types is None or "profit" in expected_form_types
    if should_check_auto_profit:
        auto_success, auto_failed, auto_first_fail, _auto_tested = process_auto_profit_popup(
            page,
            base_url,
            has_name_field=has_name_field,
            service_mode=service_mode,
            allow_root_return_after_thanks=allow_root_return_after_thanks,
        )
    else:
        auto_success, auto_failed, auto_first_fail, _auto_tested = 0, 0, None, False
        print("[AUTO-PROFIT] Пропуск: profit не входит в expected_form_types")

    pretested_form_types: set[str] = set()
    pretested_trigger_kinds: set[str] = set()
    if _auto_tested:
        pretested_form_types.add("profit")
        pretested_trigger_kinds.add("auto_profit")

    # Если в form-suite режиме целевая форма — только profit, и auto-profit уже
    # успешно отработал, считаем цель выполненной и не тратим время на доп.клики.
    if (
        target_form_mode
        and expected_form_types == {"profit"}
        and auto_success > 0
        and auto_failed == 0
    ):
        print("[POPUP] AUTO-PROFIT успешно проверен, цикл кнопок пропущен")
        return auto_success, auto_failed, auto_first_fail, pretested_form_types, pretested_trigger_kinds

    # После auto-profit возвращаемся на базовый URL, чтобы сбор кнопок шёл
    # с основной страницы, даже если auto-submit привёл на /thanks.
    nav_ok, nav_critical, nav_reason = safe_goto(page, base_url)
    if not nav_ok:
        site_label = base_url.replace("https://", "").replace("http://", "").strip("/")
        if nav_critical:
            raise SiteUnavailableError(
                f"POPUP: сайт недоступен после AUTO-PROFIT ({base_url}) | {nav_reason}"
            )
        log_error("navigation_failed", page, site_label, extra=f"after auto-profit | {nav_reason[:180]}")

    buttons = collect_popup_buttons(
        page,
        allowed_form_hints=expected_form_types if target_form_mode else None,
        include_generic_buttons=not target_form_mode,
        dedupe_css_by_text=not target_form_mode,
    )
    if target_form_mode and not buttons:
        print("[POPUP] CSS-триггеры целевой формы не найдены, fallback на generic-кнопки")
        buttons = collect_popup_buttons(
            page,
            allowed_form_hints=expected_form_types,
            include_generic_buttons=True,
            dedupe_css_by_text=False,
        )
    if auto_success > 0 and buttons:
        before = len(buttons)
        buttons = [b for b in buttons if b.get("form_hint") != "profit"]
        removed = before - len(buttons)
        if removed > 0:
            print(f"[POPUP] AUTO-PROFIT уже проверен, исключено profit-кнопок: {removed}")

    if not buttons:
        print("[POPUP] Кнопки не найдены — пропускаем")
        return auto_success, auto_failed, auto_first_fail, pretested_form_types, pretested_trigger_kinds

    if expect_connection_cards:
        card_buttons = [b for b in buttons if b.get("trigger_kind") == "connection_card"]
        other_buttons = [b for b in buttons if b.get("trigger_kind") != "connection_card"]
        if card_buttons:
            buttons = card_buttons + other_buttons
            print(f"[POPUP] Приоритет card-триггеров: {len(card_buttons)}")

    def locate(page, entry):
        index = entry.get("index")
        if isinstance(index, int) and index >= 0:
            try:
                btn = page.locator("button").nth(index)
                if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                    return btn
            except Exception:
                pass

        css = entry.get("css")
        if css:
            try:
                css_btns = page.locator(css)
                for i in range(css_btns.count()):
                    candidate = css_btns.nth(i)
                    if candidate.count() > 0 and candidate.is_visible() and candidate.is_enabled():
                        return candidate
            except Exception:
                pass

        text = (entry.get("text") or "").strip()
        if text:
            return page.locator("button").filter(has_text=text).first
        return page.locator("button").first

    success, failed, first_fail, tested_types, tested_trigger_kinds = _run_popup_cycle(
        page, buttons, base_url, locate, label="POPUP",
        has_name_field=has_name_field,
        service_mode=service_mode,
        allow_root_return_after_thanks=allow_root_return_after_thanks,
        expected_form_types=expected_form_types,
        stop_after_first_expected_form=target_form_mode,
    )
    total_success = auto_success + success
    total_failed = auto_failed + failed
    total_first_fail = auto_first_fail if auto_first_fail else first_fail
    tested_types |= pretested_form_types
    tested_trigger_kinds |= pretested_trigger_kinds
    return total_success, total_failed, total_first_fail, tested_types, tested_trigger_kinds


def process_inline_connection_form(
    page: Page,
    base_url: str,
    *,
    has_name_field: bool = False,
    allow_root_return_after_thanks: bool = False,
) -> tuple[int, int, str | None, set[str]]:
    """
    Fallback для страниц, где connection-форма уже открыта в теле страницы
    (без popup-триггера), например rtk-home.ru/.../podklyuchenie-interneta.
    """
    print("\n[INLINE-CONNECTION] Проверка inline-формы connection")
    cfg = FORM_CONFIGS["connection"]
    container = page.locator("section, form, div").filter(
        has=page.locator(cfg["phone"])
    ).first

    try:
        if container.count() == 0:
            print("  [INLINE-CONNECTION] Форма не найдена")
            return 0, 0, None, set()
    except Exception:
        print("  [INLINE-CONNECTION] Ошибка поиска формы")
        return 0, 0, None, set()

    filled = fill_form(page, container, "connection", has_name_field=has_name_field)
    if not filled:
        reason = "inline connection не заполнена (street/house/phone)"
        print(f"  [INLINE-CONNECTION] ❌ {reason}")
        return 0, 1, reason, {"connection"}

    submit = find_submit(container, "connection")
    if not submit:
        reason = "кнопка отправки inline connection не найдена"
        print(f"  [INLINE-CONNECTION] ❌ {reason}")
        return 0, 1, reason, {"connection"}

    if REALLY_SUBMIT:
        return_url_before_submit = page.url or base_url
        ok = submit_with_confirmation(
            page, container, "connection",
            timeout_ms=SUBMIT_CONFIRM_TIMEOUT_MS, attempts=2
        )
        if not ok:
            reason = "подтверждение отправки inline connection не получено"
            print(f"  [INLINE-CONNECTION] ❌ {reason}")
            return 0, 1, reason, {"connection"}

        thanks_ok, thanks_reason = verify_thanks_close_and_return(
            page,
            return_url_before_submit,
            allow_root_return=allow_root_return_after_thanks,
        )
        if not thanks_ok:
            reason = f"после inline submit не закрыт/не отработан thanks: {thanks_reason}"
            print(f"  [INLINE-CONNECTION] ❌ {reason}")
            return 0, 1, reason, {"connection"}

        nav_ok, _, nav_reason = safe_goto(page, base_url)
        if not nav_ok:
            reason = f"после inline submit не удалось вернуться на {base_url}: {nav_reason}"
            print(f"  [INLINE-CONNECTION] ❌ {reason}")
            return 0, 1, reason, {"connection"}
        close_overlays(page)

    print("  [INLINE-CONNECTION] ✅ Успешно")
    return 1, 0, None, {"connection"}


def process_inline_undecided_form(
    page: Page,
    base_url: str,
    *,
    has_name_field: bool = False,
    allow_root_return_after_thanks: bool = False,
) -> tuple[int, int, str | None, set[str]]:
    """
    Fallback для страниц, где undecided-форма уже открыта в теле страницы
    (без popup-триггера).
    """
    print("\n[INLINE-UNDECIDED] Проверка inline-формы undecided")
    cfg = FORM_CONFIGS["undecided"]
    container = page.locator("section, form, div").filter(
        has=page.locator(cfg["phone"])
    ).first

    try:
        if container.count() == 0:
            print("  [INLINE-UNDECIDED] Форма не найдена")
            return 0, 0, None, set()
    except Exception:
        print("  [INLINE-UNDECIDED] Ошибка поиска формы")
        return 0, 0, None, set()

    filled = fill_form(page, container, "undecided", has_name_field=has_name_field)
    if not filled:
        reason = "inline undecided не заполнена (street/house/phone)"
        print(f"  [INLINE-UNDECIDED] ❌ {reason}")
        return 0, 1, reason, {"undecided"}

    submit = find_submit(container, "undecided")
    if not submit:
        reason = "кнопка отправки inline undecided не найдена"
        print(f"  [INLINE-UNDECIDED] ❌ {reason}")
        return 0, 1, reason, {"undecided"}

    if REALLY_SUBMIT:
        return_url_before_submit = page.url or base_url
        ok = submit_with_confirmation(
            page, container, "undecided",
            timeout_ms=SUBMIT_CONFIRM_TIMEOUT_MS, attempts=2
        )
        if not ok:
            reason = "подтверждение отправки inline undecided не получено"
            print(f"  [INLINE-UNDECIDED] ❌ {reason}")
            return 0, 1, reason, {"undecided"}

        thanks_ok, thanks_reason = verify_thanks_close_and_return(
            page,
            return_url_before_submit,
            allow_root_return=allow_root_return_after_thanks,
        )
        if not thanks_ok:
            reason = f"после inline submit не закрыт/не отработан thanks: {thanks_reason}"
            print(f"  [INLINE-UNDECIDED] ❌ {reason}")
            return 0, 1, reason, {"undecided"}

        nav_ok, _, nav_reason = safe_goto(page, base_url)
        if not nav_ok:
            reason = f"после inline submit не удалось вернуться на {base_url}: {nav_reason}"
            print(f"  [INLINE-UNDECIDED] ❌ {reason}")
            return 0, 1, reason, {"undecided"}
        close_overlays(page)

    print("  [INLINE-UNDECIDED] ✅ Успешно")
    return 1, 0, None, {"undecided"}


def process_checkaddress_form(
    page: Page,
    base_url: str,
    *,
    allow_root_return_after_thanks: bool = False,
) -> tuple[int, int, str | None]:
    """
    Проверка checkaddress с поддержкой двух режимов:
    1) инлайн-форма на странице
    2) попап по кнопке .checkaddress_address_button
    """
    cfg = FORM_CONFIGS["checkaddress"]
    container = page.locator("section, form, div").filter(
        has=page.locator(cfg["phone"])
    ).first

    try:
        has_inline = container.count() > 0
    except Exception:
        has_inline = False

    if not has_inline:
        print("  [CHECKADDRESS] Инлайн-форма не найдена, пробуем открыть попап по кнопке")
        triggers = page.locator(POPUP_BUTTON_CLASSES["checkaddress"])
        detected_form = None
        popup_container = None
        last_click_error: Exception | None = None
        clicked_any = False

        try:
            total_triggers = triggers.count()
        except Exception:
            total_triggers = 0

        if total_triggers == 0:
            return 0, 1, "форма checkaddress не найдена на странице"

        for i in range(total_triggers):
            trigger = triggers.nth(i)
            try:
                if not trigger.is_visible() or not trigger.is_enabled():
                    continue
                clicked_any = True
                trigger.scroll_into_view_if_needed()
                click_modes = ("normal", "force", "js")
                for click_mode in click_modes:
                    if click_mode == "normal":
                        trigger.click(timeout=7_000)
                    elif click_mode == "force":
                        trigger.click(timeout=7_000, force=True)
                    else:
                        try:
                            trigger.evaluate(
                                """(el) => {
                                    el.click();
                                    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                                }"""
                            )
                        except Exception:
                            continue

                    page.wait_for_timeout(450)
                    detected_form, popup_container = resolve_checkaddress_container_after_click(
                        page,
                        timeout_ms=12_000,
                    )
                    if detected_form == "checkaddress" and popup_container is not None:
                        break
                if detected_form == "checkaddress" and popup_container is not None:
                    break
            except Exception as err:
                last_click_error = err
                continue

        if detected_form != "checkaddress" or popup_container is None:
            reason = "форма checkaddress не найдена на странице"
            if last_click_error is not None:
                reason = f"{reason} (последняя ошибка клика: {last_click_error})"
            return 0, 1, reason
        container = popup_container

    filled = fill_form(page, container, "checkaddress")
    if not filled:
        return 0, 1, "форма checkaddress не заполнена"

    submit = find_submit(container, "checkaddress")
    if not submit:
        return 0, 1, "кнопка отправки checkaddress не найдена"

    submit.scroll_into_view_if_needed()
    print("  ✅ checkaddress готова")
    if not REALLY_SUBMIT:
        return 1, 0, None

    return_url_before_submit = page.url or base_url
    ok = submit_with_confirmation(
        page,
        container,
        "checkaddress",
        timeout_ms=SUBMIT_CONFIRM_TIMEOUT_MS,
        attempts=2,
    )
    if not ok:
        return 0, 1, "подтверждение отправки не получено"

    thanks_ok, thanks_reason = verify_thanks_close_and_return(
        page,
        return_url_before_submit,
        allow_root_return=allow_root_return_after_thanks,
    )
    if not thanks_ok:
        return 0, 1, f"не выполнен шаг закрытия Thanks: {thanks_reason}"

    nav_ok, _, nav_reason = safe_goto(page, base_url)
    if not nav_ok:
        return 0, 1, f"не удалось вернуться на {base_url} после Thanks: {nav_reason}"
    close_overlays(page)
    return 1, 0, None


# ---------------------------------------------------------------------------
# Выбор города
# ---------------------------------------------------------------------------

def run_city_scenario(page: Page, base_url: str, city_name: str) -> tuple[str | None, str | None]:
    """
    Открывает попап выбора города, кликает на нужный город,
    возвращает (city_base_url, city_business_url).
    Поддерживает все варианты вёрстки из набора локаторов RegionChoice.
    """
    sep = "=" * 55
    print(f"\n{sep}\n[CITY] Выбор города '{city_name}'\n{sep}")

    nav_ok, nav_critical, nav_reason = safe_goto(page, base_url)
    if not nav_ok:
        if nav_critical:
            raise SiteUnavailableError(f"CITY: не удалось открыть {base_url} | {nav_reason}")
        log_error("navigation_failed", page,
                  base_url.replace("https://", "").replace("http://", "").strip("/"),
                  extra=nav_reason[:180])
        return None, None
    close_overlays(page)
    domru_mobile_burger_opened = open_domru_mobile_city_burger(page)

    # Все известные варианты кнопки открытия попапа города
    CITY_BUTTON_SELECTORS = [
        "xpath=(//span[@id='city'])[1]",
        "xpath=(//span[@id='city'])[2]",
        "xpath=(//span[@id='city'])[3]",
        "xpath=(//a[@id='city'])[1]",
        "xpath=(//a[@id='city'])[2]",
        "xpath=(//a[@id='city'])[3]",
        "xpath=(//a[@class='city'])[2]",
        "xpath=//div[@class='header__wrapper-middle']//span[@id='city']",
        "xpath=(//button[@id='noButton'])[1]",
        "xpath=(//button[contains(@class,'popup-select-region__button') and contains(@class,'city')])[1]",
        ".region-search__button.button.button-red",
        ".region-search__button.button.button-green",
        "button.region-search__button",
        "button:has-text('Выбрать город')",
        "a.header__city.city",
        "a.header__city",
        "#city",
        "span#city",
        "a#city",
        "[class*='header'][class*='city']",
        "xpath=//div[@class='footer__city']//a",
    ]

    city_button_selectors = list(CITY_BUTTON_SELECTORS)
    if domru_mobile_burger_opened or is_domru_mobile_city_context(page):
        city_button_selectors = DOMRU_MOBILE_CITY_TRIGGER_SELECTORS + [
            sel for sel in city_button_selectors
            if sel not in {"[class*='header'][class*='city']", "a.header__city", "a.header__city.city"}
        ]

    city_btn = None
    city_btn_sel = None
    city_btn_idx = None
    for sel in city_button_selectors:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                candidate = loc.nth(i)
                try:
                    if candidate.is_visible():
                        city_btn = candidate
                        city_btn_sel = sel
                        city_btn_idx = i
                        print(f"  [CITY] Кнопка найдена (visible): '{sel}' idx={i}")
                        break
                except Exception:
                    pass
            if city_btn is not None:
                break
        except Exception:
            pass

    if city_btn is None or city_btn_sel is None or city_btn_idx is None:
        print("  [CITY] ❌ Кнопка выбора города не найдена — шаг пропущен")
        return None, None

    city_btn_clicked = False
    for attempt in range(1, 4):
        try:
            city_btn = page.locator(city_btn_sel).nth(city_btn_idx)
            city_btn.scroll_into_view_if_needed()
            city_btn.click(timeout=4000, force=True)
            city_btn_clicked = True
            break
        except Exception as e:
            print(f"  [CITY] Попытка клика {attempt}/3 не удалась: {e}")
            page.wait_for_timeout(500)

    if not city_btn_clicked:
        log_error(
            "click_failed", page,
            base_url.replace("https://", "").replace("http://", "").strip("/"),
            extra=f"city button click failed sel={city_btn_sel}"
        )
        return None, None

    page.wait_for_timeout(800)

    # Все известные варианты поля поиска города
    CITY_INPUT_SELECTORS = [
        "xpath=//input[@placeholder='Введите название города']",
        "xpath=//input[@id='city-input']",
        "xpath=//input[@placeholder='Поиск города']",
        "xpath=//input[@placeholder='Город']",
        "input[name='city']",
        "input[placeholder*='оиск']",
        "input[placeholder*='ород']",
        "input[type='search']",
    ]

    def fill_city_input_once() -> bool:
        for sel in CITY_INPUT_SELECTORS:
            try:
                inputs = page.locator(sel)
                for i in range(inputs.count()):
                    inp = inputs.nth(i)
                    try:
                        if not inp.is_visible():
                            continue
                        inp.click(force=True)
                        inp.fill(city_name)
                        page.wait_for_timeout(500)
                        print(f"  [CITY] Search input filled ({sel}, idx={i})")
                        return True
                    except Exception:
                        pass
            except Exception:
                pass
        return False

    city_input_filled = fill_city_input_once()

    if not city_input_filled and (domru_mobile_burger_opened or is_domru_mobile_city_context(page)):
        open_domru_mobile_city_burger(page)
        for sel in DOMRU_MOBILE_CITY_TRIGGER_SELECTORS:
            try:
                loc = page.locator(sel)
                for i in range(loc.count()):
                    trigger = loc.nth(i)
                    try:
                        if not trigger.is_visible():
                            continue
                        text = (trigger.inner_text() or "").strip()
                        if not text and "city-bold" in sel:
                            continue
                        trigger.click(force=True)
                        page.wait_for_timeout(450)
                        if fill_city_input_once():
                            city_input_filled = True
                            break
                    except Exception:
                        pass
                if city_input_filled:
                    break
            except Exception:
                pass

    # Все известные варианты списка городов
    CITY_LINK_SELECTORS = [
        "xpath=(//a[@class='region_item region_link'])",
        "xpath=//a[@class='region_item']",
        "xpath=//div[@class='city-coverage__capital']//a",
        "xpath=(//table[@class='city_list']//tbody//tr//td//a)",
        ".region_item.region_link",
        ".region_item",
    ]

    link = None
    for sel in CITY_LINK_SELECTORS:
        if link is not None:
            break
        try:
            locs = page.locator(sel).filter(has_text=city_name)
            for i in range(locs.count()):
                candidate = locs.nth(i)
                try:
                    candidate.wait_for(state="attached", timeout=3000)
                except Exception:
                    pass
                try:
                    if not candidate.is_visible():
                        continue
                    link = candidate
                    print(f"  [CITY] Город '{city_name}' найден: '{sel}' idx={i}")
                    break
                except Exception:
                    pass
        except Exception:
            pass

    if link is None or link.count() == 0:
        log_error("city_not_found", page,
                  base_url.replace("https://","").replace("http://","").strip("/"),
                  extra=f"city={city_name}")
        return None, None

    old_url = page.url
    city_link_clicked = False
    for attempt in range(1, 4):
        # Антифлак: если URL уже сменился, считаем выбор города успешным.
        if page.url != old_url:
            city_link_clicked = True
            print("  [CITY] URL уже сменился до повторного клика — считаем выбор успешным")
            break
        try:
            link.scroll_into_view_if_needed()
            link.click(timeout=4000, force=True)
            city_link_clicked = True
            break
        except Exception as e:
            print(f"  [CITY] Клик по городу, попытка {attempt}/3: {e}")
            page.wait_for_timeout(500)
            # Антифлак: click мог сработать, но Playwright выбросил timeout
            # при ожидании завершения навигации.
            if page.url != old_url:
                city_link_clicked = True
                print("  [CITY] После исключения URL сменился — считаем выбор успешным")
                break

    if not city_link_clicked:
        log_error("click_failed", page,
                  base_url.replace("https://","").replace("http://","").strip("/"),
                  extra=f"city link click failed city={city_name}")
        return None, None

    print(f"  [CITY] Клик по '{city_name}'")

    city_base_url = None
    for _ in range(50):
        page.wait_for_timeout(300)
        if page.url != old_url:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=CITY_LOADSTATE_TIMEOUT_MS)
            except Exception as e:
                print(f"  [CITY] domcontentloaded timeout ({CITY_LOADSTATE_TIMEOUT_MS}ms), continue without wait: {e}")
            city_base_url = page.url.rstrip("/")
            break

    if not city_base_url:
        log_error("city_no_redirect", page,
                  base_url.replace("https://","").replace("http://","").strip("/"),
                  extra=f"city={city_name}")
        return None, None

    print(f"  [CITY] ✅ {city_base_url}")
    return city_base_url, city_base_url + "/business"


def normalize_expected_form_types(cfg: dict) -> tuple[set[str], set[str]]:
    requested_raw = cfg.get("_expected_form_types") or []
    requested = {str(item).strip().lower() for item in requested_raw if str(item).strip()}
    supported = set(FORM_CONFIGS.keys())
    active = requested.intersection(supported)
    unsupported = requested - supported
    return active, unsupported


def _form_oriented_presence_error(form_type: str, reason: str) -> str:
    return f"presence-check {form_type}: {reason}"


def _find_presence_trigger(page: Page, form_type: str):
    effective_form_type = "connection" if form_type == "connection_cards" else form_type
    selector = POPUP_BUTTON_CLASSES.get(effective_form_type)
    if not selector:
        return None
    buttons = page.locator(selector)
    for index in range(buttons.count()):
        button = buttons.nth(index)
        try:
            if button.is_visible() and button.is_enabled():
                return button
        except Exception:
            pass
    return None


def _presence_container_has_required_fields(container, form_type: str) -> bool:
    effective_form_type = "connection" if form_type == "connection_cards" else form_type
    cfg = FORM_CONFIGS.get(effective_form_type)
    if not cfg:
        return False
    try:
        phone = container.locator(cfg["phone"]).first
        submit = container.locator(cfg["submit"]).first
        if phone.count() == 0 or not phone.is_visible():
            return False
        if submit.count() == 0 or not submit.is_visible():
            return False
        if not cfg.get("no_house"):
            house_selector = cfg.get("house")
            if house_selector:
                house = container.locator(house_selector).first
                if house.count() == 0 or not house.is_visible():
                    return False
        return True
    except Exception:
        return False


def _presence_check_one_form(page: Page, base_url: str, form_type: str) -> tuple[bool, str]:
    """Open one expected form and inspect its controls without filling or submitting."""
    if form_type == "business":
        return True, "business presence-check skipped while business steps are disabled"

    effective_form_type = "connection" if form_type == "connection_cards" else form_type
    if effective_form_type in {"connection", "undecided"}:
        inline_container = find_visible_form_container_by_phone(
            page, FORM_CONFIGS[effective_form_type]
        )
        if inline_container is not None and _presence_container_has_required_fields(
            inline_container, effective_form_type
        ):
            close_popup_or_page(page)
            return True, "inline form detected"

    if effective_form_type == "profit":
        detected_type, auto_container = wait_for_popup_with_fields(
            page,
            timeout_ms=2_000,
            form_hint="profit",
        )
        if detected_type == "profit" and auto_container is not None:
            if _presence_container_has_required_fields(auto_container, "profit"):
                close_popup_or_page(page)
                return True, "automatic popup detected"
            close_popup_or_page(page)

    button = _find_presence_trigger(page, effective_form_type)
    if button is None:
        return False, "trigger not found or not interactable"

    try:
        button.scroll_into_view_if_needed()
        button.click(force=True)
        page.wait_for_timeout(popup_click_settle_ms(page))
    except Exception as exc:
        return False, f"trigger click failed: {str(exc)[:180]}"

    detected_type, container = wait_for_popup_with_fields(
        page,
        timeout_ms=popup_wait_timeout_ms(page),
        form_hint=effective_form_type,
    )
    try:
        if detected_type != effective_form_type or container is None:
            return False, f"opened form type={detected_type or 'none'}"
        if not _presence_container_has_required_fields(container, effective_form_type):
            return False, "required fields or submit control not found"
        return True, "popup opened with required controls"
    finally:
        close_popup_or_page(page)


def _run_form_oriented_presence_checks(
    page: Page,
    base_url: str,
    expected_forms: set[str],
    optional_forms: set[str],
) -> tuple[int, list[str]]:
    failures: list[str] = []
    checked = 0
    for form_type in sorted(expected_forms):
        if form_type in optional_forms:
            print(f"  [PRESENCE] optional form={form_type}")
        nav_ok, _, nav_reason = safe_goto(page, base_url)
        if not nav_ok:
            failures.append(_form_oriented_presence_error(form_type, f"navigation failed: {nav_reason[:180]}"))
            continue
        dismiss_region_popup(page)
        accept_cookie_banner(page)
        close_mobile_burger_menu(page)
        checked += 1
        ok, reason = _presence_check_one_form(page, base_url, form_type)
        if not ok and form_type not in optional_forms:
            failures.append(_form_oriented_presence_error(form_type, reason))
            print(f"  [PRESENCE] ❌ {form_type}: {reason}")
        elif ok:
            print(f"  [PRESENCE] ✅ {form_type}: {reason}")
        else:
            print(f"  [PRESENCE] ℹ️ optional {form_type}: {reason}")
    return checked, failures


def run_form_oriented_scenario(page: Page, cfg: dict):
    """Run presence checks for all expected forms and fully test one primary form."""
    base_url = cfg["base_url"]
    site_label = base_url.replace("https://", "").replace("http://", "").strip("/")
    primary_form = str(cfg.get("_primary_form") or "").strip().lower()
    expected_forms, unsupported_forms = normalize_expected_form_types(cfg)
    optional_forms, _ = normalize_expected_form_types(
        {"_expected_form_types": cfg.get("_optional_expected_form_types", [])}
    )
    optional_forms -= {"business"}
    has_name_field = cfg.get("has_name_field", False)
    service_mode = normalize_service_mode(cfg.get("_service_mode", SERVICE_MODE_ALL))

    if primary_form == "express":
        primary_form = "express-connection"
    if primary_form == "connection_cards":
        primary_form = "connection"
    if primary_form not in FORM_CONFIGS or primary_form == "business":
        raise pytest.UsageError(f"Неподдерживаемая primary форма: {primary_form!r}")

    allure.dynamic.parameter("run_mode", "form-oriented")
    allure.dynamic.parameter("primary_form", primary_form)
    allure.dynamic.parameter("brand", cfg.get("_scope_brand", ""))
    allure.dynamic.parameter("url", base_url)
    allure.dynamic.label("runMode", "form-oriented")
    allure.dynamic.label("primaryForm", primary_form)
    print(
        f"\n{'#' * 55}\n# FORM-ORIENTED: {site_label} | "
        f"primary={primary_form} | expected={','.join(sorted(expected_forms))}\n{'#' * 55}"
    )

    if unsupported_forms:
        allure.attach(
            "Не реализованы: " + ", ".join(sorted(unsupported_forms)),
            name=f"Unsupported expected forms ({site_label})",
            attachment_type=allure.attachment_type.TEXT,
        )

    with allure.step("Presence-check ожидаемых форм"):
        _, presence_failures = _run_form_oriented_presence_checks(
            page, base_url, expected_forms, optional_forms
        )

    primary_expected = {primary_form}
    nav_ok, nav_critical, nav_reason = safe_goto(page, base_url)
    if not nav_ok:
        reason = f"не удалось открыть {base_url} | {nav_reason}"
        if nav_critical:
            skip_site_due_unavailability(site_label, "full", f"форма {primary_form}", reason, page)
        presence_failures.append(f"full-check {primary_form}: {reason}")
    else:
        dismiss_region_popup(page)
        accept_cookie_banner(page)
        close_mobile_burger_menu(page)

        full_failures: list[str] = []
        with allure.step(f"Full functional check: {primary_form}"):
            if primary_form == "checkaddress":
                button = _find_presence_trigger(page, "checkaddress")
                if button is None:
                    full_failures.append("trigger not found")
                else:
                    try:
                        button.click(force=True)
                        detected, container = resolve_checkaddress_container_after_click(page)
                        if detected != "checkaddress" or container is None:
                            full_failures.append("checkaddress form did not open")
                        elif not fill_form(page, container, "checkaddress", has_name_field=has_name_field):
                            full_failures.append("checkaddress form not filled")
                        elif not submit_with_confirmation(
                            page, container, "checkaddress", timeout_ms=SUBMIT_CONFIRM_TIMEOUT_MS, attempts=2
                        ):
                            full_failures.append("checkaddress confirmation not received")
                    except Exception as exc:
                        full_failures.append(str(exc)[:300])
            elif primary_form == "connection":
                s, f, first, tested = process_all_popups(
                    page, base_url, has_name_field=has_name_field,
                    service_mode=service_mode, allow_root_return_after_thanks=True,
                    expected_form_types=primary_expected,
                )
                if "connection" not in tested:
                    inline_s, inline_f, inline_first, inline_tested = process_inline_connection_form(
                        page, base_url, has_name_field=has_name_field, allow_root_return_after_thanks=True
                    )
                    s += inline_s
                    f += inline_f
                    tested |= inline_tested
                    first = first or inline_first
                if f > 0 or "connection" not in tested:
                    full_failures.append(first or "connection full-check failed")
            elif primary_form == "undecided":
                s, f, first, tested = process_all_popups(
                    page, base_url, has_name_field=has_name_field,
                    service_mode=service_mode, allow_root_return_after_thanks=True,
                    expected_form_types=primary_expected,
                )
                if "undecided" not in tested:
                    inline_s, inline_f, inline_first, inline_tested = process_inline_undecided_form(
                        page, base_url, has_name_field=has_name_field, allow_root_return_after_thanks=True
                    )
                    s += inline_s
                    f += inline_f
                    tested |= inline_tested
                    first = first or inline_first
                if f > 0 or "undecided" not in tested:
                    full_failures.append(first or "undecided full-check failed")
            else:
                s, f, first, tested, _ = process_all_popups(
                    page, base_url, has_name_field=has_name_field,
                    service_mode=service_mode, allow_root_return_after_thanks=True,
                    expected_form_types=primary_expected,
                )
                if f > 0 or primary_form not in tested:
                    full_failures.append(first or f"{primary_form} full-check failed")

        presence_failures.extend(f"full-check {primary_form}: {item}" for item in full_failures)

    details = "\n".join(presence_failures)
    allure.dynamic.parameter("check_kind", "presence+full")
    allure.attach(
        details or "All presence-checks and the primary full-check passed.",
        name=f"Form-oriented result ({site_label})",
        attachment_type=allure.attachment_type.TEXT,
    )
    assert not presence_failures, f"[{site_label}] Form-oriented failures:\n{details}"


def run_site_scenario(page: Page, cfg: dict):
    """
    Полный сценарий для сайта:
    1. Форма checkaddress (если есть)
    2. Все попапы главной
    3. Попапы /business (если есть)
    4. Сценарий города (если задан city_name):
       4a. Попапы главной города
       4b. Попапы /business города (если has_business)
    """
    global SUPPRESS_TECH_ALERTS
    if str(cfg.get("_run_mode") or "legacy").strip().lower() == "form-oriented":
        run_form_oriented_scenario(page, cfg)
        return
    base_url       = cfg["base_url"]
    has_name_field = cfg.get("has_name_field", False)
    sep            = "=" * 55
    site_label     = base_url.replace("https://", "").replace("http://", "").strip("/")
    city_name      = cfg.get("city_name")
    city_base      = None
    city_biz       = None
    service_mode   = normalize_service_mode(cfg.get("_service_mode", SERVICE_MODE_ALL))
    source_mode    = str(cfg.get("_source_mode") or "").strip().lower()
    is_url_mode    = source_mode == "url_file"
    expect_connection_cards = bool(cfg.get("_expect_connection_cards", False))
    expected_forms, unsupported_forms = normalize_expected_form_types(cfg)
    optional_expected_forms, _ = normalize_expected_form_types(
        {"_expected_form_types": cfg.get("_optional_expected_form_types", [])}
    )
    expected_popup_forms = expected_forms - {"checkaddress", "business"}
    optional_popup_forms = optional_expected_forms - {"checkaddress", "business"}
    expected_business_forms = {"business"} if "business" in expected_forms else set()
    total_success_submits = 0
    deferred_checkaddress_reason: str | None = None

    print(f"\n{'#'*55}\n# САЙТ: {site_label} | MODE: {service_mode}\n{'#'*55}")
    if is_url_mode:
        print(f"  [URL-MODE] expected forms: {', '.join(sorted(expected_forms)) or '(none)'}")
        if optional_popup_forms:
            print(f"  [URL-MODE] optional popup forms: {', '.join(sorted(optional_popup_forms))}")
    if unsupported_forms:
        text = (
            f"[{site_label}] Формы ещё не реализованы в тесте: "
            f"{', '.join(sorted(unsupported_forms))}"
        )
        print(f"  [FORM] {text}")
        allure.attach(
            text,
            name=f"Unsupported expected forms ({site_label})",
            attachment_type=allure.attachment_type.TEXT,
        )

    # ── 1. Форма checkaddress ─────────────────────────────────────────────
    with allure.step("Шаг 1: форма checkaddress"):
        if ("checkaddress" in expected_forms) if is_url_mode else cfg.get("has_checkaddress"):
            print(f"\n{sep}\n[{site_label}] Шаг 1: форма checkaddress\n{sep}")
            goto_or_handle_step(page, base_url, site_label, "1", "форма checkaddress")
            close_overlays(page)

            checkaddress_success, checkaddress_failed, step_reason = process_checkaddress_form(
                page,
                base_url,
                allow_root_return_after_thanks=is_url_mode,
            )
            total_success_submits += checkaddress_success
            if checkaddress_failed > 0 and step_reason:
                # Шумоподавление: отправляем step-alert по checkaddress только
                # если в рамках текущего URL не было ни одного успешного submit.
                deferred_checkaddress_reason = step_reason[:900]
        else:
            reason = (
                "не входит в expected forms текущего URL"
                if is_url_mode
                else "has_checkaddress=False"
            )
            mark_step_not_applicable(site_label, "1", "форма checkaddress", reason)

    # ── 2. Попапы главной ─────────────────────────────────────────────────
    with allure.step("Шаг 2: попапы главной"):
        if is_url_mode and not expected_popup_forms and not expect_connection_cards:
            mark_step_not_applicable(
                site_label,
                "2",
                "попапы главной",
                "для текущего form-suite popup-типы не ожидаются",
            )
        else:
            print(f"\n{sep}\n[{site_label}] Шаг 2: попапы главной\n{sep}")
            goto_or_handle_step(page, base_url, site_label, "2", "попапы главной")
            close_overlays(page)
            try:
                s, f, first_fail, tested_popup_forms, tested_trigger_kinds = process_all_popups(
                    page,
                    base_url,
                    has_name_field=has_name_field,
                    service_mode=service_mode,
                    allow_root_return_after_thanks=is_url_mode,
                    expected_form_types=expected_popup_forms if is_url_mode else None,
                    expect_connection_cards=expect_connection_cards if is_url_mode else False,
                )
            except SiteUnavailableError as e:
                skip_site_due_unavailability(site_label, "2", "попапы главной", str(e), page)
            if is_url_mode and "connection" in expected_popup_forms and "connection" not in tested_popup_forms:
                inline_s, inline_f, inline_first_fail, inline_tested = process_inline_connection_form(
                    page,
                    base_url,
                    has_name_field=has_name_field,
                    allow_root_return_after_thanks=is_url_mode,
                )
                s += inline_s
                f += inline_f
                tested_popup_forms |= inline_tested
                if first_fail is None and inline_first_fail:
                    first_fail = inline_first_fail[:220]
            if is_url_mode and "undecided" in expected_popup_forms and "undecided" not in tested_popup_forms:
                inline_s, inline_f, inline_first_fail, inline_tested = process_inline_undecided_form(
                    page,
                    base_url,
                    has_name_field=has_name_field,
                    allow_root_return_after_thanks=is_url_mode,
                )
                # Для A/B-кейсов (например, mts-home-online.ru) undecided может быть optional:
                # если форма не подтвердилась/не заполнилась, не считаем это ошибкой шага.
                if "undecided" in optional_popup_forms and inline_f > 0 and inline_s == 0:
                    optional_reason = inline_first_fail or "inline undecided недоступна"
                    print(
                        "  [INLINE-UNDECIDED] ℹ️ optional форма не подтверждена "
                        f"(допустимо): {optional_reason}"
                    )
                    inline_f = 0
                    inline_first_fail = None
                s += inline_s
                f += inline_f
                tested_popup_forms |= inline_tested
                if first_fail is None and inline_first_fail:
                    first_fail = inline_first_fail[:220]
            if is_url_mode:
                missing_popup_forms = expected_popup_forms - tested_popup_forms
                missing_required_popup_forms = missing_popup_forms - optional_popup_forms
                missing_optional_popup_forms = missing_popup_forms & optional_popup_forms
                if missing_optional_popup_forms:
                    optional_text = ", ".join(sorted(missing_optional_popup_forms))
                    print(f"  [POPUP] ℹ️ optional формы не обнаружены (допустимо): {optional_text}")
                if missing_required_popup_forms:
                    f += len(missing_required_popup_forms)
                    missing_text = ", ".join(sorted(missing_required_popup_forms))
                    detail = f"не найдены ожидаемые типы форм: {missing_text}"
                    if first_fail is None:
                        first_fail = detail[:220]
                    print(f"  [POPUP] ❌ {detail}")
                if expect_connection_cards and "connection_card" not in tested_trigger_kinds:
                    f += 1
                    detail = "не сработал card-триггер connection_address_card_button"
                    if first_fail is None:
                        first_fail = detail[:220]
                    print(f"  [POPUP] ❌ {detail}")
            total_success_submits += s
            if f > 0:
                reason = f"{f} ошибок, {s} успешно"
                if first_fail:
                    reason += f" | first={first_fail}"
                if total_success_submits > 0:
                    print(
                        "  [STEP-ALERT] ℹ️ suppressed alert for step 2: "
                        f"по URL найден успешный submit ({total_success_submits})"
                    )
                    f = 0
                    first_fail = None
                else:
                    send_step_alert(site_label, "2", "попапы главной", reason[:900], page)
            assert f == 0, (
                f"[{site_label}] Попапы главной: {f} ошибок, {s} успешно"
                + (f" | first={first_fail}" if first_fail else "")
            )

    if deferred_checkaddress_reason:
        if total_success_submits <= 0:
            if (
                (SUPPRESS_BEELINE_CHECKADDRESS_ALERTS and _is_beeline_runtime_url(base_url))
                or (SUPPRESS_MTS_CHECKADDRESS_ALERTS and _is_mts_runtime_url(base_url))
            ):
                print(
                    "  [STEP-ALERT] ℹ️ suppressed temporary MTS/Beeline checkaddress alert: "
                    f"{deferred_checkaddress_reason}"
                )
            else:
                send_step_alert(site_label, "1", "форма checkaddress", deferred_checkaddress_reason, page)
        else:
            print(
                "  [STEP-ALERT] ℹ️ suppressed checkaddress alert: "
                f"по URL найден успешный submit ({total_success_submits})"
            )

    print(f"\n{'#'*55}\n# ✅ ГОТОВО: {site_label}\n{'#'*55}\n")


# ---------------------------------------------------------------------------

# Independent Beeline scenario entrypoint.

SCOPE = "mts_home_online_ab"


def pytest_generate_tests(metafunc):
    if "scenario_cfg" not in metafunc.fixturenames:
        return
    requested_scope = str(
        metafunc.config.getoption("--brand-scope", default="") or ""
    ).strip().lower()
    if requested_scope != SCOPE:
        raise pytest.UsageError(
            f"Сценарий {SCOPE!r} запущен с несовместимым --brand-scope={requested_scope!r}."
        )
    configs = build_site_configs_from_brand_scope(scope=SCOPE)
    values = list(configs.values())
    metafunc.parametrize(
        "scenario_cfg",
        values,
        ids=[f"{SCOPE}:{cfg['base_url']}" for cfg in values],
    )


def test_mts_home_online_ab(
    page: Page,
    scenario_cfg: dict,
    browser_name: str,
    blocking_profile: str,
    execution_profile: str,
):
    cfg = scenario_cfg
    url = cfg["base_url"]
    allure.dynamic.title(f"{SCOPE}: {url}")
    allure.dynamic.label("suite", "Brand-specific provider scenarios")
    allure.dynamic.label("runMode", "brand-oriented")
    allure.dynamic.label("brandScope", SCOPE)
    allure.dynamic.label("scenarioType", "brand")
    allure.dynamic.parameter("brand_scope", SCOPE)
    allure.dynamic.parameter("url", url)
    allure.dynamic.parameter("browser", browser_name)
    allure.dynamic.parameter("blocking_profile", blocking_profile)
    allure.dynamic.parameter("execution_profile", execution_profile)
    allure.dynamic.parameter(
        "domain_session",
        "true" if cfg.get("_domain_session") else "false",
    )
    run_site_scenario(page, cfg)

