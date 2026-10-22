from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import json
import os
import re
import sys

from alert_events import event_file


RESULTS_DIR = Path(os.getenv("ALLURE_RESULTS_DIR", "allure-results"))
RUN_URL = os.getenv("RUN_URL", "").strip()
ALLURE_URL = os.getenv("ALLURE_URL", "").strip()
SITE_HINT = os.getenv("SITE_HINT", "").strip()

OUT_MESSAGE_FILE = Path("telegram_message.txt")
OUT_FLAG_FILE = Path("telegram_should_send.txt")
OUT_ALERT_MESSAGE_FILE = Path("telegram_alert_message.txt")
OUT_ALERT_FLAG_FILE = Path("telegram_alert_should_send.txt")

STATE_FILE = Path(os.getenv("NOTIFY_STATE_FILE", "notify_state.json"))
STATE_URL = os.getenv("NOTIFY_STATE_URL", "").strip()
SUMMARY_STATE_FILE = Path(os.getenv("SUMMARY_STATE_FILE", "summary_state.json"))
ALERT_STATE_FILE = Path(os.getenv("ALERT_STATE_FILE", "alert_state.json"))

NORMAL_ALERT_MAX_PER_SITE = 5
MASS_ALERT_SITE_THRESHOLD = 5
MAX_MESSAGE_LEN = 3600

try:
    # Avoid UnicodeEncodeError on Windows consoles with cp1251.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def env_bool(name: str, default: bool = True) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


ALERT_ERRORS_ENABLED = env_bool("ALERT_ERRORS_ENABLED", True)
ALERT_AGGREGATES_ENABLED = env_bool("ALERT_AGGREGATES_ENABLED", True)
ALERT_SUMMARY_ENABLED = env_bool("ALERT_SUMMARY_ENABLED", True)
ALERT_RECOVERED_ENABLED = env_bool("ALERT_RECOVERED_ENABLED", True)
ALERT_DAILY_SUMMARY_ENABLED = env_bool("ALERT_DAILY_SUMMARY_ENABLED", True)
NOTIFY_MODE = (os.getenv("NOTIFY_MODE") or "run").strip().lower()
MSK_TZ = timezone(timedelta(hours=3))
DEFAULT_FORM_TITLE = "заявки"
SUMMARY_SEND_HOURS = (9, 17)


STEP_PATTERNS: list[tuple[str, str]] = [
    ("Появился попап заявки", "попап не появился"),
    ("Появился попап заявки", "popup_not_found"),
    ("Кнопка-триггер не найдена", "кнопка-триггер"),
    ("Кнопка-триггер не найдена", "trigger"),
    ("Выбор улицы в сайджесте", "street"),
    ("Выбор дома в сайджесте", "house"),
    ("Ввод номера телефона", "phone"),
    ("Отправка заявки после клика на кнопку отправки", "submit"),
    ("Отправка заявки после клика на кнопку отправки", "no_confirmation"),
    ("Изменить город в попапе заявки", "city"),
]


def normalize_text(value: str, max_len: int = 220) -> str:
    text = " ".join((value or "").split()).strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def load_alert_events() -> list[dict]:
    path = event_file()
    if not path.exists():
        return []
    events: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict) and item.get("group_key"):
                events.append(item)
    except Exception:
        return []
    return events


def clear_alert_events() -> None:
    try:
        event_file().write_text("", encoding="utf-8")
    except Exception:
        pass


def runtime_scope_key() -> str:
    job = (os.getenv("JOB_NAME") or "local").strip()
    scope = (os.getenv("PROVIDER_SCOPE") or "all").strip()
    return f"{job}|{scope}"


def load_alert_state() -> dict:
    try:
        data = json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("scopes"), dict):
            return data
    except Exception:
        pass
    return {"scopes": {}}


