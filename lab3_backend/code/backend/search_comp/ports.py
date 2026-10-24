"""Порты сервиса поиска — интерфейсы, которые реализуют соседние компоненты core_api.

* FullTextSource  — реализует kb_repo_comp (полнотекстовый поиск в PostgreSQL);
* SemanticSource  — реализует index_comp (векторный поиск в Qdrant);
* SearchCache     — реализует index_comp (кэш в Redis);
* UsagePublisher  — реализует event_comp (событие usage.event в RabbitMQ).

Протоколы структурные (typing.Protocol): адаптеру не нужно наследоваться,
достаточно иметь методы с такими сигнатурами (принцип инверсии зависимостей).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from backend.search_comp.query import AccessFilter, SearchQuery
from shared.dto import FragmentHit


class FullTextSource(Protocol):
    """Источник полнотекстовых кандидатов."""

    def fulltext_search(self, query: SearchQuery, access: AccessFilter, limit: int) -> list[FragmentHit]:
        """Возвращает до limit фрагментов, отсортированных по убыванию релевантности."""
        ...


class SemanticSource(Protocol):
    """Источник семантических кандидатов."""

    def semantic_search(self, query: SearchQuery, access: AccessFilter, limit: int) -> list[FragmentHit]:
        """Возвращает до limit фрагментов, отсортированных по убыванию сходства."""
        ...


class SearchCache(Protocol):
    """Кэш результатов поиска."""

    def get(self, key: str) -> list[FragmentHit] | None:
        """Возвращает сохранённый результат или None."""
        ...

    def set(self, key: str, hits: list[FragmentHit], ttl: int) -> None:
        """Сохраняет результат на ttl секунд."""
        ...


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """Факт поиска для аналитики использования базы знаний (usage.event)."""

    user_id: UUID
    strategy: str
    query_length: int
    results: int
    from_cache: bool
    occurred_at: datetime


class UsagePublisher(Protocol):
    """Публикатор событий использования."""

    def publish(self, event: UsageEvent) -> None:
        """Отправляет событие; ошибки доставки не должны ломать поиск."""
        ...
