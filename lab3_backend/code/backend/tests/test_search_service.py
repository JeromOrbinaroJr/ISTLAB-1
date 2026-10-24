"""Тесты search_comp. Запуск из папки code/:  python -m unittest discover -s backend/tests -t ."""

from __future__ import annotations

import unittest
from datetime import datetime
from uuid import UUID

from backend.prototype_adapters import (
    CollectingUsagePublisher,
    InMemoryFullTextSource,
    InMemorySearchCache,
    InMemorySemanticSource,
    demo_corpus,
)
from backend.search_comp import (
    AccessFilter,
    FullTextStrategy,
    HybridRRFStrategy,
    InvalidQueryError,
    SearchQuery,
    SearchService,
    SearchStrategy,
    SemanticStrategy,
)
from backend.search_comp.ports import UsageEvent
from shared.dto import FragmentHit, SearchFilters, UserContext

MARKETER = UserContext(user_id=UUID(int=7), roles=("marketer",), groups=("marketing", "sales"))


def hit(n: int) -> FragmentHit:
    return FragmentHit(
        fragment_id=UUID(int=n), document_id=UUID(int=n), title=f"Doc {n}", text="",
        score=0.0, source_url="", updated_at=datetime(2026, 1, 1),
    )


class FixedSource:
    """Источник, возвращающий заранее заданный порядок; считает вызовы."""

    def __init__(self, order: list[int]) -> None:
        self.order = order
        self.calls = 0

    def fulltext_search(self, query: SearchQuery, access: AccessFilter, limit: int) -> list[FragmentHit]:
        self.calls += 1
        return [hit(n) for n in self.order][:limit]

    def semantic_search(self, query: SearchQuery, access: AccessFilter, limit: int) -> list[FragmentHit]:
        return self.fulltext_search(query, access, limit)


class FailingPublisher:
    def publish(self, event: UsageEvent) -> None:
        raise ConnectionError("RabbitMQ недоступен")


def make_service(strategy: SearchStrategy) -> tuple[SearchService, CollectingUsagePublisher]:
    usage = CollectingUsagePublisher()
    return SearchService(strategy, InMemorySearchCache(), usage), usage


class StrategyTests(unittest.TestCase):
    def test_rrf_rewards_documents_found_by_both_sources(self) -> None:
        strategy = HybridRRFStrategy(FixedSource([1, 2, 3]), FixedSource([3, 4, 1]))
        query = SearchQuery("x", 3, SearchFilters())
        ids = [h.fragment_id.int for h in strategy.search(query, AccessFilter(frozenset({"g"})))]
        self.assertEqual(ids[:2], [1, 3])
        self.assertEqual(len(ids), 3)

    def test_rrf_requests_more_candidates_than_top_k(self) -> None:
        source = FixedSource(list(range(1, 20)))
        HybridRRFStrategy(source, FixedSource([]), candidates_factor=3).search(
            SearchQuery("x", 4, SearchFilters()), AccessFilter(frozenset())
        )
        self.assertEqual(source.calls, 1)

    def test_strategies_share_one_contract(self) -> None:
        corpus = demo_corpus()
        for strategy in (
            FullTextStrategy(InMemoryFullTextSource(corpus)),
            SemanticStrategy(InMemorySemanticSource(corpus)),
            HybridRRFStrategy(InMemoryFullTextSource(corpus), InMemorySemanticSource(corpus)),
        ):
            hits = strategy.search(SearchQuery("кейс внедрения", 2, SearchFilters()), AccessFilter.from_user(MARKETER))
            self.assertLessEqual(len(hits), 2, strategy.name)
            self.assertTrue(all(isinstance(h, FragmentHit) for h in hits))


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        corpus = demo_corpus()
        self.fulltext = FullTextStrategy(InMemoryFullTextSource(corpus))
        self.semantic = SemanticStrategy(InMemorySemanticSource(corpus))

    def test_set_strategy_changes_algorithm(self) -> None:
        service, _ = make_service(self.fulltext)
        service.set_strategy(self.semantic)
        self.assertIs(service.strategy, self.semantic)
        service.search("презентация", MARKETER)

    def test_access_filter_hides_foreign_documents(self) -> None:
        service, _ = make_service(self.fulltext)
        titles = [h.title for h in service.search("бюджет", MARKETER)]
        self.assertEqual(titles, [])
        head = UserContext(UUID(int=8), ("marketing_head",), ("management",))
        self.assertTrue(service.search("бюджет", head))

    def test_second_call_comes_from_cache(self) -> None:
        service, usage = make_service(self.fulltext)
        first = service.search("кейс", MARKETER)
        second = service.search("кейс", MARKETER)
        self.assertEqual(first, second)
        self.assertEqual([e.from_cache for e in usage.events], [False, True])

    def test_cache_key_depends_on_strategy(self) -> None:
        service, usage = make_service(self.fulltext)
        service.search("кейс", MARKETER)
        service.set_strategy(self.semantic)
        service.search("кейс", MARKETER)
        self.assertEqual([e.from_cache for e in usage.events], [False, False])

    def test_filters_are_passed_to_sources(self) -> None:
        service, _ = make_service(self.fulltext)
        hits = service.search("кейс", MARKETER, filters=SearchFilters(doc_types=("kp",)))
        self.assertEqual(hits, [])

    def test_invalid_queries_are_rejected(self) -> None:
        service, _ = make_service(self.fulltext)
        with self.assertRaises(InvalidQueryError):
            service.search("   ", MARKETER)
        with self.assertRaises(InvalidQueryError):
            service.search("кейс", MARKETER, top_k=0)

    def test_publisher_failure_does_not_break_search(self) -> None:
        service = SearchService(self.fulltext, InMemorySearchCache(), FailingPublisher())
        with self.assertLogs("backend.search_comp.service", level="WARNING"):
            self.assertTrue(service.search("кейс", MARKETER))


if __name__ == "__main__":
    unittest.main()