def save_alert_state(state: dict) -> None:
    try:
        ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def build_runtime_alert(events: list[dict]) -> tuple[str, bool, str]:
    state = load_alert_state()
    scope = runtime_scope_key()
    previous = state.setdefault("scopes", {}).get(scope) or {}
    grouped: dict[str, list[dict]] = {}
    for event in events:
        grouped.setdefault(str(event["group_key"]), []).append(event)

    current: dict[str, dict] = {}
    blocks: list[str] = []
    has_critical = False
    for group_key, items in grouped.items():
        first = items[0]
        has_critical = has_critical or first.get("alert_type") == "critical"
        pages = sorted({str(item.get("page_url") or item.get("site") or "") for item in items})
        repeated = group_key in previous
        headline = "Ошибка все еще актуальна" if repeated else "Ошибка на всех страницах лендинга"
        if len(pages) <= 1:
            headline = "Ошибка все еще актуальна" if repeated else "Ошибка автотеста"
        lines = [
            f"❌ {headline}",
            f"🌐 Домен: {first.get('domain') or first.get('site') or 'unknown-site'}",
            f"🔎 Шаг: {first.get('step') or 'не указан'}",
            f"Детали: {first.get('details') or 'без деталей'}",
            f"Страницы ({len(pages)}):",
        ]
        lines.extend(f"• {page}" for page in pages[:25])
        if len(pages) > 25:
            lines.append(f"• ... и еще {len(pages) - 25}")
        blocks.append("\n".join(lines))
        current[group_key] = {
            "domain": first.get("domain") or first.get("site"),
            "step": first.get("step"),
            "details": first.get("details"),
            "pages": pages,
            "last_seen_utc": datetime.now(timezone.utc).isoformat(),
        }

    for group_key in sorted(set(previous) - set(current)):
        item = previous[group_key]
        blocks.append(
            "\n".join(
                [
                    "✅ Ошибка устранена",
                    f"🌐 Домен: {item.get('domain') or 'unknown-site'}",
                    f"🔎 Шаг: {item.get('step') or 'не указан'}",
                ]
            )
        )

    state["scopes"][scope] = current
    save_alert_state(state)
    clear_alert_events()
    if not blocks:
        return "", False, "step"
    header = "🚨 Критические ошибки автотеста" if has_critical else "🚨 Ошибки автотеста"
    message = trim_message("\n\n".join([header, f"🕒 Время: {now_msk_text()}", *blocks]))
    return message, True, "critical" if has_critical else "step"


def now_msk_text() -> str:
    return datetime.now(MSK_TZ).strftime("%Y-%m-%d %H:%M (МСК)")


def detect_step(message: str, name: str) -> str:
    haystack = f"{message} {name}".lower()
    for title, token in STEP_PATTERNS:
        if token in haystack:
            return title
    return "Не выполнен шаг тест-кейса"


