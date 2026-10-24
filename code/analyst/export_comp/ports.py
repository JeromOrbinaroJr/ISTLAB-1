"""Порт к движку PDF: в сервисе его реализует WeasyPrint, в прототипе — адаптер."""

from __future__ import annotations

from typing import Protocol


class PdfRenderer(Protocol):
    """Превращает HTML-разметку в PDF."""

    def render(self, html: str) -> bytes:
        """Возвращает байты PDF-документа."""
        ...
