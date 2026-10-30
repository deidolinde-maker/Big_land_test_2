from __future__ import annotations

import allure
import pytest

from config.brand_scope import AB_SCOPES
from config.url_loader import build_site_configs_from_brand_scope
from big_landing_code import run_site_scenario


def pytest_generate_tests(metafunc):
    if "ab_site_cfg" not in metafunc.fixturenames:
        return

    run_mode = str(metafunc.config.getoption("--run-mode", default="brand-oriented") or "brand-oriented").strip().lower()
    scope = str(metafunc.config.getoption("--brand-scope", default="") or "").strip().lower()
    if run_mode != "brand-oriented" or scope not in AB_SCOPES:
        raise pytest.UsageError(
            "MTS AB-сценарий запускается только с "
            "--run-mode=brand-oriented и --brand-scope=mts_gpon_ab|mts_home_online_ab."
        )

    configs = build_site_configs_from_brand_scope(scope=scope)
    metafunc.parametrize(
        "ab_site_cfg",
        list(configs.values()),
        ids=[f"{scope}:{cfg['base_url']}" for cfg in configs.values()],
    )


def test_mts_ab_site(
    page,
    ab_site_cfg: dict,
    browser_name: str,
    blocking_profile: str,
    execution_profile: str,
):
    scope = str(ab_site_cfg.get("_brand_scope") or "mts_ab")
    url = ab_site_cfg["base_url"]
    allure.dynamic.title(f"MTS AB: {scope} | {url}")
    allure.dynamic.label("suite", "MTS AB isolated scenarios")
    allure.dynamic.label("runMode", "brand-oriented")
    allure.dynamic.label("brandScope", scope)
    allure.dynamic.label("scenarioType", "mts_ab")
    allure.dynamic.parameter("brand_scope", scope)
    allure.dynamic.parameter("url", url)
    allure.dynamic.parameter("browser", browser_name)
    allure.dynamic.parameter("blocking_profile", blocking_profile)
    allure.dynamic.parameter("execution_profile", execution_profile)
    allure.dynamic.parameter("domain_session", "true")
    run_site_scenario(page, ab_site_cfg)