def normalize_site_label(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return SITE_HINT or "unknown-site"

    if not raw.startswith(("http://", "https://")):
        return raw.strip("/")

    parsed = urlsplit(raw)
    host = (parsed.netloc or "").strip().lower()
    if host:
        return host
    return raw.strip("/")


def parse_site_from_site_cfg(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"['\"]base_url['\"]\s*:\s*['\"]([^'\"]+)['\"]", value)
    if not match:
        return ""
    return normalize_site_label(match.group(1))


def parse_site_from_test_name(name: str) -> str:
    if not name:
        return ""
    match = re.search(r"https?://[^\s\]]+", name)
    if not match:
        return ""
    return normalize_site_label(match.group(0))


def extract_site_label(data: dict) -> str:
    for param in data.get("parameters") or []:
        if (param.get("name") or "").strip() == "site_cfg":
            parsed = parse_site_from_site_cfg(str(param.get("value") or ""))
            if parsed:
                return parsed

    parsed_from_name = parse_site_from_test_name(str(data.get("name") or ""))
    if parsed_from_name:
        return parsed_from_name

    return normalize_site_label(SITE_HINT or "unknown-site")


def extract_browser_name(data: dict) -> str:
    for param in data.get("parameters") or []:
        if (param.get("name") or "").strip() == "browser_name":
            return normalize_text(str(param.get("value") or "").strip("'\""), max_len=40)
    return ""


def collect_results(results_dir: Path) -> tuple[int, list[dict]]:
    passed = 0
    failed_records: list[dict] = []

    if not results_dir.exists():
        return 0, []

    for path in results_dir.glob("*-result.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        status = (data.get("status") or "").strip().lower()
        if status == "passed":
            passed += 1
            continue
        if status not in {"failed", "broken"}:
            continue

        details = data.get("statusDetails") or {}
        failed_records.append(
            {
                "site": extract_site_label(data),
                "name": normalize_text(data.get("name") or path.name, max_len=180),
                "message": normalize_text(details.get("message") or "без текста ошибки", max_len=240),
                "browser": extract_browser_name(data),
                "step": detect_step(
                    normalize_text(details.get("message") or "", max_len=500),
                    normalize_text(data.get("name") or "", max_len=500),
                ),
            }
        )

    return passed, failed_records


def group_failed_by_site(failed_records: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for record in failed_records:
        grouped.setdefault(record["site"], []).append(record)
    return grouped


def load_json_from_url(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "everyday-test-notify"})
    with urlopen(req, timeout=8) as resp:
        payload = resp.read().decode("utf-8")
    return json.loads(payload)


def load_previous_state() -> dict:
    default_state = {"failed_sites": [], "failed_signatures": []}
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "failed_sites": list(data.get("failed_sites") or []),
                    "failed_signatures": list(data.get("failed_signatures") or []),
                }
            return default_state
    except Exception:
        pass

    if not STATE_URL:
        return default_state

    try:
        data = load_json_from_url(STATE_URL)
        if isinstance(data, dict):
            return {
                "failed_sites": list(data.get("failed_sites") or []),
                "failed_signatures": list(data.get("failed_signatures") or []),
            }
        return default_state
    except Exception:
        return default_state


def save_current_state(failed_sites: set[str], failed_signatures: set[str]) -> None:
    payload = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "failed_sites": sorted(failed_sites),
        "failed_signatures": sorted(failed_signatures),
    }
    try:
        if STATE_FILE.parent:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_summary_state() -> dict:
    default_state = {"last_sent_slot": "", "runs": []}
    try:
        if SUMMARY_STATE_FILE.exists():
            data = json.loads(SUMMARY_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                runs = data.get("runs") or []
                return {
                    "last_sent_slot": str(data.get("last_sent_slot") or ""),
                    "runs": runs if isinstance(runs, list) else [],
                }
    except Exception:
        pass
    return default_state


def save_summary_state(last_sent_slot: str, runs: list[dict]) -> None:
    payload = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_sent_slot": last_sent_slot,
        "runs": runs,
    }
    try:
        if SUMMARY_STATE_FILE.parent:
            SUMMARY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY_STATE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def current_summary_slot(now: datetime | None = None) -> tuple[str, datetime]:
    current = now or datetime.now(MSK_TZ)
    candidates = [
        datetime(current.year, current.month, current.day, hour, tzinfo=MSK_TZ)
        for hour in SUMMARY_SEND_HOURS
    ]
    due = [item for item in candidates if item <= current]
    if not due:
        previous_day = current.date() - timedelta(days=1)
        slot = datetime(previous_day.year, previous_day.month, previous_day.day, 17, tzinfo=MSK_TZ)
    else:
        slot = max(due)
    return slot.strftime("%Y-%m-%d %H:%M"), slot


def build_period_summary(runs: list[dict], slot: str) -> str:
    total_passed = sum(int(run.get("passed") or 0) for run in runs)
    all_failures = [item for run in runs for item in (run.get("failed_records") or [])]
    grouped: dict[tuple[str, str], list[dict]] = {}
    for item in all_failures:
        key = (item.get("site") or "unknown-site", item.get("step") or "Не выполнен шаг тест-кейса")
        grouped.setdefault(key, []).append(item)

    first_time = runs[0].get("timestamp") if runs else ""
    lines = [
        f"Сводный отчет автотестов форм заявок за период {first_time} - {now_msk_text()}",
        "",
        f"Прогонов: {len(runs)}",
        f"Успешных проверок: {total_passed}",
        f"Ошибок: {len(all_failures)}",
    ]
    if all_failures:
        lines.extend(["", "Ошибки по сайтам и шагам:"])
        for (site, step), items in sorted(grouped.items(), key=lambda pair: len(pair[1]), reverse=True):
            sample = normalize_text(items[0].get("message") or "без деталей", max_len=180)
            lines.append(f"- {site} / {step}: {len(items)}")
            lines.append(f"  Пример: {sample}")
    else:
        lines.extend(["", "Ошибок за период не зафиксировано."])

    lines.extend(["", f"Отчет сформирован для окна {slot} по Москве."])
    if RUN_URL:
        lines.append(f"Run: {RUN_URL}")
    if ALLURE_URL:
        lines.append(f"Allure: {ALLURE_URL}")
    return trim_message("\n".join(lines).strip())


