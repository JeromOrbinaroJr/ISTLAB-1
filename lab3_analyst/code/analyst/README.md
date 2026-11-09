# analyst/export_comp — модуль экспорта отчётов (analytics_service)

Прототип компонента `export_comp` с паттерном «Стратегия»: формат выгрузки
(CSV, XLSX, PDF) подменяется на лету без изменения `ExportService`.
Только стандартная библиотека Python 3.12.

Все команды — из папки `code/`:

```bash
python -m analyst.demo                                  # демонстрация, файлы в export_demo_output/
python -m unittest discover -s analyst/tests -t .       # тесты
python -m mypy analyst shared                           # проверка типов (mypy --strict из mypy.ini)
```

| Файл | Что внутри |
|---|---|
| `export_comp/models.py` | `ExportFormat`, `Period`, `KpiValue`, `BenchmarkRow`, `ReportDocument`, `ReportTable`, `ReportValidationError` |
| `export_comp/strategies.py` | `ExportStrategy` (ABC) и стратегии CSV, XLSX, PDF |
| `export_comp/ports.py` | `PdfRenderer` (Protocol) — движок PDF |
| `export_comp/service.py` | `ExportService` — контекст стратегии |
| `export_comp/prototype_adapters.py` | `MinimalPdfRenderer` — PDF со встроенным системным TTF-шрифтом (в сервисе — WeasyPrint) |
| `demo.py`, `tests/` | демонстрация и тесты `unittest` |

PDF в прототипе ищет шрифт с кириллицей: DejaVu Sans (Linux), Arial (Windows, macOS)
или путь из переменной `EXPORT_PDF_FONT`. Если шрифта нет, демо пропускает PDF,
а соответствующий тест помечается как пропущенный.
