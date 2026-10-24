"""Стратегии поиска и ранжирования (паттерн «Стратегия»).

Все стратегии реализуют один контракт SearchStrategy.search(...), поэтому
SearchService переключается между ними без изменения своего кода
(принцип открытости/закрытости). Новый алгоритм — новый класс.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from uuid import UUID

from backend.search_comp.ports import FullTextSource, SemanticSource
from backend.search_comp.query import AccessFilter, SearchQuery
from shared.dto import FragmentHit


class SearchStrategy(ABC):
    """Интерфейс стратегии: как найти и упорядочить фрагменты."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Короткое имя стратегии (для ключа кэша и аналитики)."""

    @abstractmethod
    def search(self, query: SearchQuery, access: AccessFilter) -> list[FragmentHit]:
        """Возвращает не более query.top_k фрагментов, лучшие — первыми."""


class FullTextStrategy(SearchStrategy):
    """Только полнотекстовый поиск: точные термины, артикулы, названия."""

    def __init__(self, source: FullTextSource) -> None:
        self._source = source

    @property
    def name(self) -> str:
        return "fulltext"

    def search(self, query: SearchQuery, access: AccessFilter) -> list[FragmentHit]:
        return self._source.fulltext_search(query, access, query.top_k)


class SemanticStrategy(SearchStrategy):
    """Только семантический поиск: вопросы на естественном языке."""

    def __init__(self, source: SemanticSource) -> None:
        self._source = source

    @property
    def name(self) -> str:
        return "semantic"

    def search(self, query: SearchQuery, access: AccessFilter) -> list[FragmentHit]:
        return self._source.semantic_search(query, access, query.top_k)


class HybridRRFStrategy(SearchStrategy):
    """Гибридный поиск: объединение двух списков методом Reciprocal Rank Fusion.

    Итоговая оценка фрагмента — сумма 1 / (k + позиция) по обоим спискам.
    Метод не требует приводить разные шкалы оценок к одной: важны только позиции.
    """

    def __init__(
        self,
        fulltext: FullTextSource,
        semantic: SemanticSource,
        k: int = 60,
        candidates_factor: int = 3,
    ) -> None:
        if k <= 0:
            raise ValueError("k должен быть положительным")
        if candidates_factor < 1:
            raise ValueError("candidates_factor должен быть не меньше 1")
        self._fulltext = fulltext
        self._semantic = semantic
        self._k = k
        self._candidates_factor = candidates_factor

    @property
    def name(self) -> str:
        return "hybrid_rrf"

    def search(self, query: SearchQuery, access: AccessFilter) -> list[FragmentHit]:
        limit = query.top_k * self._candidates_factor
        lexical = self._fulltext.fulltext_search(query, access, limit)
        semantic = self._semantic.semantic_search(query, access, limit)
        return self._fuse([lexical, semantic], query.top_k)

    def _fuse(self, ranked_lists: list[list[FragmentHit]], top_k: int) -> list[FragmentHit]:
        scores: dict[UUID, float] = {}
        best: dict[UUID, FragmentHit] = {}
        for ranked in ranked_lists:
            for position, hit in enumerate(ranked, start=1):
                scores[hit.fragment_id] = scores.get(hit.fragment_id, 0.0) + 1.0 / (self._k + position)
                best.setdefault(hit.fragment_id, hit)
        ordered = sorted(scores, key=lambda fid: (-scores[fid], str(fid)))
        return [replace(best[fid], score=round(scores[fid], 6)) for fid in ordered[:top_k]]
