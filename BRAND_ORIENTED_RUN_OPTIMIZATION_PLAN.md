# Brand-oriented модель автотеста

## Решение

Form-oriented модель с отдельной job на каждую форму не используется как целевая: она увеличила длительность прогона примерно до 6 часов и ухудшила стабильность.

Новая модель разделяет запуск по брендам:

```text
beeline
mega
mts
providerdom
rtk
t2
```

Отдельные сценарии:

```text
mts_gpon_ab         -> mts-home-gpon.ru
mts_home_online_ab  -> mts-home-online.ru
```

Каждый AB-сценарий запускается отдельной Jenkins job и не пересекается с другими лендингами.

Исполнительные entrypoint-файлы находятся в `scenarios/`:

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

Большой `big_landing_code.py` удалён из новой модели. Каждый scope запускается
через собственный entrypoint в `scenarios/`; Jenkins больше не имеет fallback
на общий файл.

## URL-сборка

Новые сокращённые scope-файлы находятся в `urls/brand_scopes/`.
В них закреплены главная, Москва, Санкт-Петербург и один региональный URL, если он подходит для проверки домашнего интернета.

AB scope:

- GPON: главная, Москва, Санкт-Петербург, Самара;
- Home Online: главная, Москва, Санкт-Петербург, Апрелевка.

Закомментированные URL и исключённые бренды в новые scope не попадают.

## Сессии

Обычные brand jobs обрабатывают URL в изолированных context.
Для каждого AB-сценария создаётся один browser context на всю job и домен. Внутри него URL идут последовательно. Cookies, `localStorage`, AB-marker и version state сохраняются; page-level popup и введённые поля сбрасываются при переходе к следующему URL.

## MTS AB

Используется логика `Everyday_test`:

- определение версии;
- version-specific локаторы;
- scoped visible forms;
- связанные street/house suggestions;
- обработка регионального popup;
- retry для disabled house field;
- действующий success-маркер.

Generic locator fallback других брендов к AB-сценариям не подключается.

## Переход

Старый режим сохраняется. Новый включается параметрами:

```text
RUN_MODE=brand-oriented
BRAND_SCOPE=<scope>
```

Сначала запускаются отдельные сравнимые jobs на одном браузере и прокси. Сравниваются время, timeout/retry, количество ошибок и полнота сценариев.
