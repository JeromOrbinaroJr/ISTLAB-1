"""search_comp — сервис гибридного поиска контейнера core_api.

Алгоритм поиска и ранжирования вынесен в стратегии (паттерн «Стратегия»):
FullTextStrategy, SemanticStrategy, HybridRRFStrategy.
"""

from backend.search_comp.errors import InvalidQueryError
from backend.search_comp.ports import FullTextSource, SearchCache, SemanticSource, UsageEvent, UsagePublisher
from backend.search_comp.query import AccessFilter, SearchQuery
from backend.search_comp.service import SearchService
from backend.search_comp.strategies import (
    FullTextStrategy,
    HybridRRFStrategy,
    SearchStrategy,
    SemanticStrategy,
)

__all__ = [
    "AccessFilter",
    "FullTextSource",
    "FullTextStrategy",
    "HybridRRFStrategy",
    "InvalidQueryError",
    "SearchCache",
    "SearchQuery",
    "SearchService",
    "SearchStrategy",
    "SemanticSource",
    "SemanticStrategy",
    "UsageEvent",
    "UsagePublisher",
]
