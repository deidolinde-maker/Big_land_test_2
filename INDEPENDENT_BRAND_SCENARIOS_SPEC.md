# Спецификация независимых брендовых сценариев

## 1. Цель

Полностью убрать зависимость новой разработки от большого `big_landing_code.py`.
Каждый бренд и каждый MTS AB-сценарий получают самостоятельный исполняемый Python-файл.

Целевые entrypoint-файлы:

```text
scenarios/beeline.py
scenarios/mega.py
scenarios/mts.py
scenarios/providerdom.py
scenarios/rtk.py
scenarios/t2.py
scenarios/mts_gpon_ab.py
scenarios/mts_home_online_ab.py
```

Допускается дублирование кода между файлами. Приоритеты новой архитектуры:

1. предсказуемость поведения конкретного бренда;
2. простота диагностики;
3. отсутствие случайного подхвата чужих локаторов;
4. независимость AB-сценариев;
5. только после этого — устранение дублирования.

## 2. Что остаётся общим

Общими могут оставаться только данные и нейтральные технические компоненты:

- provider-конфиги;
- URL-scope-файлы;
- тестовые значения;
- proxy/browser settings;
- Allure attachments;
- Telegram notification transport;
- общие типы ошибок и служебные функции, если они не содержат брендовой логики.

Вызов `big_landing_code.py` из Jenkins и брендовых сценариев запрещается.
Брендовый сценарий не должен импортировать другой брендовый сценарий.

## 3. Целевая структура

```text
scenarios/
  beeline.py
  mega.py
  mts.py
  providerdom.py
  rtk.py
  t2.py
  mts_gpon_ab.py
  mts_home_online_ab.py

config/
urls/brand_scopes/
jenkins/brand_pipeline.groovy
Jenkinsfile.<scope>
```

После завершения миграции:

- `big_landing_code.py` удаляется;
- `mts_ab_tests/test_mts_ab.py` либо удаляется, либо становится архивным и не участвует в Jenkins;
- старые form-oriented документы и entrypoints не участвуют в запуске новой модели.

## 4. Контракт каждого сценария

Каждый файл обязан:

1. иметь фиксированный `SCOPE`;
2. загружать только свой URL-scope;
3. параметризовать один тест-кейс на один URL;
4. выполнять только свою последовательность шагов;
5. формировать Allure-параметры `brand_scope`, `url`, `scenario_type`;
6. продолжать прогон после ошибки одного URL;
7. завершать job с failure после обработки всего списка, если есть ошибки.

Минимальный контракт сценария:

```python
SCOPE = "beeline"

def pytest_generate_tests(metafunc):
    ...

def test_beeline(...):
    ...
```

## 5. Особые MTS AB-сценарии

### 5.1. GPON

Файл: `scenarios/mts_gpon_ab.py`.

URL:

```text
https://mts-home-gpon.ru/
https://mts-home-gpon.ru/moskva
https://mts-home-gpon.ru/sankt-peterburg
https://mts-home-gpon.ru/samara
```

Сценарий использует логику `Everyday_test` для:

- определения версии;
- выбора version-specific локаторов;
- регионального popup;
- street/house suggestions;
- retry disabled house field;
- submit и success-маркера.

### 5.2. Home Online

Файл: `scenarios/mts_home_online_ab.py`.

URL:

```text
https://mts-home-online.ru/
https://mts-home-online.ru/moskva
https://mts-home-online.ru/sankt-peterburg
https://mts-home-online.ru/voronezh
```

Сценарий изолирован от GPON, использует собственные version rules и локаторы AB-вариантов.

### 5.3. Session

Каждый MTS AB-сценарий использует один browser context на весь доменный scope.
URL проходят последовательно в одной сессии. Сохраняются cookies, localStorage,
AB-marker и version state. Перед новым URL сбрасываются page-level popup и введённые поля.

## 6. Этапы реализации

### Этап 0. Фиксация baseline

- Зафиксировать текущий commit новой brand-oriented модели.
- Сохранить список scope и ожидаемое число URL.
- Зафиксировать текущие Jenkinsfile и уведомления.
- Записать ограничения: локальный полный pytest недоступен без зависимостей.

Результат: есть точка возврата и сопоставимый baseline.

### Этап 1. Инвентаризация большого файла

Разделить код `big_landing_code.py` на категории:

