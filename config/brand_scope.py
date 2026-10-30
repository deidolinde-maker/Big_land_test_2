from __future__ import annotations

from pathlib import Path


BRAND_SCOPE_FILES: dict[str, str] = {
    "beeline": "beeline.txt",
    "mega": "mega.txt",
    "mts": "mts.txt",
    "providerdom": "providerdom.txt",
    "rtk": "rtk.txt",
    "t2": "t2.txt",
    "mts_gpon_ab": "mts_gpon_ab.txt",
    "mts_home_online_ab": "mts_home_online_ab.txt",
}

BRAND_SCOPE_PROVIDERS: dict[str, str] = {
    "beeline": "beeline",
    "mega": "megafon",
    "mts": "mts",
    "providerdom": "domru",
    "rtk": "rostelecom",
    "t2": "t2",
    "mts_gpon_ab": "mts",
    "mts_home_online_ab": "mts",
}

AB_SCOPES = frozenset({"mts_gpon_ab", "mts_home_online_ab"})


def available_brand_scopes() -> list[str]:
    return sorted(BRAND_SCOPE_FILES)


def is_ab_scope(scope: str) -> bool:
    return (scope or "").strip().lower() in AB_SCOPES


def scope_provider(scope: str) -> str:
    key = (scope or "").strip().lower()
    try:
        return BRAND_SCOPE_PROVIDERS[key]
    except KeyError as exc:
        raise ValueError(
            f"Неизвестный BRAND_SCOPE={scope!r}. Доступно: {', '.join(available_brand_scopes())}"
        ) from exc


def load_brand_scope_urls(scope: str, *, urls_dir: str | Path | None = None) -> list[str]:
    key = (scope or "").strip().lower()
    if key not in BRAND_SCOPE_FILES:
        raise ValueError(
            f"Неизвестный BRAND_SCOPE={scope!r}. Доступно: {', '.join(available_brand_scopes())}"
        )
    root = Path(urls_dir or (Path(__file__).resolve().parent.parent / "urls" / "brand_scopes"))
    path = root / BRAND_SCOPE_FILES[key]
    if not path.exists():
        raise ValueError(f"Файл brand scope не найден: {path}")

    urls: list[str] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.lstrip("\ufeff").strip()
        if not line or line.startswith("#"):
            continue
        if line not in seen:
            seen.add(line)
            urls.append(line)
    if not urls:
        raise ValueError(f"Файл brand scope пустой: {path}")
    return urls
