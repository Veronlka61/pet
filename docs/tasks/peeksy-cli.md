# Peeksy — Visual Regression Testing CLI (peeksy)

## Current State

Проект **greenfield**. Из кода — только `main.py` (шаблон PyCharm). Архитектуры
нет: `goga schema` возвращает `[]`, клеток и CODEMANIFEST'ов не существует. Из
goga-артефактов — только usage-файлы (`.goga/usages/cooks/`) под три нетривиальные
библиотеки (`playwright.md`, `image-diff.md`, `allure.md`). Инструментов захвата,
сравнения и отчётности для UI-компонентов пока нет никаких.

## Description

CLI-приложение `peeksy` для автоматизированного визуального
regression-тестирования UI-компонентов веб-страниц. Самостоятельный CLI читает
конфигурацию из YAML, открывает страницы, находит компоненты по CSS-селекторам и
делает детерминированные element-level скриншоты через Playwright. Эталонные
изображения (baseline) создаются и обновляются командой `generate`; команда
`test` повторно снимает скриншоты, сравнивает их с baseline через pixelmatch
(мismatch % + diff-overlay) и формирует результат в формате **Allure Report**
(один test-case на компонент/viewport, с вложениями baseline/current/diff).
Команда `report` собирает browsable HTML через внешний `allure` CLI.

Команды:

- `peeksy generate` — снять baseline для всех компонентов из конфига.
- `peeksy generate --component header` — один компонент.
- `peeksy generate --component header --component sidebar` — несколько
  (флаг `--component` повторяемый).
- `peeksy test [--component NAME ...]` — снимает текущее состояние,
  сравнивает с baseline, пишет результаты Allure. **Read-only** относительно
  baseline; exit-код ≠ 0 при любой регрессии (CI-friendly).
- `peeksy report` — собирает HTML-отчёт Allure из директории результатов.

## Scope

**In scope:**
- CLI-каркас `peeksy` на Typer с командами `generate`, `test`, `report` и
  повторяемым флагом `--component`.
- Валидируемая YAML-конфигурация (Pydantic v2 + PyYAML): suite, компоненты
  (`name`, `url`, CSS `selector`, `mask_selectors`, `viewports`), пороги
  `threshold`/`tolerance`, пути к baseline/results/report.
- Захват детерминированных element-level скриншотов через Playwright (Chromium,
  headless, фиксированный DPR, network-idle, отключение анимаций, ожидание
  шрифтов, маскировка динамических зон).
- Сравнение baseline vs current через pixelmatch (mismatch %, diff-overlay,
  пороговая модель threshold + tolerance).
- Генерация результатов Allure программно через `allure-python-commons` (без
  pytest): один test-result на `(component, viewport)`, статусы
  PASSED/FAILED/BROKEN, вложения baseline/current/diff, стабильные
  `historyId`/`testCaseId`.
- Сборка HTML-отчёта через внешний `allure` CLI (`allure generate` / `allure open`).
- Базовый набор тестов самого инструмента (pytest + pytest-playwright).

**Out of scope:**
- Кросс-браузерная матрица за пределами Chromium (Firefox/WebKit — позже).
- CI/CD-плагины и интеграции (GitHub Actions/GitLab и т.п.).
- Интерактивный UI ревью/аппрува скриншотов.
- Сравнение полных страниц (full-page) как отдельный режим — фокус на компонентах.

## Acceptance Criteria

- `peeksy generate` без флагов создаёт baseline-изображения для всех
  компонентов из конфига в директории baseline; повторный запуск даёт
  попиксельно идентичные (pixelmatch-clean) результаты.
- `peeksy generate --component header --component sidebar` сохраняет
  baseline только для указанных компонентов.
- `peeksy test` сравнивает все компоненты, формирует результат Allure с
  вложениями baseline/current/diff и возвращает exit-код 0, если все прошли, и
  ≠ 0 — если хотя бы один компонент регрессировал.
- `peeksy test --component X` ограничивает прогон компонентом X.
- Для компонента с несколькими `viewports` `generate` снимает отдельный baseline
  на каждый viewport, а `test` формирует отдельный Allure test-result на пару
  `(component, viewport)` (со своими baseline/current/diff); при регрессии только
  в одном viewport FAILED получает именно эта строка, остальные остаются PASSED.
- Реальный сдвиг компонента на ~2px детектируется как FAILED (mismatch % выше
  tolerance).
- Ошибки инфраструктуры (страница не загрузилась, селектор не найден)
  отображаются в отчёте как `Status.BROKEN`, а не как визуальная регрессия.
