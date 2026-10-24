"""Адаптеры прототипа в памяти — подменяют kb_repo_comp, index_comp и event_comp.

В сервисе на их месте PostgreSQL (tsvector), Qdrant + bge-m3, Redis и RabbitMQ.
Здесь — простые алгоритмы без внешних зависимостей, чтобы прототип запускался сразу.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from backend.search_comp.ports import UsageEvent
from backend.search_comp.query import AccessFilter, SearchQuery
from shared.dto import FragmentHit

_WORD = re.compile(r"[\w-]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


@dataclass(frozen=True, slots=True)
class StoredFragment:
    """Фрагмент документа с метаданными, которые знает только хранилище."""

    hit: FragmentHit
    project_id: UUID
    doc_type: str
    groups: frozenset[str]


def _allowed(fragment: StoredFragment, query: SearchQuery, access: AccessFilter) -> bool:
    filters = query.filters
    if not fragment.groups & access.groups:
        return False
    if filters.project_ids and fragment.project_id not in filters.project_ids:
        return False
    if filters.doc_types and fragment.doc_type not in filters.doc_types:
        return False
    if filters.date_from and fragment.hit.updated_at.date() < filters.date_from:
        return False
    return True


class InMemoryFullTextSource:
    """Полнотекстовый поиск: доля слов запроса, встретившихся во фрагменте."""

    def __init__(self, fragments: list[StoredFragment]) -> None:
        self._fragments = fragments

    def fulltext_search(self, query: SearchQuery, access: AccessFilter, limit: int) -> list[FragmentHit]:
        terms = set(_tokens(query.text))
        scored: list[FragmentHit] = []
        for fragment in self._fragments:
            if not _allowed(fragment, query, access):
                continue
            words = set(_tokens(fragment.hit.title + " " + fragment.hit.text))
            matched = len(terms & words)
            if matched:
                scored.append(replace(fragment.hit, score=round(matched / len(terms), 4)))
        scored.sort(key=lambda h: (-h.score, str(h.fragment_id)))
        return scored[:limit]


class InMemorySemanticSource:
    """«Семантический» поиск: косинусное сходство по символьным триграммам.

    Находит фрагменты и при другой форме слова («презентация» / «презентации»),
    чего не умеет точное совпадение слов. В сервисе вместо этого — bge-m3 и Qdrant.
    """

    def __init__(self, fragments: list[StoredFragment]) -> None:
        self._fragments = fragments

    @staticmethod
    def _vector(text: str) -> Counter[str]:
        grams: Counter[str] = Counter()
        for word in _tokens(text):
            padded = f"  {word} "
            grams.update(padded[i : i + 3] for i in range(len(padded) - 2))
        return grams

    @staticmethod
    def _cosine(a: Counter[str], b: Counter[str]) -> float:
        dot = sum(a[g] * b[g] for g in a.keys() & b.keys())
        norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
        return dot / norm if norm else 0.0

    def semantic_search(self, query: SearchQuery, access: AccessFilter, limit: int) -> list[FragmentHit]:
        q = self._vector(query.text)
        scored = [
            replace(f.hit, score=round(self._cosine(q, self._vector(f.hit.title + " " + f.hit.text)), 4))
            for f in self._fragments
            if _allowed(f, query, access)
        ]
        scored = [h for h in scored if h.score >= 0.2]
        scored.sort(key=lambda h: (-h.score, str(h.fragment_id)))
        return scored[:limit]


class InMemorySearchCache:
    """Кэш в словаре; время жизни для прототипа не отслеживается."""

    def __init__(self) -> None:
        self._data: dict[str, list[FragmentHit]] = {}
        self.ttl_by_key: dict[str, int] = {}

    def get(self, key: str) -> list[FragmentHit] | None:
        return self._data.get(key)

    def set(self, key: str, hits: list[FragmentHit], ttl: int) -> None:
        self._data[key] = list(hits)
        self.ttl_by_key[key] = ttl


class CollectingUsagePublisher:
    """Складывает события в список вместо RabbitMQ."""

    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    def publish(self, event: UsageEvent) -> None:
        self.events.append(event)


def demo_corpus() -> list[StoredFragment]:
    """Небольшая база знаний для демонстрации."""

    def frag(n: int, title: str, text: str, doc_type: str, groups: set[str], project: int) -> StoredFragment:
        return StoredFragment(
            hit=FragmentHit(
                fragment_id=UUID(int=n),
                document_id=UUID(int=100 + n),
                title=title,
                text=text,
                score=0.0,
                source_url=f"https://kb.example/docs/{100 + n}",
                updated_at=datetime(2026, 9, n),
            ),
            project_id=UUID(int=1000 + project),
            doc_type=doc_type,
            groups=frozenset(groups),
        )

    return [
        frag(1, "Кейс: внедрение ИИ-поиска в банке", "Платформа сократила подготовку презентаций для банка на 40 %.", "case", {"marketing", "sales"}, 1),
        frag(2, "Презентация продукта для ЦИПР", "Слайды с описанием ИИ-агента и генерации презентаций.", "presentation", {"marketing"}, 2),
        frag(3, "Коммерческое предложение для ритейла", "КП: тарифы SaaS-подписки и сроки внедрения в ритейле.", "kp", {"sales"}, 3),
        frag(4, "Отчёт о рынке корпоративного ИИ 2026", "Рынок решений управления знаниями растёт на 25 % в год.", "report", {"marketing", "management"}, 4),
        frag(5, "Кейс: промышленный холдинг", "Внедрение базы знаний в закрытом контуре с локальной LLM.", "case", {"sales"}, 5),
        frag(6, "Бюджет на маркетинг (конфиденциально)", "Бюджет на презентации и выставки на 2027 год.", "budget", {"management"}, 6),
    ]
