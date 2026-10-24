"""SearchService — контекст паттерна «Стратегия» и публичный интерфейс search_comp."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from backend.search_comp.ports import SearchCache, UsageEvent, UsagePublisher
from backend.search_comp.query import AccessFilter, SearchQuery
from backend.search_comp.strategies import SearchStrategy
from shared.dto import FragmentHit, SearchFilters, UserContext

logger = logging.getLogger(__name__)


class SearchService:
    """Выполняет поиск выбранной стратегией с учётом прав, кэшем и учётом использования.

    Сигнатура search(...) — внутренний контракт с kb_api_comp из ЛР2,
    её не меняем без согласования с тимлидом.
    """

    def __init__(
        self,
        strategy: SearchStrategy,
        cache: SearchCache,
        usage: UsagePublisher,
        cache_ttl: int = 300,
    ) -> None:
        if cache_ttl <= 0:
            raise ValueError("cache_ttl должен быть положительным")
        self._strategy = strategy
        self._cache = cache
        self._usage = usage
        self._cache_ttl = cache_ttl

    @property
    def strategy(self) -> SearchStrategy:
        """Текущая стратегия."""
        return self._strategy

    def set_strategy(self, strategy: SearchStrategy) -> None:
        """Подменяет алгоритм поиска во время работы."""
        self._strategy = strategy

    def search(
        self,
        query: str,
        user: UserContext,
        top_k: int = 8,
        filters: SearchFilters | None = None,
    ) -> list[FragmentHit]:
        """Ищет фрагменты, доступные пользователю; лучшие — первыми."""
        search_query = SearchQuery(text=query.strip(), top_k=top_k, filters=filters or SearchFilters())
        access = AccessFilter.from_user(user)
        key = self._cache_key(search_query, access)

        cached = self._cache.get(key)
        if cached is not None:
            self._report(user, search_query, len(cached), from_cache=True)
            return cached

        hits = self._strategy.search(search_query, access)
        self._cache.set(key, hits, self._cache_ttl)
        self._report(user, search_query, len(hits), from_cache=False)
        return hits

    def _cache_key(self, query: SearchQuery, access: AccessFilter) -> str:
        raw = "|".join(
            (
                self._strategy.name,
                query.text.lower(),
                str(query.top_k),
                repr(query.filters),
                access.cache_part(),
            )
        )
        return "search:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _report(self, user: UserContext, query: SearchQuery, results: int, *, from_cache: bool) -> None:
        event = UsageEvent(
            user_id=user.user_id,
            strategy=self._strategy.name,
            query_length=len(query.text),
            results=results,
            from_cache=from_cache,
            occurred_at=datetime.now(timezone.utc),
        )
        try:
            self._usage.publish(event)
        except Exception:  # аналитика не должна ломать поиск
            logger.warning("Не удалось опубликовать usage.event", exc_info=True)
