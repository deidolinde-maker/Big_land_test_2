# Отчет по доработкам оркестраторов и mobile rollout
Дата: 2026-05-04  
Репозиторий: `deidolinde-maker/Everyday_test`  
Основание: `PATCH_BRANCH_3_PROVIDER_SPLIT_IMPLEMENTATION_PLAN.md`, `PATCH_BRANCH_4_MOBILE_PROFILE_IMPLEMENTATION_PLAN.md`

## 1. Краткий итог
- Провайдерный desktop-контур стабилен и работает через оркестратор.
- Mobile-контур выведен в рабочий прод-процесс через единый orchestrator.
- Добавлен удобный запуск mobile прямо из карточек провайдерских workflow.
- Сохранена архитектурная целостность: desktop и mobile используют общую конфигурационную модель, без дублирования логики.

## 2. Что реализовано
### 2.1 Desktop / provider orchestration
- Закреплен основной процесс через:
  - `.github/workflows/provider-orchestrator.yml`
  - `.github/workflows/provider-mts.yml`
  - `.github/workflows/provider-beeline.yml`
  - `.github/workflows/provider-megafon.yml`
  - `.github/workflows/provider-t2.yml`
  - `.github/workflows/provider-rostelecom.yml`
  - `.github/workflows/provider-domru.yml`
- Последовательные прогоны по провайдерам дают:
  - более короткие и читаемые логи;
  - быструю локализацию проблем;
  - меньший риск “массовых” непрозрачных падений.

### 2.2 Mobile orchestration
- Реализован и запущен единый mobile-контур:
  - `.github/workflows/provider-mobile-orchestrator.yml`
- Поддерживаемые режимы:
  - `provider_scope=smoke|all`
  - `core|variants`
  - `chromium|webkit`
- Публикация отчетов:
  - `gh-pages/provider-mobile-orchestrator/`

### 2.3 Финальная унификация запуска
- Во все `provider-*.yml` добавлены mobile-переключатели:
  - `run_mobile_chromium`
  - `run_mobile_webkit`
- В эти же workflow добавлены mobile шаги:
  - `Run Core Mobile tests (...)`
  - `Run Place Variants Mobile tests (...)`
- Mobile результаты включены в общий merge Allure внутри провайдерных workflow.

### 2.4 Устранение ключевой mobile-нестабильности
- Исправлен сценарий выбора региона для Domru-семейства в mobile:
  - регион-селектор находится внутри burger-меню;
  - добавлена логика открытия burger перед city-сценарием.
- Результат: ранее падавшие тесты по выбору города стали green.

## 3. Результаты прогонов и скорость
## 3.1 Core mobile (подтвержденные целевые прогоны)
- `megafon (webkit)`: `2/2 passed`, `7:49`
- `domru (chromium)`: после фикса региона `2/2 passed`, `5:20`
- `domru (webkit)`: `2/2 passed`, `5:49`
- `t2 (chromium)`: `1/1 passed`, `1:49`
- `t2 (webkit)`: `1/1 passed`, `2:08`

## 3.2 Variants mobile (быстрые нестабильные провайдеры)
- `domru (chromium)`: `2/2 passed`, `5:42`
- `t2 (chromium)`: `1/1 passed`, `0:36`
- `t2 (webkit)`: `1/1 passed`, `0:39`

## 3.3 Full mobile orchestrator
- Выполнен полный прогон (`all`), подтвержден рабочий статус контура.
- Это отдельный результат от `smoke`, не пилот.

## 4. Разница между старой и новой версией процесса
### 4.1 До доработок
- Mobile запуск опирался на временные pilot workflow.
- Были нестабильные падения на city-сценарии в mobile (Domru).
- Запуск mobile из provider workflow был неудобным.
- Контур mobile воспринимался как вспомогательный и менее системный.

### 4.2 После доработок
- Единый orchestrator для mobile и единый запуск из provider workflow.
- Устранен критичный мобильный флак с region/city в Domru.
- Удалены временные mobile workflow-дубликаты.
- Процесс стал сквозным, предсказуемым и операционно удобным.

## 5. Архитектурный эффект
- Mobile тест не ломает desktop-контур: изоляция достигнута на уровне execution-profile и workflow-флагов.
- Конфигурации провайдеров общие для desktop и mobile:
  - изменения в одном месте масштабируются на оба контура.
- Это снижает стоимость поддержки и риск рассинхронизации тестовой логики.

## 6. Текущее состояние и готовность
- Desktop/provider процесс: стабилен.
- Mobile process: стабилен в clean-контуре (`blocking_profile=none`).
- Алерты и отчетность: работают.
- Оркестраторы: готовы для дальнейшего масштабирования по следующим шагам плана.

## 7. Связь с планами
- `PATCH_BRANCH_3_PROVIDER_SPLIT_IMPLEMENTATION_PLAN.md`:
  - достигнута целевая модель провайдерной оркестрации и управляемых запусков.
- `PATCH_BRANCH_4_MOBILE_PROFILE_IMPLEMENTATION_PLAN.md`:
  - mobile rollout доведен до рабочего этапа с подтвержденными green-прогонами;
  - orchestrator и provider-level mobile toggles внедрены.