- общая навигация;
- popup/form primitives;
- address/suggestion logic;
- submit/success;
- уведомления;
- brand-specific branches;
- MTS AB branches;
- старые form-oriented branches.

Результат: список функций, которые переносятся в каждый самостоятельный файл.

### Этап 2. Независимый Beeline-сценарий

- Перенести полный рабочий flow в `scenarios/beeline.py`.
- Убрать из файла ветки MTS, Mega, RTK, T2 и form-oriented.
- Запустить только `Jenkinsfile.beeline`.
- Сравнить Allure, ошибки и время с baseline.

Критерий: Beeline job запускается без импорта `big_landing_code.py`.

### Этап 3. Остальные стандартные бренды

Последовательно перенести:

```text
mega -> providerdom -> rtk -> t2 -> mts
```

Каждый перенос проходит отдельный parity-check до перехода к следующему бренду.

### Этап 4. MTS GPON AB

- Перенести только GPON-логику в `scenarios/mts_gpon_ab.py`.
- Сохранить одну session на домен.
- Перенести version detection и локаторы из `Everyday_test`.
- Проверить четыре URL и переходы между ними.

### Этап 5. MTS Home Online AB

- Перенести отдельную логику в `scenarios/mts_home_online_ab.py`.
- Не переиспользовать GPON-specific branches.
- Проверить четыре URL и success flow каждой AB-версии.

### Этап 6. Переключение Jenkins

- Каждый `Jenkinsfile.<scope>` запускает только свой сценарий.
- В `jenkins/brand_pipeline.groovy` заменить запуск core-файла на `scenarios/<scope>.py`.
- Проверить, что отчёты и state-файлы разделены по scope.

### Этап 7. Удаление большого файла

Перед удалением проверить:

- `rg` не находит импорт `big_landing_code` в `scenarios/` и Jenkins;
- все 8 entrypoint-файлов импортируются отдельно;
- каждый Jenkinsfile проходит smoke collection;
- Allure и Telegram работают без большого файла;
- MTS AB не зависит от generic fallback.

После этого удалить `big_landing_code.py` и архивировать старый `mts_ab_tests`.

## 7. Проверки на каждом этапе

### Статические

- AST/compile всех изменённых Python-файлов;
- `git diff --check`;
- поиск запрещённых импортов;
- проверка фиксированного scope.

### Collection

Для каждого entrypoint:

```text
pytest scenarios/<scope>.py --collect-only --run-mode=brand-oriented --brand-scope=<scope>
```

### Runtime smoke

- один URL главной страницы;
- один московский URL;
- один региональный URL;
- отдельно по одному GPON и Home Online AB URL.

### Acceptance

- ошибка одного URL не прекращает обработку остальных;
- отчёт содержит только текущий scope;
- summary state не пересекается с оригинальным большим тестом;
- один AB-сценарий не использует локаторы другого AB-сценария;
- итоговое время и стабильность не хуже baseline.

## 8. Откат

До этапа 7 старый `big_landing_code.py` сохраняется как fallback-файл, но не запускается новыми Jenkins jobs.
Если перенос одного бренда не проходит parity-check, откатывается только его entrypoint и Jenkinsfile,
остальные перенесённые бренды не блокируются.

## 9. Источники QA

- `docs/qa-kb/workflows/analyze-task.md`
- `docs/qa-kb/project-contexts/everyday-test/context.md`
- `docs/qa-kb/project-contexts/everyday-test/mts-new-version-implementation.md`

## 10. Технический контракт entrypoint-файла

Каждый файл из `scenarios/` является самостоятельным pytest-модулем.
Он обязан запускаться напрямую:

```text
pytest scenarios/beeline.py \
  --run-mode=brand-oriented \
  --brand-scope=beeline \
  --alluredir=allure-results
```

Entry point не должен импортировать `big_landing_code` или другой entry point.
Разрешены импорты из:

```text
config.*
conftest.py через pytest fixtures
allure
pytest
playwright.sync_api
```

Если временно требуется общая функция, она сначала переносится в сам entrypoint,
после чего зависимость от `big_landing_code.py` удаляется до завершения этапа.

## 11. Структура самостоятельного сценария

Рекомендуемый порядок разделов в каждом файле:

```text
imports
SCOPE / SCENARIO_TYPE / EXPECTED_HOSTS
локальные константы и локаторы
pytest_generate_tests
browser/session helpers
navigation helpers
popup/form helpers
submit/success helpers
test_<scope>
```

Сценарий не должен содержать условие вида:

