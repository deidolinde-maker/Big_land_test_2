import os
import json
import re
from pathlib import Path

import pytest
import allure
from config.brand_scope import available_brand_scopes, is_ab_scope

ADBLOCK_MVP_BLOCKLIST = (
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adservice.google.com",
    "yandex.ru/ads",
    "an.yandex.ru",
    "mc.yandex.ru",
    "top.mail.ru",
    "adriver.ru",
    "adfox",
    "advert",
    "banner",
)

EXECUTION_PROFILE_ALLOWED_BROWSERS = {
    "desktop": {"chromium", "firefox", "webkit"},
    "mobile-chromium": {"chromium"},
    "mobile-webkit": {"webkit"},
}

EXECUTION_PROFILE_DEVICE_PRESET = {
    "mobile-chromium": "Pixel 5",
    "mobile-webkit": "iPhone 12",
}


def pytest_addoption(parser):
    parser.addoption(
        "--run-mode",
        action="store",
        default="brand-oriented",
        choices=("brand-oriented",),
        help="Единственная модель запуска: brand-oriented.",
    )
    parser.addoption(
        "--brand-scope",
        action="store",
        default=None,
        choices=available_brand_scopes(),
        help="Сокращённый brand/AB scope для brand-oriented режима.",
    )
    parser.addoption(
        "--service-mode",
        action="store",
        default="all",
        choices=("all", "core"),
        help="Режим submit по Place: all (все варианты в одном URL) или core (базовый вариант).",
    )
    parser.addoption(
        "--blocking-profile",
        action="store",
        default="none",
        choices=("none", "adblock-mvp"),
        help="Профиль блокировщиков: none (по умолчанию) или adblock-mvp.",
    )
    parser.addoption(
        "--execution-profile",
        action="store",
        default="desktop",
        choices=("desktop", "mobile-chromium", "mobile-webkit"),
        help=(
            "Профиль исполнения: desktop (по умолчанию), "
            "mobile-chromium или mobile-webkit (эмуляция мобильного браузера)."
        ),
    )


def _normalize_browser_option(browser_opt) -> list[str]:
    if browser_opt is None:
        return []
    if isinstance(browser_opt, (list, tuple)):
        return [str(x).strip().lower() for x in browser_opt if str(x).strip()]
    value = str(browser_opt).strip().lower()
    return [value] if value else []


def _should_block_request(url: str, resource_type: str) -> bool:
    current_url = (url or "").lower()
    current_type = (resource_type or "").lower()

    if not current_url:
        return False

    # MVP: блокируем рекламные/трекерные домены и часть тяжёлых рекламных ресурсов.
    if any(marker in current_url for marker in ADBLOCK_MVP_BLOCKLIST):
        return True
    if current_type in {"media", "object"} and "ad" in current_url:
        return True
    return False


@pytest.fixture
def blocking_profile(pytestconfig):
    return pytestconfig.getoption("--blocking-profile", default="none")


@pytest.fixture(scope="session")
def execution_profile(pytestconfig):
    return pytestconfig.getoption("--execution-profile", default="desktop")


@pytest.fixture(scope="session", autouse=True)
def expose_execution_profile_to_process_env(execution_profile):
    """
    Экспортируем execution profile в env, чтобы runtime-логика теста
    могла строго разделять desktop/mobile поведение.
    """
    os.environ["PYTEST_EXECUTION_PROFILE"] = execution_profile


