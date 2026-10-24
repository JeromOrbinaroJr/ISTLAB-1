# ЛР3 (C4 L4) — backend: компонент `search_comp`

Диаграмма классов UML и прототип на Python компонента «Сервис гибридного поиска» (`search_comp`) контейнера `core_api`.
Паттерн «Стратегия»: три алгоритма поиска (полнотекстовый, семантический, гибридный RRF) подменяются во время работы без изменения сервиса.

Автор: Герман Осит (backend), группа ИДБ-23-14.

## Что в папке

```
lab3_backend/
├── README.md                     # эта инструкция
├── run_web.bat                   # наглядная демонстрация в браузере (Windows, двойной щелчок)
├── run_demo.bat                  # демонстрация в консоли
├── run_tests.bat                 # запуск тестов (Windows)
├── check_types.bat               # строгая проверка типов mypy (Windows)
├── screenshots/                  # снимки наглядной демонстрации
├── diagram/
│   ├── backend_classes.puml      # диаграмма классов (PlantUML)
│   └── backend_classes.png       # отрисованная диаграмма
└── code/
    ├── mypy.ini                  # строгий режим mypy (strict = True)
    ├── requirements-dev.txt      # mypy — нужен только для проверки типов
    ├── shared/dto.py             # общие модели данных команды
    └── backend/
        ├── search_comp/          # сам компонент
        │   ├── errors.py         # InvalidQueryError
        │   ├── query.py          # SearchQuery, AccessFilter
        │   ├── ports.py          # порты FullTextSource, SemanticSource, SearchCache, UsagePublisher
        │   ├── strategies.py     # SearchStrategy + FullText / Semantic / HybridRRF
        │   └── service.py        # SearchService — контекст стратегии
        ├── prototype_adapters.py # адаптеры в памяти вместо PostgreSQL, Qdrant, Redis, RabbitMQ
        ├── web_demo.py           # наглядная демонстрация в браузере
        ├── demo.py               # демонстрация в консоли
        └── tests/test_search_service.py  # 10 модульных тестов
```

## 1. Что нужно

- **Python 3.10 или новее** (рекомендуется 3.12). Внешние библиотеки для запуска не нужны — только стандартная библиотека.
- Проверить версию:
  - Windows: `python --version` (если команда не найдена — `py --version`, и дальше везде пиши `py` вместо `python`);
  - macOS / Linux: `python3 --version` (дальше везде `python3`).
- Если Python не установлен: python.org → Downloads → при установке отметь **Add python.exe to PATH**.

> Все команды ниже выполняются **из папки `code`**, иначе Python не найдёт пакеты `backend` и `shared`.

## 2. Быстрый запуск на Windows

Двойной щелчок по файлам в папке `lab3_backend`:

| Файл | Что делает |
|---|---|
| `run_web.bat` | Открывает наглядную демонстрацию в браузере |
| `run_demo.bat` | Запускает демонстрацию в консоли |
| `run_tests.bat` | Запускает 10 тестов |
| `check_types.bat` | Ставит mypy и проверяет типы в строгом режиме |

## 3. Наглядная демонстрация в браузере (главное для защиты)

```bash
python -m backend.web_demo
```

Скрипт поднимает маленький локальный сервер на стандартной библиотеке Python и сам открывает страницу **http://127.0.0.1:8765** (если не открылась — вставь адрес в браузер). Остановить — `Ctrl+C` в окне терминала. Интернет не нужен.

**Слева** выбираешь:
- **роль** — Маркетолог (группы marketing, sales), Руководитель маркетинга (marketing, management), Менеджер по развитию бизнеса (sales);
- **алгоритм** — Полнотекстовый, Семантический или Гибридный (RRF);
- **запрос** — вручную или готовой кнопкой, фильтр по типу документа и сколько результатов показать.

**Справа** видно:
- **Результаты** — найденные документы, их тип, кому доступны и оценка;
- **Как работал алгоритм** — те же шаги, что выполняет `SearchService.search`: проверка запроса → права доступа → смена стратегии (`set_strategy`) → кэш → сам алгоритм (списки кандидатов из источников, а у гибридного — таблица расчёта RRF: место → 1/(60 + место) → сумма) → сохранение в кэш → событие для аналитики;
- **Сравнить все три стратегии** — один запрос тремя алгоритмами рядом;
- **База знаний демонстрации** — все документы и видит ли их выбранная роль.

Что показать преподавателю за 1 минуту:

| Действие | Что видно |
|---|---|
| Переключи алгоритм с «Гибридный» на «Полнотекстовый» | Шаг 3: «Стратегия заменена… Код SearchService при этом не менялся» — это и есть паттерн «Стратегия» |
| Выбери «Гибридный (RRF)» и нажми «Найти» | Шаг 5: два списка кандидатов и таблица расчёта RRF |
| Роль «Руководитель маркетинга», запрос «бюджет» | Конфиденциальный бюджет найден |
| Переключи роль на «Маркетолог» | Бюджет не найден; шаг 2 показывает, что документ скрыт правами |
| Нажми «Найти» ещё раз | Шаг 4: «Попадание… ответ взят из кэша», стратегия не вызывалась |
| «Сравнить все три стратегии» | Разный порядок результатов у трёх алгоритмов |

Снимки экрана — в папке `screenshots/`.

> Код компонента `search_comp` для этой страницы не менялся: `web_demo.py` подключает к тому же `SearchService` порты-«наблюдатели», которые записывают, что происходило, и показывают это на странице.

## 4. Запуск из терминала