def build_twice_daily_summary(passed: int, failed_records: list[dict]) -> tuple[str, bool]:
    state = load_summary_state()
    runs = list(state.get("runs") or [])
    run_id = os.getenv("BUILD_TAG", "").strip() or RUN_URL or now_msk_text()
    if not any(str(run.get("run_id") or "") == run_id for run in runs):
        runs.append(
            {
                "run_id": run_id,
                "timestamp": now_msk_text(),
                "passed": passed,
                "failed_records": failed_records,
            }
        )

    slot, slot_time = current_summary_slot()
    should_send = ALERT_SUMMARY_ENABLED and slot != state.get("last_sent_slot") and datetime.now(MSK_TZ) >= slot_time
    if should_send:
        message = build_period_summary(runs, slot)
        save_summary_state(slot, [])
        return message, True

    save_summary_state(state.get("last_sent_slot") or "", runs)
    return "", False


def append_site_lines(lines: list[str], sites: list[tuple[str, list[dict]]]) -> None:
    for site, items in sites:
        count = len(items)
        browsers = sorted({item.get("browser") for item in items if item.get("browser")})
        browsers_text = f" | браузеры: {', '.join(browsers)}" if browsers else ""
        sample = normalize_text(items[0].get("message") or items[0].get("name") or "без деталей", max_len=180)
        lines.append(f"• {site} — {count} падений{browsers_text}")
        lines.append(f"  пример: {sample}")


def format_single_error_block(
    site: str,
    step: str,
    items: list[dict],
) -> str:
    sample = items[0]
    detail = normalize_text(sample.get("message") or sample.get("name") or "без деталей", max_len=220)
    return "\n".join(
        [
            f"🚨 Ошибка глобального автотеста формы [{DEFAULT_FORM_TITLE}]",
            f"🕒 Время: {now_msk_text()}",
            f"🌐 Лендинг: {site}",
            f"❌ Ошибка: {step}",
            f"🔎 Детали: {detail}",
        ]
    )


def format_aggregate_block(
    site: str,
    step: str,
    items: list[dict],
    total_failed: int,
) -> str:
    pct = round((len(items) / max(total_failed, 1)) * 100)
    return "\n".join(
        [
            f"🚨 Ошибка глобального автотеста формы [{DEFAULT_FORM_TITLE}]",
            f"🕒 Время: {now_msk_text()}",
            f"🌐 Лендинг: {site}",
            f"❌ Ошибка: {step}",
            f"📊 Масштаб: {len(items)} падений ({pct}%)",
        ]
    )


