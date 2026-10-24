"""Демонстрация search_comp: одна и та же служба, три стратегии, подмена на лету.

Запуск из папки code/:  python -m backend.demo
"""

from __future__ import annotations

from uuid import UUID

from backend.prototype_adapters import (
    CollectingUsagePublisher,
    InMemoryFullTextSource,
    InMemorySearchCache,
    InMemorySemanticSource,
    demo_corpus,
)
from backend.search_comp import FullTextStrategy, HybridRRFStrategy, SearchService, SemanticStrategy
from shared.dto import FragmentHit, SearchFilters, UserContext


def show(title: str, hits: list[FragmentHit]) -> None:
    print(f"\n{title}")
    if not hits:
        print("  (ничего не найдено)")
    for position, hit in enumerate(hits, start=1):
        print(f"  {position}. [{hit.score:.4f}] {hit.title}")


def main() -> None:
    corpus = demo_corpus()
    fulltext_source = InMemoryFullTextSource(corpus)
    semantic_source = InMemorySemanticSource(corpus)
    usage = CollectingUsagePublisher()

    service = SearchService(
        strategy=HybridRRFStrategy(fulltext_source, semantic_source),
        cache=InMemorySearchCache(),
        usage=usage,
    )
    marketer = UserContext(user_id=UUID(int=7), roles=("marketer",), groups=("marketing", "sales"))
    query = "презентации кейс внедрения"

    for strategy in (FullTextStrategy(fulltext_source), SemanticStrategy(semantic_source), HybridRRFStrategy(fulltext_source, semantic_source)):
        service.set_strategy(strategy)
        show(f"Стратегия {strategy.name}: «{query}»", service.search(query, marketer, top_k=3))

    show("Повторный запрос (из кэша)", service.search(query, marketer, top_k=3))
    show("Фильтр: только кейсы", service.search(query, marketer, top_k=3, filters=SearchFilters(doc_types=("case",))))

    head = UserContext(user_id=UUID(int=8), roles=("marketing_head",), groups=("marketing", "management"))
    show("Маркетолог ищет «бюджет»", service.search("бюджет", marketer))
    show("Руководитель ищет «бюджет»", service.search("бюджет", head))

    print(f"\nСобытий usage.event: {len(usage.events)}; из кэша: {sum(e.from_cache for e in usage.events)}")


if __name__ == "__main__":
    main()
