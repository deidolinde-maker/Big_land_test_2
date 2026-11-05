from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


SUPPORTED_FORM_TYPES = {
    "profit",
    "connection",
    "checkaddress",
    "undecided",
    "business",
    "moving",
    "express-connection",
}

FORM_SUITE_TO_FORM_TYPE: dict[str, str] = {
    "profit": "profit",
    "connection": "connection",
    "connection_cards": "connection",
    "checkaddress": "checkaddress",
    "business": "business",
    "undecided": "undecided",
    "moving": "moving",
    "express": "express-connection",
}

FORM_SUITE_CHOICES: tuple[str, ...] = (
    "all",
    "profit",
    "connection",
    "connection_cards",
    "checkaddress",
    "business",
    "undecided",
    "moving",
    "express",
)


def canonicalize_url(url: str) -> str:
    line = (url or "").strip()
    parsed = urlsplit(line)
    scheme = (parsed.scheme or "https").lower()
    netloc = (parsed.netloc or "").lower()
    path = parsed.path or ""
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _resolve_allowlists_dir() -> Path:
    return (Path(__file__).resolve().parent / "form_allowlists").resolve()


def _load_allowlist(file_name: str) -> set[str]:
    file_path = _resolve_allowlists_dir() / file_name
    if not file_path.exists():
        return set()

    result: set[str] = set()
    for raw in file_path.read_text(encoding="utf-8").splitlines():
        line = (raw or "").strip()
        if not line or line.startswith("#"):
            continue
        line = line.strip().strip('"').strip("'")
        if not line:
            continue
        # In source lists URL can have tail markers like " (закрыто)".
        line = line.split()[0].strip()
        try:
            normalized = canonicalize_url(line)
        except Exception:
            continue
        if urlsplit(normalized).netloc:
            result.add(normalized)
    return result

CONNECTION_URL_ALLOWLIST = _load_allowlist("connection.txt")
CONNECTION_CARD_URL_ALLOWLIST = _load_allowlist("connection_cards.txt")
CHECKADDRESS_URL_ALLOWLIST = _load_allowlist("checkaddress.txt")
BUSINESS_URL_ALLOWLIST = _load_allowlist("business.txt")
EXPRESS_URL_ALLOWLIST = _load_allowlist("express.txt")
UNDECIDED_URL_ALLOWLIST = _load_allowlist("undecided.txt")
MOVING_URL_ALLOWLIST = _load_allowlist("moving.txt")
PROFIT_URL_ALLOWLIST = _load_allowlist("profit.txt")

OVERRIDE_FILE_BY_BRAND: dict[str, str] = {
    "mts": "mts.json",
    "beeline": "beeline.json",
    "megafon": "megafon.json",
    "t2": "t2.json",
    "rostelecom": "rostelecom.json",
    "domru": "domru.json",
    "ttk": "ttk.json",
}

FORM_SUITE_TO_ALLOWLIST: dict[str, set[str]] = {
    "profit": PROFIT_URL_ALLOWLIST,
    "connection": CONNECTION_URL_ALLOWLIST,
    "connection_cards": CONNECTION_CARD_URL_ALLOWLIST,
    "checkaddress": CHECKADDRESS_URL_ALLOWLIST,
    "business": BUSINESS_URL_ALLOWLIST,
    "undecided": UNDECIDED_URL_ALLOWLIST,
    "moving": MOVING_URL_ALLOWLIST,
    "express": EXPRESS_URL_ALLOWLIST,
}


def normalize_form_suite(value: str | None) -> str:
    suite = (value or "all").strip().lower().replace("-", "_")
    aliases = {
        "connect_cards": "connection_cards",
        "connection_card": "connection_cards",
        "express_connection": "express",
    }
    suite = aliases.get(suite, suite)

    if not suite:
        suite = "all"
    if suite not in FORM_SUITE_CHOICES:
        allowed = ", ".join(FORM_SUITE_CHOICES)
        raise ValueError(f"Неизвестный form_suite={value!r}. Доступно: {allowed}")
    return suite


def available_form_suites() -> list[str]:
    return list(FORM_SUITE_CHOICES)


def expected_form_types_for_suite(form_suite: str) -> list[str]:
    suite = normalize_form_suite(form_suite)
    if suite == "all":
        return []
    return [FORM_SUITE_TO_FORM_TYPE[suite]]


def expects_connection_cards_for_suite(form_suite: str) -> bool:
    return normalize_form_suite(form_suite) == "connection_cards"


def is_url_in_form_suite(page_url: str, form_suite: str) -> bool:
    suite = normalize_form_suite(form_suite)
    if suite == "all":
        return True

    allowlist = FORM_SUITE_TO_ALLOWLIST.get(suite) or set()
    return _is_allowlisted(canonicalize_url(page_url), allowlist)


def filter_urls_for_form_suite(urls: list[str], form_suite: str) -> list[str]:
    suite = normalize_form_suite(form_suite)
    if suite == "all":
        return list(urls)
    return [url for url in urls if is_url_in_form_suite(url, suite)]


