"""Общие DTO платформы, которыми обмениваются компоненты разных контейнеров.

Владелец файла — тимлид. Поля совпадают с контрактами ЛР2
(UserContext, FragmentHit, SourceRef, MarketIndicator, SearchFilters).
В прототипе это неизменяемые dataclass без внешних зависимостей;
в сервисе те же поля описаны моделями Pydantic v2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserContext:
    """Пользователь, от имени которого выполняется запрос."""

    user_id: UUID
    roles: tuple[str, ...]
    groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Ссылка на источник в ответе ИИ-агента."""

    document_id: UUID
    title: str
    url: str
    fragment_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class FragmentHit:
    """Найденный фрагмент документа (результат поиска)."""

    fragment_id: UUID
    document_id: UUID
    title: str
    text: str
    score: float
    source_url: str
    updated_at: datetime

    def to_source_ref(self) -> SourceRef:
        """Превращает найденный фрагмент в ссылку на источник."""
        return SourceRef(
            document_id=self.document_id,
            title=self.title,
            url=self.source_url,
            fragment_id=self.fragment_id,
        )


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Необязательные фильтры поиска (контракт связи №43)."""

    project_ids: tuple[UUID, ...] = ()
    doc_types: tuple[str, ...] = ()
    date_from: date | None = None


@dataclass(frozen=True, slots=True)
class MarketIndicator:
    """Рыночный показатель (контракт связи №44)."""

    metric: str
    value: float
    unit: str
    period: str
    source: str
    source_url: str
