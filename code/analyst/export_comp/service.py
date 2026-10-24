"""Контекст стратегии: сервис экспорта, который вызывает report_comp."""

from __future__ import annotations

import re
from collections.abc import Iterable

from analyst.export_comp.models import ExportFormat, ReportDocument, ReportValidationError
from analyst.export_comp.strategies import ExportStrategy

_TRANSLIT = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
     "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"],
))


class ExportService:
    """Выгружает отчёт в нужный формат, подменяя стратегию на лету."""

    def __init__(
        self,
        strategies: Iterable[ExportStrategy],
        default: ExportFormat = ExportFormat.PDF,
    ) -> None:
        self._strategies: dict[ExportFormat, ExportStrategy] = {s.format: s for s in strategies}
        if default not in self._strategies:
            raise ValueError(f"Нет стратегии для формата по умолчанию: {default.value}")
        self._strategy: ExportStrategy = self._strategies[default]

    @property
    def current_format(self) -> ExportFormat:
        """Формат текущей стратегии."""
        return self._strategy.format

    def set_strategy(self, strategy: ExportStrategy) -> None:
        """Делает стратегию текущей и регистрирует её формат."""
        self._strategies[strategy.format] = strategy
        self._strategy = strategy

    def export(self, document: ReportDocument, fmt: ExportFormat) -> bytes:
        """Проверяет отчёт и выгружает его в формат fmt (сигнатура из ЛР2)."""
        self._validate(document)
        if self._strategy.format is not fmt:
            self.set_strategy(self._select(fmt))
        return self._strategy.render(document)

    def content_type(self, fmt: ExportFormat) -> str:
        """MIME-тип файла для формата (сигнатура из ЛР2)."""
        return self._select(fmt).media_type

    def filename(self, document: ReportDocument, fmt: ExportFormat) -> str:
        """Имя файла «<slug>_<ГГГГММДД-ГГГГММДД>.<ext>» для ключа в MinIO."""
        latin = "".join(_TRANSLIT.get(ch, ch) for ch in document.title.lower())
        slug = re.sub(r"[^a-z0-9]+", "_", latin).strip("_") or "report"
        period = f"{document.period.date_from:%Y%m%d}-{document.period.date_to:%Y%m%d}"
        return f"{slug}_{period}.{self._select(fmt).extension}"

    def _select(self, fmt: ExportFormat) -> ExportStrategy:
        """Находит стратегию для формата."""
        try:
            return self._strategies[fmt]
        except KeyError:
            raise ReportValidationError(f"Формат {fmt.value} не подключён") from None

    def _validate(self, document: ReportDocument) -> None:
        """Отчёт должен иметь название, корректный период и хотя бы одну строку."""
        if not document.title.strip():
            raise ReportValidationError("У отчёта нет названия")
        if document.period.date_from > document.period.date_to:
            raise ReportValidationError("Начало периода позже конца")
        tables = document.tables()
        if not tables:
            raise ReportValidationError("В отчёте нет данных")
        for table in tables:
            for row in table.rows:
                if len(row) != len(table.columns):
                    raise ReportValidationError(
                        f"В таблице «{table.title}» число значений не совпадает с числом колонок"
                    )
