# Отчет по `Everyday_test`: архитектура, доработки, стабильность, green-прогоны
Дата: 2026-05-05

## 1. Что это за продукт
- `Everyday_test` — это единый репозиторий автотестов лендингов провайдеров.
- Внутри 2 независимых контура:
- `Suite A` — проверка форм заявок (`big_landing_code.py`).
- `Suite B` — проверка блока мобильных тарифов (`mobile_tariffs_tests`).
- Отчетность: Allure + Telegram алерты.

## 2. Текущая архитектура запуска
- Базовая модель: провайдерные конфиги (`config/providers/*.py`) — единый источник данных для desktop и mobile.
- Desktop orchestration:
- `provider-orchestrator.yml` — общий оркестратор по провайдерам.
- `provider-<name>.yml` — ручной/точечный запуск конкретного провайдера.
- Mobile orchestration:
- `provider-mobile-orchestrator.yml` — единый mobile-оркестратор по матрице.
- Провайдерные workflow теперь тоже умеют mobile-прогоны прямо из карточки.
- Временные mobile pilot workflow удалены как дубли.

## 3. Как работает процесс сейчас
1. Выбор провайдера/скоупа (`smoke` или `all`).
2. Выбор браузеров (`chromium`, `webkit`; для desktop также `firefox`).
3. Выбор режима (`core` или `variants`).
4. Запуск тестов на провайдерных конфигах.
5. Сбор Allure-результатов по всем шагам.
6. Публикация отчета в GitHub Pages.
7. Отправка Telegram-алертов/summary.

## 4. Что доработали в рамках оркестраторов и provider split
- Разделили процесс по провайдерам и закрепили orchestrated-модель.
- Внедрили единый mobile orchestrator.
- Добавили mobile-тумблеры в каждый `provider-*.yml`:
- `run_mobile_chromium`
- `run_mobile_webkit`
- Добавили mobile-шаги `core` и `variants` в провайдерные workflow.
- Стабилизировали проблемный mobile-кейс Domru: выбор региона/города через burger-меню.
- Сохранили desktop-стабильность: mobile доработки не ломают desktop-архитектуру.

## 5. Что работает стабильно
- Desktop provider orchestration — рабочий и стабильный.
- Mobile orchestration (`smoke/all`) — рабочий.
- Core/Variants mobile на целевых нестабильных провайдерах (`domru`, `t2`) — green.
- Allure-публикация и Telegram-алерты — рабочие.

## 6. Подтвержденные green-прогоны (из фактических запусков)
- `megafon (webkit)`: `2/2 pass`, `7:49`
- `domru (chromium)`: после фикса региона `2/2 pass`, `5:20`
- `domru (webkit)`: `2/2 pass`, `5:49`
- `t2 (chromium)`: `1/1 pass`, `1:49`
- `t2 (webkit)`: `1/1 pass`, `2:08`
- `domru variants (chromium)`: `2/2 pass`, `5:42`
- `t2 variants (chromium)`: `1/1 pass`, `0:36`
- `t2 variants (webkit)`: `1/1 pass`, `0:39`

## 7. Разница “до / после”
- До:
- mobile запуск был более фрагментирован (временные пилотные workflow).
- выше операционная нагрузка и сложнее диагностика.
- падал mobile city/region кейс на Domru.
- После:
- единый mobile orchestrator + mobile запуск из provider workflow.
- единая конфигурационная модель для desktop/mobile.
- стабильные green-прогоны на быстрых/нестабильных кейсах.
- более предсказуемая скорость и удобнее контроль качества.

## 8. Ссылки на отчетность (Allure/CI)
- Mobile orchestrator отчеты: [provider-mobile-orchestrator](https://deidolinde-maker.github.io/Everyday_test/provider-mobile-orchestrator/)
- Пример suite-репорта: [suite run](https://deidolinde-maker.github.io/Everyday_test/provider-mobile-orchestrator/#suites/88ed29bce09c7a4eaf2387b89fea7e0f/bb49655d4180c310/)
- Пример CI run: [GitHub Actions job](https://github.com/deidolinde-maker/Everyday_test/actions/runs/25303912692/job/74175861735)

## 9. Итог для бизнеса
- Продукт стал стабильнее и управляемее.
- Скорость принятия решений выросла за счет коротких и понятных прогонов.
- Mobile контур внедрен без архитектурного ущерба desktop-контуру.
- Текущая модель готова к дальнейшему масштабированию без возврата к временным схемам.


