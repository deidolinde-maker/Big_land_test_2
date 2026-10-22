from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from config.form_expectations import (
    FORM_SUITE_TO_FORM_TYPE,
    build_expected_form_types,
    canonicalize_url,
    expected_form_types_for_suite,
    expects_connection_cards_for_suite,
    expects_connection_card_trigger,
    filter_urls_for_form_suite,
    is_url_in_form_suite,
    normalize_form_suite,
    optional_expected_form_types,
    load_brand_form_overrides,
)
from config.loader import available_providers, load_site_configs
from config.schema import derive_site_id

URL_FILE_BY_BRAND: dict[str, str] = {
    "mts": "mts.txt",
    "beeline": "beeline.txt",
    "megafon": "megafon.txt",
    "t2": "t2.txt",
    "rostelecom": "rostelecom.txt",
    "domru": "domru.txt",
    "ttk": "ttk.txt",
}


def available_url_brands() -> list[str]:
    return sorted(URL_FILE_BY_BRAND.keys())


def _resolve_urls_dir(urls_dir: str | Path | None = None) -> Path:
    if urls_dir is not None:
        return Path(urls_dir).resolve()
    return (Path(__file__).resolve().parent.parent / "urls").resolve()


def _normalize_url(raw: str) -> str | None:
    line = (raw or "").lstrip("\ufeff").strip()
    if not line or line.startswith("#"):
        return None

    parsed = urlsplit(line)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Некорректный URL в файле: {line!r}")
    return canonicalize_url(line)


def load_urls_for_brand(brand: str, *, urls_dir: str | Path | None = None) -> list[str]:
    brand_key = (brand or "").strip().lower()
    if brand_key not in URL_FILE_BY_BRAND:
        raise ValueError(
            f"Неизвестный бренд {brand!r}. Доступно: {', '.join(available_url_brands())}"
        )

    root = _resolve_urls_dir(urls_dir)
    file_name = URL_FILE_BY_BRAND[brand_key]
    file_path = root / file_name
    if not file_path.exists():
        raise ValueError(f"Файл URL не найден: {file_path}")

    urls: list[str] = []
    seen: set[str] = set()
    for raw in file_path.read_text(encoding="utf-8").splitlines():
        normalized = _normalize_url(raw)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)

    if not urls:
        raise ValueError(f"Файл URL пустой после фильтрации комментариев: {file_path}")

    return urls


def build_site_configs_from_urls(
    *,
    brand: str,
    urls_dir: str | Path | None = None,
    form_suite: str | None = None,
    url_shard_index: int = 1,
    url_shard_total: int = 1,
) -> dict[str, dict]:
    """
    Строит runtime-конфиг для прямого обхода URL.

    Источник полей поведения формы (has_checkaddress/has_business/...) берётся
    из provider-конфига по домену, а base_url заменяется на конкретный URL
    страницы из urls/<brand>.txt.
    """
    brand_key = (brand or "").strip().lower()
    if brand_key not in available_providers():
        raise ValueError(
            f"Бренд {brand!r} отсутствует в provider-конфигах. "
            f"Доступно: {', '.join(available_providers())}"
        )

    suite = normalize_form_suite(form_suite)
    source_urls = load_urls_for_brand(brand_key, urls_dir=urls_dir)
    source_urls = filter_urls_for_form_suite(source_urls, suite)
    if url_shard_total > 1:
        total = len(source_urls)
        start = (total * (url_shard_index - 1)) // url_shard_total
        end = (total * url_shard_index) // url_shard_total
        source_urls = source_urls[start:end]
    if not source_urls:
        raise ValueError(
            f"Для бренда {brand_key!r} и form_suite={suite!r} не найдено URL. "
            f"Проверьте urls/{URL_FILE_BY_BRAND[brand_key]} и allowlist формы. "
            f"(shard {url_shard_index}/{url_shard_total})"
        )
    provider_sites = load_site_configs(provider=brand_key)
    form_overrides = load_brand_form_overrides(brand_key)

    by_host: dict[str, dict] = {}
    for _, cfg in provider_sites.items():
        host_id = derive_site_id(cfg["base_url"])
        by_host[host_id] = cfg

    def _resolve_source_cfg(host: str) -> dict | None:
        exact = by_host.get(host)
        if exact is not None:
            return exact

        candidates: list[tuple[int, dict]] = []
        for base_host, candidate_cfg in by_host.items():
            if host.endswith("." + base_host) or base_host.endswith("." + host):
                candidates.append((len(base_host), candidate_cfg))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    built: dict[str, dict] = {}
    for page_url in source_urls:
        host_id = derive_site_id(page_url)
        source_cfg = _resolve_source_cfg(host_id)
        if source_cfg is None:
            raise ValueError(
                f"Для URL {page_url!r} не найден провайдерный базовый конфиг по домену {host_id!r}."
            )

        cfg_copy = dict(source_cfg)
        cfg_copy["base_url"] = page_url
        cfg_copy["_provider"] = brand_key
        cfg_copy["_site_id"] = host_id
        cfg_copy["_source_mode"] = "url_file"
        cfg_copy["_requested_form_suite"] = suite
        cfg_copy["_expected_form_types"] = build_expected_form_types(
            page_url=page_url,
            site_cfg=cfg_copy,
            override_rules=form_overrides,
        )
        cfg_copy["_optional_expected_form_types"] = optional_expected_form_types(page_url)
        cfg_copy["_expect_connection_cards"] = expects_connection_card_trigger(page_url)

        suite_expected_form_types = expected_form_types_for_suite(suite)
        if suite_expected_form_types:
            cfg_copy["_expected_form_types"] = suite_expected_form_types
            cfg_copy["_expect_connection_cards"] = expects_connection_cards_for_suite(suite)

        built[page_url] = cfg_copy

    return built


