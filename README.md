# Big_land_test_2

Автотесты заявочных форм и попапов на лендингах провайдеров с запуском в Jenkins и отчетами Allure.

## Что делает проект

Проект проверяет, что на URL из брендовых списков:

- форма или попап открываются;
- поля заполняются (улица, дом, телефон, опционально имя);
- submit выполняется;
- есть строгое подтверждение отправки (`thanks`, `thank_you`, `submitted`).

Если подтверждения нет, тест считает кейс ошибкой.

## Основные компоненты новой модели

- `scenarios/<scope>.py` - самостоятельный исполняемый сценарий конкретного бренда или MTS AB.
- `urls/brand_scopes/*.txt` - фиксированные URL каждого scope.
- `Jenkinsfile.<scope>` - отдельная job для каждого scope.
- `conftest.py` - CLI-параметры pytest, execution profiles, видео/скриншоты.
- `config/url_loader.py` и `config/brand_scope.py` - сбор конфигурации только выбранного scope.
- `notification_transport.py` - независимая отправка Telegram через proxy endpoint или Bot API.
- `notify_from_allure.py` - формирование summary из `allure-results` для Telegram.
- `jenkins/brand_pipeline.groovy` - общий технический pipeline без брендовой логики.

## Логика сценария

Каждый `scenarios/<scope>.py` параметризует один тест-кейс на один URL своего scope.
Порядок проверки:

1. Шаг 1: `checkaddress` (если ожидается для URL).
2. Шаг 2: попапы главной страницы.
3. Шаг 3: попапы `/business` (если ожидается).
4. Шаги 4/4a/4b: городские шаги (если включены для URL/режима).

В URL-режиме ожидаемые формы определяются не только провайдерным базовым конфигом, но и правилом suite/allowlist.

## Критерий успеха заявки

Критерий строгий:

- после submit должен быть подтверждающий URL (`.../thanks`, `.../thank_you`, `.../submitted`);
- если подтверждения нет, кейс падает;
- техалерты/шаговые алерты не меняют итоговый критерий успеха.

## Активный запуск

Пример локального запуска одного scope:

```text
pytest scenarios/beeline.py --run-mode=brand-oriented --brand-scope=beeline --alluredir=allure-results
```

Активная модель не использует `PRIMARY_FORM`, `--url-brand`, `--form-suite`,
`--provider`, `--site` и старый общий Jenkinsfile.

Исторические form-suite материалы ниже сохранены только для справки.

- `profit`
- `connection`
- `connection_cards`
- `checkaddress`
- `business`
- `undecided`
- `moving`
- `express`
- `all` (все suite по очереди)

## Локальный запуск

### Экспериментальный form-oriented режим

Для сравнения с legacy-моделью отдельная копия проекта поддерживает запуск
одной основной формы на общем URL-скоупе всех активных брендов. Остальные
ожидаемые формы проходят только presence-check без submit:

```bash
.venv/bin/python -m pytest big_landing_code.py \
  --run-mode=form-oriented \
  --primary-form=profit \
  --form-suite=all \
  --service-mode=core \
  --browser=chromium \
  --alluredir=allure-results-form-oriented \
  --timeout=600 -s
```

Основной legacy-запуск не изменен. Для следующего form-job меняется только
`--primary-form`: `connection`, `checkaddress` или `undecided`.

### Требования

- Python 3.10+
- зависимости из `requirements.txt`
- Playwright browsers

### Установка

```bash
python -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Для Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
```

### Примеры запуска

MTS, suite `checkaddress`, shard 1/2:

```bash
.venv/bin/python -m pytest big_landing_code.py \
  --url-brand=mts \
  --form-suite=checkaddress \
  --url-shard-index=1 \
  --url-shard-total=2 \
  --service-mode=core \
  --browser=chromium \
  --blocking-profile=none \
  --alluredir=allure-results \
  --timeout=600 -s
```

Мобильный профиль Chromium:

```bash
.venv/bin/python -m pytest big_landing_code.py \
  --url-brand=beeline \
  --form-suite=connection \
  --service-mode=core \
  --browser=chromium \
  --execution-profile=mobile-chromium \
  --blocking-profile=none \
  --alluredir=allure-results \
  --timeout=600 -s
```

## Параметры pytest

CLI-параметры определены в `conftest.py`:

- `--url-brand` - бренд (`mts`, `beeline`, `megafon`, `t2`, `rostelecom`, `domru`, `ttk`).
- `--form-suite` - suite формы (`all`, `profit`, `connection`, ...).
- `--url-shard-index` - индекс шарда, начиная с 1.
- `--url-shard-total` - количество шардов.
- `--service-mode` - `core`, `variants`, `all`.
- `--blocking-profile` - `none` или `adblock-mvp`.
- `--execution-profile` - `desktop`, `mobile-chromium`, `mobile-webkit`.
- стандартные параметры `pytest-playwright`, включая `--browser`.

Ограничения профилей:

- `mobile-chromium` разрешает только `--browser=chromium`.
- `mobile-webkit` разрешает только `--browser=webkit`.

## Логи, видео и артефакты

- Видео пишется в `PW_VIDEO_DIR` (по умолчанию `artifacts/videos`).
- На успешных тестах видео удаляется автоматически.
- На падениях видео прикладывается в Allure.
- Скриншот на падении прикладывается в Allure.

## Jenkins: назначение и схема

`Jenkinsfile` реализует:

- подготовку Python/Playwright с кешами;
- прогон matrix по брендам, suite, браузерам и профилям;
- URL pre-check, чтобы пропускать пустые suite без падения;
- сбор Allure и публикацию;
- Telegram summary;
- авто-цепочку джоб;
- периодическую чистку архивов.