@pytest.fixture(scope="session", autouse=True)
def validate_execution_profile(pytestconfig):
    profile = pytestconfig.getoption("--execution-profile", default="desktop")
    browsers = _normalize_browser_option(pytestconfig.getoption("--browser", default=None))
    allowed = EXECUTION_PROFILE_ALLOWED_BROWSERS.get(profile, set())

    if browsers and any(b not in allowed for b in browsers):
        allowed_list = ", ".join(sorted(allowed)) if allowed else "<none>"
        actual_list = ", ".join(browsers)
        raise pytest.UsageError(
            f"--execution-profile={profile} поддерживает только --browser: {allowed_list}. "
            f"Получено: {actual_list}."
        )


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, playwright, execution_profile):
    device_preset_name = EXECUTION_PROFILE_DEVICE_PRESET.get(execution_profile)

    merged_args = dict(browser_context_args)
    if device_preset_name:
        device_preset = playwright.devices[device_preset_name]
        merged_args.update(device_preset)

    # Включаем запись видео для каждого теста: при падении прикрепляем в Allure.
    # Путь можно переопределить через env PW_VIDEO_DIR.
    video_dir = Path(os.getenv("PW_VIDEO_DIR", "artifacts/videos")).resolve()
    video_dir.mkdir(parents=True, exist_ok=True)
    merged_args["record_video_dir"] = str(video_dir)

    if "record_video_size" not in merged_args:
        merged_args["record_video_size"] = {"width": 1280, "height": 720}

    return merged_args


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Use an optional authenticated proxy for all Playwright browser launches."""
    raw_proxy = (os.getenv("BROWSER_PROXY") or "").strip()
    if not raw_proxy:
        return browser_type_launch_args

    parts = raw_proxy.rsplit(":", 2)
    if len(parts) == 3 and all(parts):
        server, username, password = parts
        proxy = {
            "server": f"http://{server}",
            "username": username,
            "password": password,
        }
    else:
        proxy = {"server": raw_proxy if "://" in raw_proxy else f"http://{raw_proxy}"}

    merged_args = dict(browser_type_launch_args)
    merged_args["proxy"] = proxy
    print(f"[PLAYWRIGHT] Browser proxy enabled: {proxy['server']}")
    return merged_args


@pytest.fixture(scope="session")
def brand_context(browser, browser_context_args):
    """One browser context for a brand job; reused by every URL in the job."""
    context = browser.new_context(**browser_context_args)
    yield context
    context.close()


@pytest.fixture
def page(request):
    """Use one context per URL by default, or one context per brand job."""
    run_mode = str(request.config.getoption("--run-mode", default="brand-oriented") or "brand-oriented").strip().lower()
    brand_scope = str(request.config.getoption("--brand-scope", default="") or "").strip().lower()
    use_domain_session = run_mode == "brand-oriented" and is_ab_scope(brand_scope)
    context = request.getfixturevalue("brand_context" if use_domain_session else "context")
    current_page = context.new_page()

    def capture_mts_site_version(message):
        """Capture MTS site_version emitted by Yandex debug console payloads."""
        try:
            text = message.text or ""
        except Exception:
            return

        patterns = (
            r"[\"']site_version[\"']\s*:\s*[\"']([^\"']+)[\"']",
            r"\bsite_version\b\s*[:=]\s*[\"']?([A-Za-z0-9_.-]+)",
        )
        version = None
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                version = match.group(1).strip()
                break

        def find_version(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if str(key).strip().lower() == "site_version":
                        return str(item).strip() if item is not None else None
                    nested = find_version(item)
                    if nested:
                        return nested
            elif isinstance(value, (list, tuple)):
                for item in value:
                    nested = find_version(item)
                    if nested:
                        return nested
            elif isinstance(value, str) and "site_version" in value.lower():
                try:
                    return find_version(json.loads(value))
                except Exception:
                    match = re.search(
                        r"[\"']site_version[\"']\s*:\s*[\"']([^\"']+)[\"']",
                        value,
                        flags=re.IGNORECASE,
                    )
                    return match.group(1).strip() if match else None
            return None

        if not version:
            try:
                for arg in message.args:
                    version = find_version(arg.json_value())
                    if version:
                        break
            except Exception:
                pass

        if version:
            previous = getattr(current_page, "_mts_console_site_version", None)
            current_page._mts_console_site_version = version
            if previous != version:
                print(f"  [VERSION] Console site_version: {version}")

    current_page.on("console", capture_mts_site_version)
    yield current_page
    current_page.close()


@pytest.fixture(autouse=True)
def apply_blocking_profile(page, blocking_profile):
    if blocking_profile != "adblock-mvp":
        return

    def _route_handler(route, request):
        try:
            if _should_block_request(request.url, request.resource_type):
                route.abort()
                return
        except Exception:
            pass
        route.continue_()

    page.route("**/*", _route_handler)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    После каждого теста:
    - если упал шаг call: делаем скриншот;
    - на teardown (после закрытия контекста): прикрепляем video.webm в Allure.
    """
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)

    if report.when == "call":
        page = item.funcargs.get("page")
        if page is not None:
            # Сохраняем video-объект всегда: на teardown прикрепим только при падении,
            # а для успешных тестов удалим файл, чтобы не раздувать workspace.
            try:
                item._page_video = page.video
            except Exception:
                item._page_video = None

        if report.failed and page is not None:
            try:
                screenshot = page.screenshot(full_page=True)
                allure.attach(
                    screenshot,
                    name="screenshot_on_failure",
                    attachment_type=allure.attachment_type.PNG,
                )
            except Exception as e:
                print(f"[SCREENSHOT] Не удалось сделать скриншот: {e}")

    if report.when == "teardown":
        rep_call = getattr(item, "rep_call", None)
        video_obj = getattr(item, "_page_video", None)
        if video_obj is None:
            return
        try:
            video_path = Path(video_obj.path())
        except Exception:
            return

        if rep_call and rep_call.failed:
            try:
                if video_path.exists() and video_path.stat().st_size > 0:
                    allure.attach.file(
                        str(video_path),
                        name="video_on_failure",
                        attachment_type=allure.attachment_type.WEBM,
                    )
                    print(f"[VIDEO] Attached: {video_path}")
                else:
                    print(f"[VIDEO] Файл видео отсутствует или пустой: {video_path}")
            except Exception as e:
                print(f"[VIDEO] Не удалось прикрепить видео: {e}")
        else:
            # Успешные/пропущенные тесты не должны копить webm.
            try:
                if video_path.exists():
                    video_path.unlink()
                    print(f"[VIDEO] Removed on success: {video_path}")
            except Exception as e:
                print(f"[VIDEO] Не удалось удалить видео успешного теста: {e}")

