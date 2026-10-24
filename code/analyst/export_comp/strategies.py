"""Стратегии выгрузки отчёта: CSV, XLSX и PDF (паттерн «Стратегия»)."""

from __future__ import annotations

import csv
import html
import io
import zipfile
from abc import ABC, abstractmethod
from xml.sax.saxutils import escape

from analyst.export_comp.models import Cell, ExportFormat, ReportDocument, ReportTable
from analyst.export_comp.ports import PdfRenderer


class ExportStrategy(ABC):
    """Общий интерфейс всех форматов выгрузки."""

    @property
    @abstractmethod
    def format(self) -> ExportFormat:
        """Формат, который выпускает стратегия."""

    @property
    @abstractmethod
    def media_type(self) -> str:
        """MIME-тип файла."""

    @property
    @abstractmethod
    def extension(self) -> str:
        """Расширение файла без точки."""

    @abstractmethod
    def render(self, document: ReportDocument) -> bytes:
        """Превращает отчёт в байты файла."""


class CsvExportStrategy(ExportStrategy):
    """CSV для Excel и BI: разделитель «;», UTF-8 с BOM, десятичная запятая."""

    @property
    def format(self) -> ExportFormat:
        return ExportFormat.CSV

    @property
    def media_type(self) -> str:
        return "text/csv; charset=utf-8"

    @property
    def extension(self) -> str:
        return "csv"

    def render(self, document: ReportDocument) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
        writer.writerow([document.title])
        writer.writerow([f"Период: {document.period.label()}"])
        for table in document.tables():
            writer.writerow([])
            writer.writerow([table.title])
            writer.writerow(table.columns)
            for row in table.rows:
                writer.writerow([_csv_cell(value) for value in row])
        # BOM нужен, чтобы Excel сразу распознал UTF-8 и показал кириллицу.
        return buffer.getvalue().encode("utf-8-sig")


def _csv_cell(value: Cell) -> str:
    """Число с десятичной запятой (русская локаль Excel), остальное — как есть."""
    if isinstance(value, float):
        return f"{value:.2f}".replace(".", ",")
    return str(value)


class XlsxExportStrategy(ExportStrategy):
    """Минимальная книга Excel (Office Open XML): по листу на таблицу отчёта."""

    # Фиксированная дата внутри ZIP делает выгрузку воспроизводимой.
    _ZIP_DATE = (2026, 1, 1, 0, 0, 0)

    @property
    def format(self) -> ExportFormat:
        return ExportFormat.XLSX

    @property
    def media_type(self) -> str:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    @property
    def extension(self) -> str:
        return "xlsx"

    def render(self, document: ReportDocument) -> bytes:
        tables = document.tables()
        sheets = "".join(
            f'<sheet name="{escape(_sheet_name(t.title, n))}" sheetId="{n}" r:id="rId{n}"/>'
            for n, t in enumerate(tables, start=1)
        )
        sheet_rels = "".join(
            f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/'
            f'2006/relationships/worksheet" Target="worksheets/sheet{n}.xml"/>'
            for n in range(1, len(tables) + 1)
        )
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{n}.xml" ContentType="application/'
            f'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for n in range(1, len(tables) + 1)
        )
        parts: dict[str, str] = {
            "[Content_Types].xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                f"{overrides}</Types>"
            ),
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
            ),
            "xl/workbook.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f"<sheets>{sheets}</sheets></workbook>"
            ),
            "xl/_rels/workbook.xml.rels": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f"{sheet_rels}</Relationships>"
            ),
        }
        for n, table in enumerate(tables, start=1):
            parts[f"xl/worksheets/sheet{n}.xml"] = self._sheet_xml(table)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                info = zipfile.ZipInfo(name, date_time=self._ZIP_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content.encode("utf-8"))
        return buffer.getvalue()

    def _sheet_xml(self, table: ReportTable) -> str:
        """Лист: первая строка — заголовки колонок, далее данные."""

        def column(index: int) -> str:
            letters = ""
            index += 1
            while index:
                index, rest = divmod(index - 1, 26)
                letters = chr(65 + rest) + letters
            return letters

        def cell(ref: str, value: Cell) -> str:
            if isinstance(value, (int, float)):
                return f'<c r="{ref}"><v>{value}</v></c>'
            return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'

        rows_xml: list[str] = []
        all_rows: list[tuple[Cell, ...]] = [table.columns, *table.rows]
        for r, row in enumerate(all_rows, start=1):
            cells = "".join(cell(f"{column(c)}{r}", v) for c, v in enumerate(row))
            rows_xml.append(f'<row r="{r}">{cells}</row>')
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
        )


def _sheet_name(title: str, number: int) -> str:
    """Имя листа: без запрещённых символов и не длиннее 31 знака."""
    cleaned = "".join(" " if ch in '[]:*?/\\' else ch for ch in title).strip()
    return (cleaned or f"Лист {number}")[:31]


class PdfExportStrategy(ExportStrategy):
    """PDF через внешний движок: стратегия собирает HTML, движок верстает PDF."""

    def __init__(self, renderer: PdfRenderer) -> None:
        self._renderer = renderer

    @property
    def format(self) -> ExportFormat:
        return ExportFormat.PDF

    @property
    def media_type(self) -> str:
        return "application/pdf"

    @property
    def extension(self) -> str:
        return "pdf"

    def render(self, document: ReportDocument) -> bytes:
        return self._renderer.render(self._to_html(document))

    def _to_html(self, document: ReportDocument) -> str:
        """HTML по шаблону дайджеста; весь текст экранируется."""
        parts = [
            '<!doctype html><html lang="ru"><head><meta charset="utf-8">',
            f"<title>{html.escape(document.title)}</title></head><body>",
            f"<h1>{html.escape(document.title)}</h1>",
            f"<p>Период: {html.escape(document.period.label())}</p>",
        ]
        for table in document.tables():
            head = "".join(f"<th>{html.escape(c)}</th>" for c in table.columns)
            body = "".join(
                "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>"
                for row in table.rows
            )
            parts.append(
                f"<h2>{html.escape(table.title)}</h2>"
                f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
            )
        parts.append("</body></html>")
        return "".join(parts)
