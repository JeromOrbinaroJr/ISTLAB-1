"""Модели данных модуля экспорта (поля совпадают с ЛР2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import TypeAlias
from uuid import UUID

from shared.dto import MarketIndicator

Cell: TypeAlias = str | int | float
"""Значение одной ячейки таблицы отчёта."""


class ExportFormat(str, Enum):
    """Поддерживаемые форматы выгрузки."""

    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"


class ReportValidationError(ValueError):
    """Отчёт нельзя выгрузить: он пуст, некорректен или формат не подключён."""


@dataclass(frozen=True, slots=True)
class Period:
    """Отчётный период, границы включительно."""

    date_from: date
    date_to: date

    def label(self) -> str:
        """Период в виде «12.10.2026 – 18.10.2026»."""
        return f"{self.date_from:%d.%m.%Y} – {self.date_to:%d.%m.%Y}"


@dataclass(frozen=True, slots=True)
class KpiValue:
    """Значение показателя использования или эффективности."""

    kpi: str
    value: float
    unit: str
    period: Period
    dimension: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkRow:
    """Сравнение проекта компании с рыночным значением."""

    project_id: UUID
    project_title: str
    industry: str
    metric: str
    company_value: float
    market_value: float
    delta_pct: float


@dataclass(frozen=True, slots=True)
class ReportTable:
    """Одна таблица отчёта: заголовок, колонки и строки."""

    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]


@dataclass(frozen=True, slots=True)
class ReportDocument:
    """Отчёт до выгрузки в файл (содержимое формирует report_comp)."""

    title: str
    period: Period
    kpis: tuple[KpiValue, ...] = ()
    indicators: tuple[MarketIndicator, ...] = ()
    benchmark: tuple[BenchmarkRow, ...] = ()

    def tables(self) -> tuple[ReportTable, ...]:
        """Раскладывает отчёт на таблицы; пустые разделы пропускаются."""
        result: list[ReportTable] = []
        if self.kpis:
            result.append(ReportTable(
                title="Показатели использования и эффективности",
                columns=("Показатель", "Значение", "Ед. изм.", "Срез"),
                rows=tuple((k.kpi, k.value, k.unit, k.dimension or "—") for k in self.kpis),
            ))
        if self.indicators:
            result.append(ReportTable(
                title="Рыночные индикаторы",
                columns=("Показатель", "Значение", "Ед. изм.", "Период", "Источник", "Ссылка"),
                rows=tuple(
                    (i.metric, i.value, i.unit, i.period, i.source, i.source_url)
                    for i in self.indicators
                ),
            ))
        if self.benchmark:
            result.append(ReportTable(
                title="Сопоставление с рынком",
                columns=("Проект", "Отрасль", "Показатель", "Компания", "Рынок", "Отклонение, %"),
                rows=tuple(
                    (b.project_title, b.industry, b.metric, b.company_value, b.market_value, b.delta_pct)
                    for b in self.benchmark
                ),
            ))
        return tuple(result)
