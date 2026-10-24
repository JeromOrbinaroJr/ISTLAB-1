"""Демонстрация: один отчёт выгружается в три формата, стратегия меняется на лету.

Запуск из папки code/:  python -m analyst.demo
Файлы сохраняются в папку export_demo_output/.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID

from analyst.export_comp import (
    BenchmarkRow,
    CsvExportStrategy,
    ExportFormat,
    ExportService,
    ExportStrategy,
    KpiValue,
    PdfExportStrategy,
    Period,
    ReportDocument,
    ReportValidationError,
    XlsxExportStrategy,
)
from analyst.export_comp.prototype_adapters import MinimalPdfRenderer
from shared.dto import MarketIndicator


def sample_digest() -> ReportDocument:
    """Еженедельный рыночный дайджест с тестовыми данными."""
    week = Period(date(2026, 10, 12), date(2026, 10, 18))
    return ReportDocument(
        title="Еженедельный рыночный дайджест",
        period=week,
        kpis=(
            KpiValue("Поисков в базе знаний", 1284, "шт.", week),
            KpiValue("Скачиваний материалов", 312, "шт.", week),
            KpiValue("Среднее время подготовки материала", 37.5, "мин", week, "Маркетинг"),
        ),
        indicators=(
            MarketIndicator("Объём рынка ИИ-решений", 1486.0, "млрд руб.", "2025", "TAdviser",
                            "https://www.tadviser.ru/"),
            MarketIndicator("Рост рынка корпоративного ПО", 18.4, "%", "2025", "Strategy Partners",
                            "https://strategy.ru/"),
        ),
        benchmark=(
            BenchmarkRow(UUID("6f1c2a8e-0000-4000-8000-000000000001"), "Цифровой двойник цеха",
                         "Промышленность", "Срок внедрения, мес.", 4.0, 6.5, -38.46),
        ),
    )


def main() -> None:
    out = Path("export_demo_output")
    out.mkdir(exist_ok=True)

    strategies: list[ExportStrategy] = [CsvExportStrategy(), XlsxExportStrategy()]
    try:
        strategies.append(PdfExportStrategy(MinimalPdfRenderer()))
        default = ExportFormat.PDF
    except FileNotFoundError as error:
        print(f"PDF пропущен: {error}")
        default = ExportFormat.CSV

    service = ExportService(strategies, default=default)
    report = sample_digest()
    print(f"Стратегия по умолчанию: {service.current_format.value}")

    # Тот же вызов export(), но формат разный — сервис сам подменяет стратегию.
    for fmt in (ExportFormat.PDF, ExportFormat.CSV, ExportFormat.XLSX):
        try:
            content = service.export(report, fmt)
        except ReportValidationError as error:
            print(f"{fmt.value}: {error}")
            continue
        path = out / service.filename(report, fmt)
        path.write_bytes(content)
        print(f"{fmt.value:>4} → стратегия {service.current_format.value:<4} "
              f"{service.content_type(fmt):<70} {len(content):>8} байт  {path}")

    # Явная подмена через set_strategy: снова CSV, без правки ExportService.
    service.set_strategy(CsvExportStrategy())
    print(f"После set_strategy текущий формат: {service.current_format.value}")

    # Проверка отчёта: пустой отчёт не выгружается.
    try:
        service.export(ReportDocument("Пустой отчёт", report.period), ExportFormat.CSV)
    except ReportValidationError as error:
        print(f"Пустой отчёт отклонён: {error}")


if __name__ == "__main__":
    main()