## Jenkins: обязательные credentials

Если `USE_TELEGRAM_PROXY=true`, нужны credentials типа Secret Text:

- `telegram_proxy_url`
- `telegram_proxy_auth_secret`
- `tg_proxy_creds_survarius`
- `browser_proxy_creds`

## Jenkins: параметры job

Ключевые параметры:

- `PRIMARY_FORM` - основная форма job: `profit`, `connection`, `checkaddress`, `undecided`, `moving` или `express`.
- `SERVICE_MODE` - `core`, `variants`, `all`.
- браузерные флаги:
  - `RUN_CHROMIUM`
  - `RUN_FIREFOX`
  - `RUN_WEBKIT`
  - `RUN_MOBILE_CHROMIUM`
  - `RUN_MOBILE_WEBKIT`
- `BLOCKING_PROFILE` - `none`/`adblock-mvp`.
- алерт-флаги:
  - `ALERT_ERRORS`
  - `ALERT_AGGREGATES`
  - `ALERT_SUMMARY`
  - `ALERT_RECOVERED`
- цепочка:
  - `ENABLE_CONTINUOUS_LOOP`
  - `LOOP_DELAY_SECONDS`
  - `CHAIN_NEXT_JOB`
  - `CHAIN_NEXT_FORM` (необязательно; по умолчанию форма выбирается автоматически)
- чистка артефактов:
  - `ENABLE_PERIODIC_ARTIFACT_PURGE`
  - `PERIODIC_PURGE_EVERY`

Внутри pipeline общий URL-скоуп всех активных брендов и режим
`form-oriented` зафиксированы. Они больше не выбираются вручную в Jenkins.

## Jenkins: почему Allure может быть 0 и что сделано

Раньше `collected 0 items / 1 error` мог ломать job при пустом suite (нет URL после фильтра).

Сейчас поведение такое:

- перед `run_one` делается pre-check `suite_has_urls(...)`;
- если URL нет, suite логируется как `SKIP`, pytest не запускается;
- если в job вообще не было запусков (`ran_suites == 0`), добавляется synthetic skipped test-case в `allure-results`, чтобы Allure не был пустым.

## Jenkins: политика архивации и чистки

- Артефакты всегда архивируются:
  - `allure-results/**`
  - `allure-results-*/**`
  - `telegram_message.txt`
  - `telegram_should_send.txt`
  - `notify_state.json`
- Видео (`artifacts/videos/**`) архивируются только при `FAILURE`.
- По завершению workspace чистится от временных данных:
  - `artifacts/videos`, `allure-results-*`, `.pytest_cache`, `pytest-cache-files-*`, `__pycache__`.

Периодическая чистка архивов Jenkins:

- если `ENABLE_PERIODIC_ARTIFACT_PURGE=true`,
- каждый `PERIODIC_PURGE_EVERY`-й билд удаляет архивы и `allure-report` у прошлых билдов текущей job.

## Jenkins: как настроить авто-цепочку

Для form-oriented цепочки:

- включить `ENABLE_CONTINUOUS_LOOP=true`;
- указать `CHAIN_NEXT_JOB` на следующую form-job;
- оставить `CHAIN_NEXT_FORM` пустым, чтобы форма выбралась автоматически:
  - `profit -> connection`
  - `connection -> checkaddress`
  - `checkaddress -> undecided`
  - `undecided -> profit`

Для ручного переопределения:

- задайте `CHAIN_NEXT_JOB` и/или `CHAIN_NEXT_FORM`.

## Jenkins: как отключить автозапуски

Способы:

- снять `Enable` у нужной job в Jenkins UI;
- запускать job вручную с `ENABLE_CONTINUOUS_LOOP=false`;
- отключить upstream/downstream триггеры для цепочки, если они настроены отдельно.

## Troubleshooting

### 1) Шаговый alert есть, а Allure зеленый

Это возможно, если на одном шаге была ошибка, но по сайту в этом же тест-кейсе есть успешный submit и логика подавления step-fail включена для шага/режима.

Проверяйте:

- `statusDetails` в `allure-results/*-result.json`;
- консольный лог по конкретному URL;
- Telegram `step` и `summary` отдельно.

### 2) `подтверждение отправки не получено`

Частые причины:

- не зафиксировался саджест дома/улицы;
- CF7 вернул `validation_failed`;
- submit ушел, но редирект/thank-you не пришел.

Проверяйте в логе:

- `CF7 feedback status`
- `New XHR/fetch after submit`
- фактический URL после submit

### 3) В form-oriented job нет URL

Проверьте, что выбранная `PRIMARY_FORM` присутствует в активном allowlist.

Проверьте:

- `urls/*.txt`
- `config/form_allowlists/<primary_form>.txt`
- override-правила в `config/form_expectations/*.json`

## Практика обновления URL/ожиданий

При изменениях ленда:

1. Обновить URL в `urls/<brand>.txt`.
2. Обновить allowlist suite в `config/form_allowlists/*.txt`.
3. При необходимости добавить/исправить override в `config/form_expectations/<brand>.json`.
4. Прогнать локально `--run-mode=form-oriented --primary-form=<form>`.
5. Запустить соответствующую form-job и проверить Allure + Telegram.

## Рекомендуемый минимальный smoke перед пушем

```bash
.venv/bin/python -m pytest big_landing_code.py \
  --url-brand=mts \
  --form-suite=checkaddress \
  --url-shard-index=1 --url-shard-total=2 \
  --service-mode=core \
  --browser=chromium \
  --blocking-profile=none \
  --alluredir=allure-results \
  --timeout=600 -s
```