def group_failed_by_site_step(failed_records: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for record in failed_records:
        key = (record.get("site") or "unknown-site", record.get("step") or "Не выполнен шаг тест-кейса")
        grouped.setdefault(key, []).append(record)
    return grouped


def signature_for_site_step(site: str, step: str) -> str:
    return f"{site}||{step}"


def trim_message(message: str, max_len: int = MAX_MESSAGE_LEN) -> str:
    if len(message) <= max_len:
        return message
    return message[: max_len - 15].rstrip() + "\n... (обрезано)"


def build_summary(
    passed: int,
    failed_records: list[dict],
    resolved_sites: list[str],
    previous_failed_signatures: set[str],
) -> tuple[str, bool]:
    failed_total = len(failed_records)
    grouped_by_site = group_failed_by_site(failed_records)
    grouped_by_site_step = group_failed_by_site_step(failed_records)
    failed_sites_count = len(grouped_by_site)

    lines: list[str] = []
    has_any_category_output = False

    summary_enabled = ALERT_SUMMARY_ENABLED if NOTIFY_MODE != "daily" else ALERT_DAILY_SUMMARY_ENABLED
    if summary_enabled:
        has_any_category_output = True
        if failed_total == 0:
            lines.extend([f"✅ Глобальный автотест форм заявок завершён ({now_msk_text()})", ""])
        else:
            lines.extend([f"🚨 Глобальный автотест форм заявок завершён с ошибками ({now_msk_text()})", ""])
        if SITE_HINT:
            lines.append(f"Сайт (input): {SITE_HINT}")
            lines.append("")
        lines.append(f"🌐 Лендингов с ошибками: {failed_sites_count}")
        lines.append(f"✔️ Успешных: {passed}")
        lines.append(f"❌ Ошибок: {failed_total}")

    if failed_total > 0:
        sorted_site_steps = sorted(grouped_by_site_step.items(), key=lambda item: len(item[1]), reverse=True)
        regular_groups = [item for item in sorted_site_steps if len(item[1]) <= NORMAL_ALERT_MAX_PER_SITE]
        aggregate_groups = [item for item in sorted_site_steps if len(item[1]) > NORMAL_ALERT_MAX_PER_SITE]

        repeated_aggregate_groups: list[tuple[tuple[str, str], list[dict]]] = []
        first_seen_aggregate_groups: list[tuple[tuple[str, str], list[dict]]] = []
        for key, items in aggregate_groups:
            site, step = key
            signature = signature_for_site_step(site, step)
            if signature in previous_failed_signatures:
                repeated_aggregate_groups.append((key, items))
            else:
                first_seen_aggregate_groups.append((key, items))

        repeated_sites = {key[0] for key, _ in repeated_aggregate_groups}
        if ALERT_AGGREGATES_ENABLED and len(repeated_sites) > MASS_ALERT_SITE_THRESHOLD and summary_enabled:
            has_any_category_output = True
            lines.append("")
            lines.append(
                f"🚨 Массовая ошибка: {len(repeated_sites)} лендингов имеют повторяющиеся падения (всего {failed_total} ошибок)"
            )

        # Важно: накопительные алерты отправляем только со 2-го прогона подряд.
        # Первичную фиксацию крупных групп оставляем в обычных alert_errors.
        effective_regular_groups = regular_groups + first_seen_aggregate_groups

        if ALERT_ERRORS_ENABLED and effective_regular_groups:
            has_any_category_output = True
            for (site, step), items in effective_regular_groups[:8]:
                lines.append("")
                lines.append(format_single_error_block(site, step, items))

        if ALERT_AGGREGATES_ENABLED and repeated_aggregate_groups:
            has_any_category_output = True
            for (site, step), items in repeated_aggregate_groups[:8]:
                lines.append("")
                lines.append(format_aggregate_block(site, step, items, failed_total))

    if ALERT_RECOVERED_ENABLED and resolved_sites:
        has_any_category_output = True
        for site in resolved_sites[:10]:
            lines.append("")
            lines.extend(
                [
                    f"✅ Ошибка устранена: глобального автотеста формы [{DEFAULT_FORM_TITLE}]",
                    f"🕒 Время: {now_msk_text()}",
                    f"🌐 Лендинг: {site}",
                ]
            )
        if len(resolved_sites) > 10 and summary_enabled:
            lines.append("")
            lines.append(f"… и ещё восстановлений: {len(resolved_sites) - 10}")

    if has_any_category_output:
        lines.append("")
        if RUN_URL:
            lines.append(f"Run: {RUN_URL}")
        if ALLURE_URL:
            lines.append(f"Allure: {ALLURE_URL}")

    return trim_message("\n".join(lines).strip()), has_any_category_output


def main() -> int:
    passed, failed_records = collect_results(RESULTS_DIR)
    runtime_message, runtime_should_send, _runtime_alert_type = build_runtime_alert(load_alert_events())
    OUT_ALERT_FLAG_FILE.write_text("1" if runtime_should_send else "0", encoding="utf-8")
    OUT_ALERT_MESSAGE_FILE.write_text(runtime_message, encoding="utf-8")
    if runtime_message:
        print(runtime_message)
    if NOTIFY_MODE == "twice_daily":
        message, should_send = build_twice_daily_summary(passed, failed_records)
        OUT_FLAG_FILE.write_text("1" if should_send else "0", encoding="utf-8")
        OUT_MESSAGE_FILE.write_text(message, encoding="utf-8")
        if message:
            print(message)
        else:
            print("Summary accumulated; next report window is 09:00 or 17:00 MSK.")
        return 0

    current_failed_sites = {record["site"] for record in failed_records if record.get("site")}
    grouped_current = group_failed_by_site_step(failed_records)
    current_failed_signatures = {
        signature_for_site_step(site, step) for (site, step) in grouped_current.keys()
    }

    previous_state = load_previous_state()
    previous_failed_sites = set(previous_state.get("failed_sites") or [])
    previous_failed_signatures = set(previous_state.get("failed_signatures") or [])
    resolved_sites = sorted(previous_failed_sites - current_failed_sites)

    message, should_send = build_summary(
        passed,
        failed_records,
        resolved_sites,
        previous_failed_signatures=previous_failed_signatures,
    )
    save_current_state(current_failed_sites, current_failed_signatures)

    OUT_FLAG_FILE.write_text("1" if should_send else "0", encoding="utf-8")
    OUT_MESSAGE_FILE.write_text(message, encoding="utf-8")
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
