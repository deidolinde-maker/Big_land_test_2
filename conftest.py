import os
from pathlib import Path

import pytest
import allure
from config.form_expectations import available_form_suites

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
        default="legacy",
        choices=("legacy", "form-oriented"),
        help="Модель запуска: legacy (brand/suite) или form-oriented (одна primary форма).",
    )
    parser.addoption(
        "--primary-form",
        action="store",
        default=None,
        choices=("profit", "connection", "connection_cards", "checkaddress", "undecided", "moving", "express"),
        help="Основная форма для form-oriented режима.",
    )
    parser.addoption(
        "--url-brand",
        action="store",
        default=None,
        help=(
            "Бренд для запуска по внешнему списку URL из urls/<brand>.txt "
            "(например: mts, beeline, megafon, t2, rostelecom, domru, ttk)."
        ),
    )
    parser.addoption(
        "--form-suite",
        action="store",
        default="all",
        choices=available_form_suites(),
        help=(
            "Форма для прогона в URL-режиме: all, profit, connection, "
            "connection_cards, checkaddress, business, undecided, moving, express."
        ),
    )
    parser.addoption(
        "--url-shard-index",
        action="store",
        type=int,
        default=1,
        help=(
            "Номер шарда URL (начиная с 1) для --url-brand. "
            "Используется вместе с --url-shard-total."
        ),
    )
    parser.addoption(
        "--url-shard-total",
        action="store",
        type=int,
        default=1,
        help=(
            "Общее число шардов URL для --url-brand. "
            "При значении >1 список URL делится на части."
        ),
    )
    parser.addoption(
        "--provider",
        action="store",
        default=None,
        help="Имя провайдера из config/providers (например: mts, beeline, megafon, t2).",
    )
    parser.addoption(
        "--site",
        action="store",
        default=None,
        help="Домен сайта (site_id), например: mts-home-gpon.ru",
    )
    parser.addoption(
        "--service-mode",
        action="store",
        default="all",
        choices=("all", "core", "variants"),
        help="Режим submit по Place: all (все), core (базовый), variants (только варианты Place).",
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