```python
if provider == "...":
```

для другого бренда. Такие ветки удаляются, а не оставляются как generic fallback.

## 12. Контракт конфигурации URL

`build_site_configs_from_brand_scope(scope)` возвращает словарь конфигураций.
Минимальные поля каждого URL:

```python
{
    "base_url": "https://example.ru/",
    "has_checkaddress": bool,
    "has_business": bool,
    "has_name_field": bool,
    "_brand_scope": "beeline",
    "_source_mode": "url_file",
    "_expected_form_types": set[str],
    "_optional_expected_form_types": set[str],
}
```

Entry point не меняет URL после загрузки. Query, scheme, host и path должны
оставаться такими, как указано в `urls/brand_scopes/<scope>.txt`, кроме заранее
описанной canonicalization для дедупликации.

## 13. Жизненный цикл одного URL

### Стандартный бренд

```text
fixture page/context
  -> safe_goto(url)
  -> close overlays / cookie / region popup
  -> run brand-specific form flow
  -> submit
  -> verify success marker
  -> attach result to Allure
  -> close page
```

### MTS AB

```text
session context for domain
  -> create page for URL
  -> detect site version
  -> select only matching locator set
  -> run address/popup flow
  -> submit and verify success
  -> close page, preserve context storage
  -> next URL
```

Нельзя сохранять между URL ссылки на DOM-элементы, popup handles и введённые
значения. Для MTS AB сохраняются только browser-level cookies/storage/version state.

## 14. Границы ответственности

| Компонент | Ответственность | Не должен делать |
| --- | --- | --- |
| `scenarios/<scope>.py` | Шаги конкретного бренда и локаторы | Запускать другой scope |
| `config/brand_scope.py` | Реестр scope и provider mapping | Выполнять Playwright-действия |
| `config/url_loader.py` | Сборка URL-конфигураций | Решать, как кликать форму |
| `conftest.py` | Browser, proxy, profile, session fixture | Содержать брендовые локаторы |
| `notify_from_allure.py` | Сводка, deduplication, recovery | Определять успех UI-сценария |
| `jenkins/brand_pipeline.groovy` | Checkout, deps, pytest, Allure, notify | Содержать тестовую бизнес-логику |
| `Jenkinsfile.<scope>` | Фиксирует scope и entrypoint | Выбирать scope через UI-параметр |

## 15. Правила копирования из `big_landing_code.py`

Перенос выполнять блоками:

1. constants/error reasons;
2. URL and host predicates;
3. navigation and safe goto;
4. cookie/region overlay handling;
5. locator/form configuration;
6. suggestions and address filling;
7. submit and success confirmation;
8. Allure step wrappers;
9. Telegram event registration.

После каждого блока:

- AST/compile;
- импорт entrypoint;
- collection одного scope;
- smoke одного URL.

Не переносить в брендовый файл:

- branches другого бренда;
- form-oriented presence/full orchestration;
- provider matrix;
- старые `PRIMARY_FORM` и rotation rules;
- неиспользуемые mobile/business branches.

## 16. Jenkins contract

Каждый файл запускается отдельной job с настройкой Script Path:

| Job | Script Path | Fixed scope |
| --- | --- | --- |
| Beeline | `Jenkinsfile.beeline` | `beeline` |
| Mega | `Jenkinsfile.mega` | `mega` |
| MTS | `Jenkinsfile.mts` | `mts` |
| Providerdom | `Jenkinsfile.providerdom` | `providerdom` |
| Rostelecom | `Jenkinsfile.rtk` | `rtk` |
| T2 | `Jenkinsfile.t2` | `t2` |
| MTS GPON AB | `Jenkinsfile.mts_gpon_ab` | `mts_gpon_ab` |
| MTS Home Online AB | `Jenkinsfile.mts_home_online_ab` | `mts_home_online_ab` |

Внутри pipeline должны быть зафиксированы:

```text
RUN_MODE=brand-oriented
BRAND_SCOPE=<fixed scope>
PYTEST_FILE=scenarios/<scope>.py
ALLURE_RESULTS_DIR=allure-results
SUMMARY_STATE_FILE=/var/lib/jenkins/shared/big_land_test_2/summary_<scope>.json
ALERT_STATE_FILE=/var/lib/jenkins/shared/big_land_test_2/alert_<scope>.json
```

`BRAND_SCOPE` не должен приходить из пользовательского параметра Jenkins.