- `peeksy report` собирает browsable Allure HTML из директории
  результатов.
- Некорректный YAML конфига вызывает понятную ошибку валидации (Pydantic).
- Тесты самого инструмента (pytest) проходят локально.

## Stack

- **Frameworks:** Typer (CLI), Pydantic v2 (модели конфига), pytest +
  pytest-playwright (тесты инструмента), ruff + mypy (качество).
- **Libraries:** Playwright (захват), pixelmatch + Pillow (сравнение),
  allure-python-commons (модель результатов Allure), PyYAML (чтение YAML).
- **Infrastructure:** внешний `allure` CLI (Java/JDK) — сборка HTML-отчёта;
  управление пакетами через `uv`; браузер Chromium через `playwright install`.

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| Playwright | `.goga/usages/cooks/playwright.md` | created |
| pixelmatch + Pillow | `.goga/usages/cooks/image-diff.md` | created |
| allure-python-commons + allure CLI | `.goga/usages/cooks/allure.md` | created |
| Typer | inline (в аннотациях CODEMANIFEST) | — |
| Pydantic v2 + PyYAML | inline (в аннотациях CODEMANIFEST) | — |
| pytest + pytest-playwright | inline (в аннотациях CODEMANIFEST) | — |

## Risks and Constraints

- **Системная зависимость JDK/allure CLI** — сборка HTML требует установленного
  `allure` (Java). Если нежелательно — рассмотреть чисто-python рендереры Allure.
- **Детерминизм снимков** — шрифты, анимации, anti-aliasing, динамический контент
  создают flaky-диффы; митигируется фиксированным DPR, отключением анимаций,
  `document.fonts.ready`, маскировкой зон (см. `playwright.md`).
- **Версия pixelmatch** — под именем `pixelmatch` есть несколько Python-портов с
  разным API; требуется зафиксировать точную версию и сверить сигнатуру вызова.
- **Shadow DOM / iframe** — компоненты внутри теневого DOM или фреймов требуют
  piercing-селекторов / `frame_locator` (отражено в `playwright.md`).
- **Пороги** — важно не путать per-pixel `threshold` (pixelmatch) и
  suite-level `tolerance` (решение о регрессии).

## Scope Estimate

**Одна задача.** Зоны ответственности (config, CLI, capture, compare,
reporting) станут **клетками** на этапе архитектуры (`goga-arch-by-brainstorm`),
а не отдельными задачами — ни один срез не даёт самостоятельной ценности
(`generate` без `test` — просто генератор скриншотов; `test` без baseline
сравнивать не с чем; `report` без `test` показывать нечего). Реализацию можно
бить на milestone внутри одной задачи:
1. Каркас CLI + YAML-конфигурация.
2. `generate` — захват baseline.
3. `test` — сравнение (pixelmatch) + результаты Allure.
4. `report` — сборка HTML.

## Existing Architecture

Отсутствует (greenfield). Клеток нет. Предварительные зоны для этапа архитектуры
(снизу вверх, по зависимостям): `config` (Pydantic-модели YAML) →
`capture` (Playwright) → `compare` (pixelmatch) → `reporting` (Allure) →
`runner` (оркестрация generate/test) → `cli` (Typer-фасад). Точная декомпозиция и
`Imports` определяются в `goga-arch-by-brainstorm`.

## Notes

Ключевые решения, зафиксированные при формулировке:
- **Архитектура выполнения:** самостоятельный CLI, пишет результаты Allure
  напрямую (не поверх pytest) — точно ложится на требование «CLI + YAML».
- **Имя CLI:** `peeksy`.
- **Baseline policy:** базлайны создаёт/перезаписывает только `generate`; `test`
  строго read-only и падает (exit ≠ 0) при регрессии; новое одобренное состояние
  принимается повторным запуском `generate` (отдельный `approve` и флаг `--update`
  в `test` отклонены).
- **Захват:** Playwright (выбрано вместо Selenium) — честные element-screenshots,
  авто-wait, network-idle, детерминированный рендер.
- **Сравнение:** pixelmatch (по требованию заказчика) + Pillow; AA-aware,
  mismatch count + diff-overlay.
- **Отчётность:** allure-python-commons (модель) + внешний `allure` CLI (HTML).
- **Usage-файлы** созданы для трёх нетривиальных библиотек: `playwright.md`,
  `image-diff.md`, `allure.md`. Typer и Pydantic/PyYAML оставлены inline.