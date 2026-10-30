# Спецификация brand-oriented режима

## Запуск

Обязательные параметры:

```text
RUN_MODE=brand-oriented
BRAND_SCOPE=beeline|mega|mts|providerdom|rtk|t2|mts_gpon_ab|mts_home_online_ab
```

`PRIMARY_FORM` в этом режиме не используется. Form-oriented режим остаётся доступным для сравнения.

## URL-case

Каждый URL получает независимый Allure-result с атрибутами:

```text
brand_scope
url
scenario_type: standard | mts_ab
status
step
error_type
error_detail
```

Ошибка одного URL не останавливает дальнейший URL scope.

## Контекст

Для стандартных brand scope используется обычный изолированный context на URL.
Для `mts_gpon_ab` и `mts_home_online_ab` используется один context на весь запуск job. Новый page создаётся для каждого URL, но browser-level state домена сохраняется.

## Jobs

Основные jobs: Beeline, Mega, MTS, Providerdom, Ростелеком и T2.

Каждая job запускает собственный Python entrypoint из `scenarios/`. Общие
Playwright-примитивы и текущая форма-логика пока импортируются из core-модуля,
но scope и точка исполнения бренда отделены.

Отдельные AB jobs:

- `MTS GPON AB` — только `mts-home-gpon.ru`;
- `MTS Home Online AB` — только `mts-home-online.ru`.

Общие технические утилиты разрешены только для логирования, Allure, прокси и уведомлений. Locator flow и version logic AB-сценариев не смешиваются с другими брендами.

## Приёмка

- scope-файлы дают только согласованный сокращённый набор URL;
- brand job не запускает URL другого brand scope;
- AB job не запускает URL другого домена;
- AB URL проходят в одном browser context;
- локальная ошибка продолжает job;
- Allure и Telegram показывают brand scope, URL и тип сценария;
- старый режим продолжает запускаться без изменения параметров.