## 17. Allure и Telegram contract

Каждый result обязан содержать:

```text
brand_scope
scenario_type: brand | mts_ab
url
browser
execution_profile
domain_session
step
status
error_type
error_detail
```

Summary state и alert state хранятся отдельно по scope. Runtime deduplication
использует минимум `JOB_NAME + BRAND_SCOPE + error_group_key`.

Проверка успеха UI не должна зависеть от того, отправилось ли Telegram-сообщение.
И наоборот, ошибка отправки Telegram не должна менять результат теста.

## 18. Критерии удаления `big_landing_code.py`

Перед удалением выполнить все проверки:

```text
rg -n "big_landing_code|run_form_oriented|PRIMARY_FORM|form-oriented|legacy" scenarios jenkins Jenkinsfile.*
```

Ожидаемый результат: нет рабочих импортов и запусков старой модели.

Дополнительно:

- каждый из 8 entrypoint импортируется отдельно;
- каждый scope собирает только свои URL;
- каждый Jenkinsfile указывает свой `scenarios/<scope>.py`;
- MTS AB запускается без generic brand entrypoint;
- state-файлы новой модели не совпадают с путями оригинального теста;
- Allure results и Telegram summary не смешиваются;
- старый `big_landing_code.py` можно удалить без изменения import graph.

## 19. Риски и решения

| Риск | Решение |
| --- | --- |
| Дублирование исправления в 8 файлах | Принимать дублирование на этапе стабилизации; вести одинаковые изменения через checklist |
| Расхождение локаторов между брендами | Запрещать generic fallback и проверять scope-specific locators |
| Потеря уведомлений | Сначала сравнить Allure/event output, затем удалить core |
| Ошибка одного бренда влияет на остальные | Отдельный Jenkins job, workspace и state paths |
| AB state переезжает между URL | Один context только внутри AB job, новый page на каждый URL |
| Слишком большой перенос за один commit | Один commit на этап и один parity-run на бренд |

## 20. Финальный порядок commits

```text
1. Add independent scenario entrypoints
2. Migrate Beeline
3. Migrate Mega
4. Migrate Providerdom
5. Migrate Rostelecom
6. Migrate T2
7. Migrate MTS standard
8. Migrate MTS GPON AB
9. Migrate MTS Home Online AB
10. Switch Jenkins jobs to independent entrypoints
11. Remove big_landing_code.py and archived old runners
```

## 21. Текущий локальный статус разработки

| Этап | Статус | Что подтверждено | Что ещё нельзя считать готовым |
| --- | --- | --- | --- |
| 0. Baseline | выполнен | scope-файлы, Jenkinsfile, state paths и ограничения зафиксированы | runtime parity не подтверждён полным pytest-прогоном |
| 1. Инвентаризация | выполнен | технический контракт, границы модулей и список зависимостей описаны | runtime-поведение нужно подтвердить в окружении с Playwright |
| 2–9. Все 8 сценариев | выполнены локально | каждый scope имеет самостоятельный файл, fixed `SCOPE`, собственный pytest entrypoint и URL list | parity/smoke ещё не выполнены |
| 10. Jenkins switch | выполнен локально | каждый `Jenkinsfile.<scope>` указывает `scenarios/<scope>.py`; уведомления вынесены в `notification_transport.py` | не пушить до runtime-проверки |
| 11. Legacy removal | выполнен локально | удалены `big_landing_code.py`, корневой `Jenkinsfile`, старый AB-тест и `scenarios/runner.py` | проверить импорт/collection в CI-окружении |

### 21.1. Правило локальной разработки

До отдельной команды на push работа ведётся только в рабочей копии репозитория.
Каждый этап должен завершаться:

1. статической проверкой импортов и синтаксиса;
2. pytest collection соответствующего scope;
3. smoke/parity запуском одного URL, когда доступно окружение с Playwright;
4. сравнением Allure-полей и alert events со старой реализацией;
5. записью результата в эту таблицу.

Отсутствие локального `.venv` или невозможность выполнить runtime smoke не считается
успешным завершением этапа: в таком случае фиксируется только статический результат.

### 21.2. Граница переключения Jenkins

Локальная рабочая копия уже переведена на независимые entrypoint-файлы.
Публиковать изменения и запускать новую модель в Jenkins можно только после
parity-checklist: collection всех scope, smoke одного URL каждого scope,
проверка Allure и сравнение alert events.
