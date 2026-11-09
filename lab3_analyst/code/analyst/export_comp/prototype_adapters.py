"""Адаптеры только для прототипа.

В сервисе порт PdfRenderer реализует WeasyPrint. Здесь — минимальный
движок на стандартной библиотеке: достаёт из HTML заголовки, абзацы и
строки таблиц и пишет их в PDF со встроенным TrueType-шрифтом системы,
чтобы кириллица отображалась без установки пакетов.
"""

from __future__ import annotations

import os
import struct
import zlib
from html.parser import HTMLParser
from pathlib import Path

FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
)


def find_font() -> str | None:
    """Ищет TrueType-шрифт с кириллицей: переменная EXPORT_PDF_FONT или системные пути."""
    env = os.environ.get("EXPORT_PDF_FONT")
    for path in ((env,) if env else ()) + FONT_CANDIDATES:
        if Path(path).is_file():
            return path
    return None


class _TrueTypeFont:
    """Минимальное чтение TTF: коды символов → глифы и ширины глифов."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        num_tables = struct.unpack_from(">H", data, 4)[0]
        self._tables: dict[str, int] = {}
        for i in range(int(num_tables)):
            tag, _check, offset, _length = struct.unpack_from(">4sLLL", data, 12 + 16 * i)
            self._tables[tag.decode("latin-1")] = int(offset)
        head = self._tables["head"]
        self.units_per_em = int(struct.unpack_from(">H", data, head + 18)[0])
        self.bbox = tuple(int(v) for v in struct.unpack_from(">hhhh", data, head + 36))
        hhea = self._tables["hhea"]
        self.ascent = int(struct.unpack_from(">h", data, hhea + 4)[0])
        self.descent = int(struct.unpack_from(">h", data, hhea + 6)[0])
        num_hmetrics = int(struct.unpack_from(">H", data, hhea + 34)[0])
        hmtx = self._tables["hmtx"]
        self._advances = [
            int(struct.unpack_from(">H", data, hmtx + 4 * i)[0]) for i in range(num_hmetrics)
        ]
        self._cmap = self._read_cmap()

    def _read_cmap(self) -> dict[int, int]:
        """Читает таблицу cmap Unicode (формат 12 или 4)."""
        base = self._tables["cmap"]
        count = int(struct.unpack_from(">H", self.data, base + 2)[0])
        subtables: dict[tuple[int, int], int] = {}
        for i in range(count):
            platform, encoding, offset = struct.unpack_from(">HHL", self.data, base + 4 + 8 * i)
            subtables[(int(platform), int(encoding))] = base + int(offset)
        if (3, 10) in subtables:
            return self._format12(subtables[(3, 10)])
        if (3, 1) in subtables:
            return self._format4(subtables[(3, 1)])
        raise ValueError("В шрифте нет таблицы Unicode cmap")

    def _format4(self, at: int) -> dict[int, int]:
        seg_count = int(struct.unpack_from(">H", self.data, at + 6)[0]) // 2
        ends = at + 14
        starts = ends + 2 * seg_count + 2
        deltas = starts + 2 * seg_count
        range_offsets = deltas + 2 * seg_count
        result: dict[int, int] = {}
        for s in range(seg_count):
            end = int(struct.unpack_from(">H", self.data, ends + 2 * s)[0])
            start = int(struct.unpack_from(">H", self.data, starts + 2 * s)[0])
            delta = int(struct.unpack_from(">h", self.data, deltas + 2 * s)[0])
            ro_pos = range_offsets + 2 * s
            range_offset = int(struct.unpack_from(">H", self.data, ro_pos)[0])
            for code in range(start, min(end, 0xFFFE) + 1):
                if range_offset == 0:
                    glyph = (code + delta) & 0xFFFF
                else:
                    addr = ro_pos + range_offset + 2 * (code - start)
                    glyph = int(struct.unpack_from(">H", self.data, addr)[0])
                    if glyph:
                        glyph = (glyph + delta) & 0xFFFF
                if glyph:
                    result[code] = glyph
        return result

    def _format12(self, at: int) -> dict[int, int]:
        groups = int(struct.unpack_from(">L", self.data, at + 12)[0])
        result: dict[int, int] = {}
        for g in range(groups):
            start, end, glyph = struct.unpack_from(">LLL", self.data, at + 16 + 12 * g)
            for code in range(int(start), min(int(end), 0x2FFFF) + 1):
                result[code] = int(glyph) + code - int(start)
        return result

    def glyph(self, ch: str) -> int:
        """Номер глифа для символа (0 — «нет символа»)."""
        return self._cmap.get(ord(ch), 0)

    def width(self, glyph: int) -> int:
        """Ширина глифа в единицах PDF (1/1000 кегля)."""
        advance = self._advances[min(glyph, len(self._advances) - 1)]
        return advance * 1000 // self.units_per_em


class _TextExtractor(HTMLParser):
    """Достаёт из HTML строки текста с кеглем: h1, h2, p и строки таблиц."""

    _SIZES = {"h1": 15.0, "h2": 12.0}

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[tuple[str, float]] = []
        self._buffer: list[str] = []
        self._cells: list[str] | None = None
        self._tag = "p"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("h1", "h2", "p"):
            self._tag, self._buffer = tag, []
        elif tag == "tr":
            self._cells = []
        elif tag in ("td", "th"):
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h1", "h2", "p"):
            if tag == "h2":
                self.lines.append(("", 6.0))
            self.lines.append(("".join(self._buffer).strip(), self._SIZES.get(tag, 9.5)))
        elif tag in ("td", "th") and self._cells is not None:
            self._cells.append("".join(self._buffer).strip())
        elif tag == "tr" and self._cells is not None:
            self.lines.append(("  |  ".join(self._cells), 9.5))
            self._cells = None

    def handle_data(self, data: str) -> None:
        self._buffer.append(data)


class MinimalPdfRenderer:
    """Прототипная реализация порта PdfRenderer (A4, один шрифт, перенос строк)."""

    _PAGE_W, _PAGE_H, _MARGIN = 595.0, 842.0, 50.0

    def __init__(self, font_path: str | None = None) -> None:
        path = font_path or find_font()
        if path is None:
            raise FileNotFoundError(
                "Не найден TrueType-шрифт с кириллицей; укажите путь в EXPORT_PDF_FONT"
            )
        self._font = _TrueTypeFont(Path(path).read_bytes())

    def render(self, html: str) -> bytes:
        extractor = _TextExtractor()
        extractor.feed(html)
        pages = self._layout(extractor.lines)
        return self._build_pdf(pages)

    def _text_width(self, text: str, size: float) -> float:
        return sum(self._font.width(self._font.glyph(ch)) for ch in text) * size / 1000

    def _wrap(self, text: str, size: float) -> list[str]:
        limit = self._PAGE_W - 2 * self._MARGIN
        lines: list[str] = []
        current = ""
        for word in text.split(" "):
            candidate = f"{current} {word}" if current else word
            if current and self._text_width(candidate, size) > limit:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
        return lines

    def _layout(self, lines: list[tuple[str, float]]) -> list[list[tuple[str, float, float]]]:
        """Раскладывает строки по страницам: (текст, кегль, y)."""
        pages: list[list[tuple[str, float, float]]] = [[]]
        y = self._PAGE_H - self._MARGIN
        for text, size in lines:
            for part in self._wrap(text, size):
                y -= size * 1.45
                if y < self._MARGIN:
                    pages.append([])
                    y = self._PAGE_H - self._MARGIN - size * 1.45
                if part:
                    pages[-1].append((part, size, y))
        return pages

    def _build_pdf(self, pages: list[list[tuple[str, float, float]]]) -> bytes:
        font = self._font
        used: dict[int, str] = {}
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        def stream(extra: str, payload: bytes) -> bytes:
            packed = zlib.compress(payload)
            head = f"<< /Length {len(packed)} /Filter /FlateDecode {extra}>>\nstream\n"
            return head.encode() + packed + b"\nendstream"

        contents: list[int] = []
        for page in pages:
            ops: list[str] = []
            for text, size, y in page:
                glyphs = [font.glyph(ch) for ch in text]
                for g, ch in zip(glyphs, text):
                    used.setdefault(g, ch)
                hexed = "".join(f"{g:04X}" for g in glyphs)
                ops.append(f"BT /F1 {size:.1f} Tf {self._MARGIN:.1f} {y:.1f} Td <{hexed}> Tj ET")
            contents.append(add(stream("", "\n".join(ops).encode("ascii"))))

        scale = 1000 / font.units_per_em
        x0, y0, x1, y1 = (int(v * scale) for v in font.bbox)
        file_id = add(stream(f"/Length1 {len(font.data)} ", font.data))
        descriptor = add(
            (f"<< /Type /FontDescriptor /FontName /ReportFont /Flags 32 "
             f"/FontBBox [{x0} {y0} {x1} {y1}] /ItalicAngle 0 "
             f"/Ascent {int(font.ascent * scale)} /Descent {int(font.descent * scale)} "
             f"/CapHeight {int(font.ascent * scale)} /StemV 80 /FontFile2 {file_id} 0 R >>").encode()
        )
        widths = " ".join(f"{g} [{font.width(g)}]" for g in sorted(used))
        cid_font = add(
            (f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /ReportFont "
             f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
             f"/FontDescriptor {descriptor} 0 R /W [{widths}] /CIDToGIDMap /Identity >>").encode()
        )
        bfchars = "\n".join(
            f"<{g:04X}> <{ch.encode('utf-16-be').hex().upper()}>"
            for g, ch in sorted(used.items())
        )
        cmap = (
            "/CIDInit /ProcSet findresource begin 12 dict begin begincmap "
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def "
            "/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
            "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
            f"{len(used)} beginbfchar\n{bfchars}\nendbfchar\n"
            "endcmap CMapName currentdict /CMap defineresource pop end end"
        )
        to_unicode = add(stream("", cmap.encode("ascii")))
        type0 = add(
            (f"<< /Type /Font /Subtype /Type0 /BaseFont /ReportFont /Encoding /Identity-H "
             f"/DescendantFonts [{cid_font} 0 R] /ToUnicode {to_unicode} 0 R >>").encode()
        )
        pages_id = len(objects) + len(contents) + 1
        page_ids = [
            add((f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {self._PAGE_W:.0f} "
                 f"{self._PAGE_H:.0f}] /Resources << /Font << /F1 {type0} 0 R >> >> "
                 f"/Contents {c} 0 R >>").encode())
            for c in contents
        ]
        kids = " ".join(f"{p} 0 R" for p in page_ids)
        add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
        catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets: list[int] = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
        out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        return bytes(out)