def build_site_configs_from_all_urls(
    *,
    primary_form: str,
    urls_dir: str | Path | None = None,
    url_shard_index: int = 1,
    url_shard_total: int = 1,
) -> dict[str, dict]:
    """Build one stable, cross-brand URL scope for form-oriented runs.

    Unlike ``build_site_configs_from_urls`` this keeps the full expected-form
    metadata for every URL. ``primary_form`` only selects URLs for the current
    full functional check.
    """
    suite = normalize_form_suite(primary_form)
    if suite == "all":
        raise ValueError("form-oriented mode requires a concrete primary form")

    built: dict[str, dict] = {}
    url_to_key: dict[str, str] = {}
    for brand in available_url_brands():
        try:
            brand_configs = build_site_configs_from_urls(
                brand=brand,
                urls_dir=urls_dir,
                form_suite="all",
                url_shard_index=1,
                url_shard_total=1,
            )
        except ValueError as exc:
            if "не найдено URL" in str(exc):
                continue
            raise

        for page_url, cfg in brand_configs.items():
            if not is_url_in_form_suite(page_url, suite):
                continue

            existing_key = url_to_key.get(page_url)
            if existing_key is not None:
                brands = list(cfg.get("_scope_brands") or [])
                for existing_brand in built[existing_key].get("_scope_brands") or []:
                    if existing_brand not in brands:
                        brands.append(existing_brand)
                if brand not in brands:
                    brands.append(brand)
                built[existing_key]["_scope_brands"] = sorted(set(brands))
                continue

            cfg_copy = dict(cfg)
            cfg_copy["_scope_brand"] = brand
            cfg_copy["_scope_brands"] = [brand]
            cfg_copy["_requested_form_suite"] = suite
            cfg_copy["_primary_form"] = FORM_SUITE_TO_FORM_TYPE[suite]
            key = f"{brand}:{page_url}"
            url_to_key[page_url] = key
            built[key] = cfg_copy

    items = list(built.items())
    items.sort(key=lambda item: (item[1].get("base_url", ""), item[0]))
    if url_shard_total > 1:
        total = len(items)
        start = (total * (url_shard_index - 1)) // url_shard_total
        end = (total * url_shard_index) // url_shard_total
        items = items[start:end]
    if not items:
        raise ValueError(
            f"Для form-oriented primary_form={suite!r} не найдено активных URL."
        )
    return dict(items)