def _is_allowlisted(current_url: str, allowlist: set[str]) -> bool:
    if current_url in allowlist:
        return True
    if current_url.endswith("/") and current_url.rstrip("/") in allowlist:
        return True
    if (current_url + "/") in allowlist:
        return True
    return False


def _resolve_expectations_dir(expectations_dir: str | Path | None = None) -> Path:
    if expectations_dir is not None:
        return Path(expectations_dir).resolve()
    return (Path(__file__).resolve().parent / "form_expectations").resolve()


def _normalize_form_list(raw: object, *, field_name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{field_name} must be list[str]")

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip().lower()
        if not value:
            continue
        if value not in SUPPORTED_FORM_TYPES:
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def load_brand_form_overrides(
    brand: str,
    *,
    expectations_dir: str | Path | None = None,
) -> dict[str, dict[str, list[str]]]:
    brand_key = (brand or "").strip().lower()
    file_name = OVERRIDE_FILE_BY_BRAND.get(brand_key)
    if not file_name:
        return {}

    root = _resolve_expectations_dir(expectations_dir)
    file_path = root / file_name
    if not file_path.exists():
        return {}

    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid form overrides structure: {file_path}")

    normalized: dict[str, dict[str, list[str]]] = {}
    for raw_url, raw_rules in payload.items():
        url = canonicalize_url(str(raw_url))
        if not urlsplit(url).netloc:
            continue
        if not isinstance(raw_rules, dict):
            continue
        missing = _normalize_form_list(raw_rules.get("missing"), field_name="missing")
        force_present = _normalize_form_list(
            raw_rules.get("force_present"),
            field_name="force_present",
        )
        normalized[url] = {
            "missing": missing,
            "force_present": force_present,
        }

    return normalized


def build_expected_form_types(
    *,
    page_url: str,
    site_cfg: dict,
    override_rules: dict[str, dict[str, list[str]]] | None = None,
) -> list[str]:
    current_url = canonicalize_url(page_url)
    parsed = urlsplit(current_url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()

    expected: set[str] = set()
    if _is_allowlisted(current_url, CONNECTION_URL_ALLOWLIST):
        expected.add("connection")
    if _is_allowlisted(current_url, CONNECTION_CARD_URL_ALLOWLIST):
        expected.add("connection")
    if _is_allowlisted(current_url, PROFIT_URL_ALLOWLIST):
        expected.add("profit")

    if _is_allowlisted(current_url, CHECKADDRESS_URL_ALLOWLIST):
        expected.add("checkaddress")

    # business: строго по согласованному списку URL.
    if _is_allowlisted(current_url, BUSINESS_URL_ALLOWLIST):
        expected.add("business")

    # express-connection: строго по согласованному списку URL.
    if _is_allowlisted(current_url, EXPRESS_URL_ALLOWLIST):
        expected.add("express-connection")

    # moving-попап: строго по allowlist и по /usluga-pereezd.
    if _is_allowlisted(current_url, MOVING_URL_ALLOWLIST) or "/usluga-pereezd" in path:
        expected.add("moving")

    # undecided: строго по согласованному списку URL.
    if _is_allowlisted(current_url, UNDECIDED_URL_ALLOWLIST):
        expected.add("undecided")

    if override_rules:
        override = override_rules.get(current_url)
        if override:
            expected.update(override.get("force_present", []))
            for form_type in override.get("missing", []):
                expected.discard(form_type)

    # Явно согласованные allowlist-правила имеют приоритет над Excel-overrides.
    if _is_allowlisted(current_url, CONNECTION_URL_ALLOWLIST):
        expected.add("connection")
    if _is_allowlisted(current_url, CONNECTION_CARD_URL_ALLOWLIST):
        expected.add("connection")
    if _is_allowlisted(current_url, CHECKADDRESS_URL_ALLOWLIST):
        expected.add("checkaddress")
    if _is_allowlisted(current_url, BUSINESS_URL_ALLOWLIST):
        expected.add("business")
    if _is_allowlisted(current_url, EXPRESS_URL_ALLOWLIST):
        expected.add("express-connection")
    if _is_allowlisted(current_url, PROFIT_URL_ALLOWLIST):
        expected.add("profit")
    if _is_allowlisted(current_url, UNDECIDED_URL_ALLOWLIST):
        expected.add("undecided")
    if _is_allowlisted(current_url, MOVING_URL_ALLOWLIST):
        expected.add("moving")

    return sorted(expected)


def expects_connection_card_trigger(page_url: str) -> bool:
    return _is_allowlisted(canonicalize_url(page_url), CONNECTION_CARD_URL_ALLOWLIST)


def optional_expected_form_types(page_url: str) -> list[str]:
    current_url = canonicalize_url(page_url)
    optional: set[str] = set()
    # EXPRESS может быть скрыт A/B-тестом на согласованных URL.
    if _is_allowlisted(current_url, EXPRESS_URL_ALLOWLIST):
        optional.add("express-connection")
    return sorted(optional)
