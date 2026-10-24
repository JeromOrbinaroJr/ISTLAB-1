"""Тесты модуля экспорта. Запуск из code/: python -m unittest discover -s analyst/tests -t ."""

from __future__ import annotations

import csv
import io
import unittest
import zipfile
from datetime import date
from xml.etree import ElementTree

from analyst.demo import sample_digest
from analyst.export_comp import (
    CsvExportStrategy,
    ExportFormat,
    ExportService,
    ExportStrategy,
    Period,
    PdfExportStrategy,
    ReportDocument,
    ReportValidationError,
    XlsxExportStrategy,
)
from analyst.export_comp.prototype_adapters import MinimalPdfRenderer, find_font


class FakePdfRenderer:
    """Заглушка движка PDF: запоминает HTML и возвращает метку."""

    def __init__(self) -> None:
        self.html = ""

    def render(self, html: str) -> bytes:
        self.html = html
        return b"%PDF-fake"


def all_strategies() -> list[ExportStrategy]:
    return [CsvExportStrategy(), XlsxExportStrategy(), PdfExportStrategy(FakePdfRenderer())]


class StrategyContractTest(unittest.TestCase):
    """Общий контракт для всех стратегий (подстановка Лисков)."""

    def test_every_strategy_renders_bytes_and_describes_itself(self) -> None:
        report = sample_digest()
        for strategy in all_strategies():
            with self.subTest(strategy=type(strategy).__name__):
                content = strategy.render(report)
                self.assertIsInstance(content, bytes)
                self.assertTrue(content)
                self.assertEqual(strategy.extension, strategy.format.value)
                self.assertTrue(strategy.media_type)


class CsvExportStrategyTest(unittest.TestCase):
    def test_bom_semicolon_cyrillic_and_decimal_comma(self) -> None:
        content = CsvExportStrategy().render(sample_digest())
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(rows[0], ["Еженедельный рыночный дайджест"])
        self.assertIn(["Среднее время подготовки материала", "37,50", "мин", "Маркетинг"], rows)


class XlsxExportStrategyTest(unittest.TestCase):
    def test_workbook_has_sheet_per_table_and_valid_xml(self) -> None:
        report = sample_digest()
        content = XlsxExportStrategy().render(report)
        with zipfile.ZipFile(io.BytesIO(content)) as book:
            names = book.namelist()
            self.assertIn("xl/workbook.xml", names)
            sheets = [n for n in names if n.startswith("xl/worksheets/")]
            self.assertEqual(len(sheets), len(report.tables()))
            for name in names:
                ElementTree.fromstring(book.read(name))  # каждый XML корректен
            self.assertIn("Поисков в базе знаний", book.read("xl/worksheets/sheet1.xml").decode())

    def test_output_is_reproducible(self) -> None:
        strategy = XlsxExportStrategy()
        self.assertEqual(strategy.render(sample_digest()), strategy.render(sample_digest()))


class PdfExportStrategyTest(unittest.TestCase):
    def test_passes_escaped_html_to_renderer(self) -> None:
        renderer = FakePdfRenderer()
        report = ReportDocument("Отчёт <script>", sample_digest().period, kpis=sample_digest().kpis)
        content = PdfExportStrategy(renderer).render(report)
        self.assertEqual(content, b"%PDF-fake")
        self.assertIn("Отчёт &lt;script&gt;", renderer.html)
        self.assertNotIn("<script>", renderer.html)

    @unittest.skipUnless(find_font(), "нет системного TTF-шрифта")
    def test_prototype_renderer_builds_pdf(self) -> None:
        content = PdfExportStrategy(MinimalPdfRenderer()).render(sample_digest())
        self.assertTrue(content.startswith(b"%PDF-"))
        self.assertTrue(content.rstrip().endswith(b"%%EOF"))


class ExportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ExportService(all_strategies(), default=ExportFormat.PDF)
        self.report = sample_digest()

    def test_switches_strategy_on_the_fly(self) -> None:
        self.assertIs(self.service.current_format, ExportFormat.PDF)
        content = self.service.export(self.report, ExportFormat.CSV)
        self.assertIs(self.service.current_format, ExportFormat.CSV)
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        self.service.export(self.report, ExportFormat.XLSX)
        self.assertIs(self.service.current_format, ExportFormat.XLSX)

    def test_set_strategy_replaces_implementation(self) -> None:
        class UpperCsv(CsvExportStrategy):
            def render(self, document: ReportDocument) -> bytes:
                return super().render(document).decode("utf-8-sig").upper().encode("utf-8-sig")

        self.service.set_strategy(UpperCsv())
        content = self.service.export(self.report, ExportFormat.CSV)
        self.assertIn("ЕЖЕНЕДЕЛЬНЫЙ", content.decode("utf-8-sig"))

    def test_content_type_and_filename(self) -> None:
        self.assertEqual(self.service.content_type(ExportFormat.PDF), "application/pdf")
        self.assertEqual(
            self.service.filename(self.report, ExportFormat.XLSX),
            "ezhenedelnyy_rynochnyy_daydzhest_20261012-20261018.xlsx",
        )

    def test_rejects_invalid_reports(self) -> None:
        period = self.report.period
        cases = {
            "без названия": ReportDocument("  ", period, kpis=self.report.kpis),
            "обратный период": ReportDocument(
                "Отчёт", Period(date(2026, 10, 18), date(2026, 10, 12)), kpis=self.report.kpis),
            "пустой": ReportDocument("Отчёт", period),
        }
        for name, document in cases.items():
            with self.subTest(name), self.assertRaises(ReportValidationError):
                self.service.export(document, ExportFormat.CSV)

    def test_unknown_format_and_bad_default(self) -> None:
        service = ExportService([CsvExportStrategy()], default=ExportFormat.CSV)
        with self.assertRaises(ReportValidationError):
            service.export(self.report, ExportFormat.PDF)
        with self.assertRaises(ValueError):
            ExportService([CsvExportStrategy()], default=ExportFormat.PDF)


if __name__ == "__main__":
    unittest.main()