```bash
cd lab3_backend/code
```

### 4.1 Демонстрация в консоли

```bash
python -m backend.demo
```

Ожидаемый результат (сокращённо):

```
Стратегия fulltext: «презентации кейс внедрения»
  1. [0.3333] Кейс: внедрение ИИ-поиска в банке
  ...
Стратегия semantic: «презентации кейс внедрения»
  1. [0.4771] Кейс: внедрение ИИ-поиска в банке
  2. [0.4708] Презентация продукта для ЦИПР
  ...
Стратегия hybrid_rrf: «презентации кейс внедрения»
  ...
Повторный запрос (из кэша)
  ...
Фильтр: только кейсы
  ...
Маркетолог ищет «бюджет»
  (ничего не найдено)

Руководитель ищет «бюджет»
  1. [0.0328] Бюджет на маркетинг (конфиденциально)

Событий usage.event: 7; из кэша: 1
```

Что этим доказано:

| Блок вывода | Что проверяет |
|---|---|
| Три блока «Стратегия …» | Один и тот же `SearchService` работает с тремя стратегиями, подменяемыми через `set_strategy` — паттерн «Стратегия» |
| «Повторный запрос (из кэша)» | Результат взят из кэша, стратегия повторно не вызывалась |
| «Фильтр: только кейсы» | Фильтры запроса доходят до источников данных |
| «Маркетолог / Руководитель ищет «бюджет»» | Права доступа: конфиденциальный документ виден только группе `management` |
| «Событий usage.event: 7; из кэша: 1» | Каждый поиск публикует событие для аналитики |

### 4.2 Тесты

```bash
python -m unittest discover -s backend/tests -t . -v
```

Ожидаемый результат — 10 строк `... ok` и в конце:

```
Ran 10 tests in 0.0XXs

OK
```

| Тест | Что проверяет |
|---|---|
| `test_rrf_rewards_documents_found_by_both_sources` | Гибридная стратегия поднимает наверх фрагменты, найденные обоими источниками |
| `test_rrf_requests_more_candidates_than_top_k` | Гибридная стратегия запрашивает кандидатов с запасом |
| `test_strategies_share_one_contract` | Все три стратегии выполняют один контракт (принцип Лисков) |
| `test_set_strategy_changes_algorithm` | `set_strategy` подменяет алгоритм во время работы |
| `test_access_filter_hides_foreign_documents` | Чужие документы не попадают в выдачу |
| `test_second_call_comes_from_cache` | Повторный запрос берётся из кэша |
| `test_cache_key_depends_on_strategy` | Смена стратегии не отдаёт старый результат из кэша |
| `test_filters_are_passed_to_sources` | Фильтры запроса применяются |
| `test_invalid_queries_are_rejected` | Пустой запрос и `top_k = 0` вызывают `InvalidQueryError` |
| `test_publisher_failure_does_not_break_search` | Сбой публикации события не ломает поиск |

### 4.3 Проверка аннотаций типов (mypy, строгий режим)

Нужен интернет для установки mypy (один раз). Лучше в виртуальном окружении:

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements-dev.txt
mypy backend shared
```

Ожидаемый результат: `Success: no issues found in … source files`. Настройки строгого режима — в `mypy.ini` (`strict = True`).

## 5. Диаграмма

- Открой `diagram/backend_classes.puml` в VS Code и нажми **Alt+D** — предпросмотр через плагин PlantUML (локальный сервер из `docker-compose.yml` в корне проекта должен быть запущен: `docker compose up -d`).
- Готовая картинка — `diagram/backend_classes.png`.
- Имена классов, полей и методов на диаграмме совпадают с кодом в `code/backend/search_comp/`.

## 6. Как самому убедиться, что «Стратегия» работает

Открой Python из папки `code` (`python`) и выполни:

```python
from uuid import UUID
from backend.prototype_adapters import *
from backend.search_comp import *
from shared.dto import UserContext

corpus = demo_corpus()
ft, sem = InMemoryFullTextSource(corpus), InMemorySemanticSource(corpus)
service = SearchService(FullTextStrategy(ft), InMemorySearchCache(), CollectingUsagePublisher())
user = UserContext(UUID(int=1), ("marketer",), ("marketing", "sales"))

print([h.title for h in service.search("кейс", user)])      # полнотекстовый
service.set_strategy(SemanticStrategy(sem))                  # подмена на лету
print([h.title for h in service.search("кейс", user)])      # семантический
print(service.strategy.name)                                 # semantic
```

Код `SearchService` при этом не менялся — изменился только объект стратегии.

## 7. Если что-то не работает

| Ошибка | Причина и решение |
|---|---|
| `ModuleNotFoundError: No module named 'backend'` | Команда запущена не из папки `code`. Перейди: `cd lab3_backend/code` |
| `'python' is not recognized` | Python не в PATH. Используй `py` или переустанови Python с галочкой «Add to PATH» |
| `TypeError: dataclass() got an unexpected keyword argument 'slots'` | Python старше 3.10. Обнови Python |
| Кракозябры вместо русского текста в консоли Windows | Запускай через `.bat` или выполни перед запуском `chcp 65001` и `set PYTHONUTF8=1` |
| `No module named mypy` | Не выполнен `pip install -r requirements-dev.txt` |
| «Адрес уже используется» при запуске `web_demo` | Демонстрация уже запущена в другом окне — закрой его или открой http://127.0.0.1:8765 |
| Браузер не открылся сам | Открой адрес http://127.0.0.1:8765 вручную |
