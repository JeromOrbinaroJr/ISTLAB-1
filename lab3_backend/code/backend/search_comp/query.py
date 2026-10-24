"""Объекты-значения, которые сервис поиска передаёт стратегиям."""

from __future__ import annotations

from dataclasses import dataclass

from backend.search_comp.errors import InvalidQueryError
from shared.dto import SearchFilters, UserContext

MAX_TOP_K = 50
MAX_QUERY_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Проверенный поисковый запрос."""

    text: str
    top_k: int
    filters: SearchFilters

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise InvalidQueryError("Поисковый запрос не может быть пустым")
        if len(self.text) > MAX_QUERY_LENGTH:
            raise InvalidQueryError(f"Запрос длиннее {MAX_QUERY_LENGTH} символов")
        if not 1 <= self.top_k <= MAX_TOP_K:
            raise InvalidQueryError(f"top_k должен быть от 1 до {MAX_TOP_K}")


@dataclass(frozen=True, slots=True)
class AccessFilter:
    """Группы, документы которых пользователю разрешено видеть (требование C-02)."""

    groups: frozenset[str]

    @classmethod
    def from_user(cls, user: UserContext) -> AccessFilter:
        """Строит фильтр прав по группам пользователя из токена."""
        return cls(groups=frozenset(user.groups))

    def cache_part(self) -> str:
        """Детерминированное представление групп для ключа кэша."""
        return ",".join(sorted(self.groups))
