"""Наглядная демонстрация search_comp в браузере.

Запуск из папки code/:  python -m backend.web_demo
Откроется страница http://127.0.0.1:8765 — выбираешь роль, алгоритм и запрос,
справа видны результаты и пошаговый разбор работы алгоритма.
Только стандартная библиотека Python. Остановить сервер — Ctrl+C.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID

from backend.prototype_adapters import (
    CollectingUsagePublisher,
    InMemoryFullTextSource,
    InMemorySemanticSource,
    StoredFragment,
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
from shared.dto import FragmentHit, SearchFilters, UserContext

HOST = "127.0.0.1"
PORT = 8765
RRF_K = 60
CANDIDATES_FACTOR = 3

ROLES: dict[str, tuple[str, UserContext]] = {
    "marketer": ("Маркетолог", UserContext(UUID(int=7), ("marketer",), ("marketing", "sales"))),
    "head": ("Руководитель маркетинга", UserContext(UUID(int=8), ("marketing_head",), ("marketing", "management"))),
    "sales": ("Менеджер по развитию бизнеса", UserContext(UUID(int=9), ("bd_manager",), ("sales",))),
}

STRATEGY_TITLES = {
    "fulltext": "Полнотекстовый",
    "semantic": "Семантический",
    "hybrid_rrf": "Гибридный (RRF)",
}


# ---------- трассирующие обёртки над портами: записывают, что происходило ----------


@dataclass
class SourceCall:
    """Один вызов источника кандидатов."""

    source: str
    limit: int
    hits: list[FragmentHit]


@dataclass
class Trace:
    """Всё, что произошло за один поиск."""

    source_calls: list[SourceCall] = field(default_factory=list)
    cache_hit: bool | None = None
    cache_key: str = ""


class TracingFullTextSource:
    """Порт FullTextSource, который записывает каждый вызов."""

    def __init__(self, inner: InMemoryFullTextSource, trace: Trace) -> None:
        self._inner = inner
        self.trace = trace

    def fulltext_search(self, query: SearchQuery, access: AccessFilter, limit: int) -> list[FragmentHit]:
        hits = self._inner.fulltext_search(query, access, limit)
        self.trace.source_calls.append(SourceCall("fulltext", limit, hits))
        return hits


class TracingSemanticSource:
    """Порт SemanticSource, который записывает каждый вызов."""

    def __init__(self, inner: InMemorySemanticSource, trace: Trace) -> None:
        self._inner = inner
        self.trace = trace

    def semantic_search(self, query: SearchQuery, access: AccessFilter, limit: int) -> list[FragmentHit]:
        hits = self._inner.semantic_search(query, access, limit)
        self.trace.source_calls.append(SourceCall("semantic", limit, hits))
        return hits


class TracingCache:
    """Порт SearchCache в памяти, который отмечает попадания и промахи."""

    def __init__(self, trace: Trace) -> None:
        self._data: dict[str, list[FragmentHit]] = {}
        self.trace = trace

    def get(self, key: str) -> list[FragmentHit] | None:
        found = self._data.get(key)
        self.trace.cache_hit = found is not None
        self.trace.cache_key = key
        return found

    def set(self, key: str, hits: list[FragmentHit], ttl: int) -> None:
        self._data[key] = list(hits)

    def clear(self) -> int:
        size = len(self._data)
        self._data.clear()
        return size


# ---------- сборка демонстрационного компонента ----------


class DemoApp:
    """Один SearchService на всё приложение: стратегия подменяется через set_strategy."""

    def __init__(self) -> None:
        self.corpus: list[StoredFragment] = demo_corpus()
        self.by_id = {f.hit.fragment_id: f for f in self.corpus}
        self.trace = Trace()
        self.fulltext = TracingFullTextSource(InMemoryFullTextSource(self.corpus), self.trace)
        self.semantic = TracingSemanticSource(InMemorySemanticSource(self.corpus), self.trace)
        self.strategies: dict[str, SearchStrategy] = {
            "fulltext": FullTextStrategy(self.fulltext),
            "semantic": SemanticStrategy(self.semantic),
            "hybrid_rrf": HybridRRFStrategy(self.fulltext, self.semantic, k=RRF_K, candidates_factor=CANDIDATES_FACTOR),
        }
        self.cache = TracingCache(self.trace)
        self.usage = CollectingUsagePublisher()
        self.service = SearchService(self.strategies["hybrid_rrf"], self.cache, self.usage)
        self.lock = threading.Lock()

    def _reset_trace(self) -> None:
        self.trace.source_calls.clear()
        self.trace.cache_hit = None
        self.trace.cache_key = ""

    def _hit_json(self, hit: FragmentHit) -> dict[str, Any]:
        stored = self.by_id[hit.fragment_id]
        return {
            "id": hit.fragment_id.int,
            "title": hit.title,
            "text": hit.text,
            "score": hit.score,
            "doc_type": stored.doc_type,
            "groups": sorted(stored.groups),
        }

    def search(self, role: str, strategy: str, query: str, top_k: int, doc_types: list[str]) -> dict[str, Any]:
        """Выполняет поиск и возвращает результат вместе с пошаговым разбором."""
        title, user = ROLES[role]
        with self.lock:
            previous = self.service.strategy.name
            self.service.set_strategy(self.strategies[strategy])
            self._reset_trace()
            filters = SearchFilters(doc_types=tuple(doc_types))
            try:
                hits = self.service.search(query, user, top_k=top_k, filters=filters)
            except InvalidQueryError as error:
                return {"error": str(error), "steps": [{"kind": "error", "title": "Проверка запроса", "text": str(error)}]}
            calls = list(self.trace.source_calls)
            cache_hit = bool(self.trace.cache_hit)
            cache_key = self.trace.cache_key
            event = self.usage.events[-1] if self.usage.events else None

        access = AccessFilter.from_user(user)
        hidden = [f.hit.title for f in self.corpus if not f.groups & access.groups]
        steps: list[dict[str, Any]] = [
            {"kind": "ok", "title": "1. Проверка запроса — SearchQuery",
             "text": f"Текст «{query.strip()}», top_k = {top_k}, фильтр типов: {', '.join(doc_types) or 'нет'}. Запрос корректен."},
            {"kind": "info", "title": "2. Права доступа — AccessFilter.from_user",
             "text": f"Роль «{title}», группы: {', '.join(sorted(access.groups))}. "
                     + (f"Скрыто от этой роли документов: {len(hidden)} ({'; '.join(hidden)})." if hidden else "Этой роли доступны все документы.")},
            {"kind": "strategy", "title": "3. Стратегия — set_strategy",
             "text": (f"Стратегия заменена: {STRATEGY_TITLES[previous]} → {STRATEGY_TITLES[strategy]}. Код SearchService при этом не менялся."
                      if previous != strategy else f"Текущая стратегия: {STRATEGY_TITLES[strategy]}.")},
            {"kind": "hit" if cache_hit else "info", "title": "4. Кэш — SearchCache.get",
             "text": ("Попадание: такой запрос уже выполнялся этой стратегией для этих групп. Ответ взят из кэша, стратегия не вызывалась."
                      if cache_hit else "Промах: такого запроса в кэше нет, вызываем стратегию.")
                     + f" Ключ: {cache_key[:22]}…"},
        ]
        detail: dict[str, Any] = {"kind": strategy, "calls": [], "rrf": []}
        if not cache_hit:
            for call in calls:
                detail["calls"].append({
                    "source": call.source,
                    "limit": call.limit,
                    "hits": [{"pos": i, "title": h.title, "score": h.score} for i, h in enumerate(call.hits, start=1)],
                })
            if strategy == "hybrid_rrf":
                detail["rrf"] = self._rrf_breakdown(calls, hits)
            steps.append({"kind": "algo", "title": f"5. Алгоритм — {type(self.strategies[strategy]).__name__}.search",
                          "text": self._algo_text(strategy, top_k), "detail": detail})
            steps.append({"kind": "ok", "title": "6. Сохранение — SearchCache.set",
                          "text": "Результат сохранён в кэш на 300 секунд."})
        if event is not None:
            steps.append({"kind": "event", "title": f"{len(steps) + 1}. Аналитика — UsagePublisher.publish",
                          "text": f"Событие usage.event: стратегия {event.strategy}, результатов {event.results}, из кэша: {'да' if event.from_cache else 'нет'}. Всего событий: {len(self.usage.events)}."})
        return {
            "role": title,
            "groups": sorted(access.groups),
            "strategy": strategy,
            "strategy_title": STRATEGY_TITLES[strategy],
            "from_cache": cache_hit,
            "results": [self._hit_json(h) for h in hits],
            "steps": steps,
            "events": len(self.usage.events),
        }

    @staticmethod
    def _algo_text(strategy: str, top_k: int) -> str:
        if strategy == "fulltext":
            return f"Ищем точные слова запроса. Оценка = доля слов запроса, найденных во фрагменте. Берём {top_k} лучших."
        if strategy == "semantic":
            return (f"Ищем по смыслу: сравниваем «отпечатки» текста (в прототипе — буквенные триграммы, в сервисе — векторы bge-m3 в Qdrant). "
                    f"Оценка = сходство от 0 до 1. Берём {top_k} лучших.")
        return (f"Запрашиваем у обоих источников по {top_k * CANDIDATES_FACTOR} кандидатов (top_k × {CANDIDATES_FACTOR}), "
                f"затем объединяем методом Reciprocal Rank Fusion: оценка = сумма 1 / ({RRF_K} + место) по каждому списку.")

    @staticmethod
    def _rrf_breakdown(calls: list[SourceCall], hits: list[FragmentHit]) -> list[dict[str, Any]]:
        positions: dict[str, dict[UUID, int]] = {
            c.source: {h.fragment_id: i for i, h in enumerate(c.hits, start=1)} for c in calls
        }
        rows: list[dict[str, Any]] = []
        for place, hit in enumerate(hits, start=1):
            row: dict[str, Any] = {"place": place, "title": hit.title, "total": hit.score}
            for source in ("fulltext", "semantic"):
                pos = positions.get(source, {}).get(hit.fragment_id)
                row[source] = None if pos is None else {"pos": pos, "part": round(1 / (RRF_K + pos), 5)}
            rows.append(row)
        return rows

    def compare(self, role: str, query: str, top_k: int, doc_types: list[str]) -> dict[str, Any]:
        """Один запрос всеми тремя стратегиями — для сравнения рядом."""
        columns = []
        for name in ("fulltext", "semantic", "hybrid_rrf"):
            result = self.search(role, name, query, top_k, doc_types)
            columns.append({"strategy": name, "title": STRATEGY_TITLES[name],
                            "results": result.get("results", []), "from_cache": result.get("from_cache", False),
                            "error": result.get("error")})
        return {"columns": columns}

    def clear_cache(self) -> dict[str, Any]:
        with self.lock:
            return {"cleared": self.cache.clear()}

    def corpus_json(self) -> dict[str, Any]:
        return {
            "roles": [{"id": k, "title": v[0], "groups": list(v[1].groups)} for k, v in ROLES.items()],
            "documents": [
                {"title": f.hit.title, "doc_type": f.doc_type, "groups": sorted(f.groups)} for f in self.corpus
            ],
            "doc_types": sorted({f.doc_type for f in self.corpus}),
        }


APP = DemoApp()


class Handler(BaseHTTPRequestHandler):
    """HTTP-обработчик: отдаёт страницу и JSON-API для неё."""

    def log_message(self, format: str, *args: Any) -> None:  # тихий сервер
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: dict[str, Any], status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/corpus":
            self._json(APP.corpus_json())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload: dict[str, Any] = json.loads(self.rfile.read(length) or b"{}")
        role = str(payload.get("role", "marketer"))
        query = str(payload.get("query", ""))
        top_k = int(payload.get("top_k", 3))
        doc_types = [str(t) for t in payload.get("doc_types", [])]
        if role not in ROLES:
            self._json({"error": "Неизвестная роль"}, 400)
        elif self.path == "/api/search":
            strategy = str(payload.get("strategy", "hybrid_rrf"))
            if strategy not in STRATEGY_TITLES:
                self._json({"error": "Неизвестная стратегия"}, 400)
            else:
                self._json(APP.search(role, strategy, query, top_k, doc_types))
        elif self.path == "/api/compare":
            self._json(APP.compare(role, query, top_k, doc_types))
        elif self.path == "/api/clear_cache":
            self._json(APP.clear_cache())
        else:
            self._json({"error": "not found"}, 404)


PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>search_comp — демонстрация</title>
<style>
:root{--bg:#f4f6fa;--panel:#fff;--ink:#1b2333;--muted:#5b6578;--line:#dde3ec;--acc:#1f5fbf;--acc2:#e8f0fc;
--ok:#1d7a46;--okbg:#e6f4ec;--warn:#9a5b00;--warnbg:#fff3df;--evt:#6b3fa0;--evtbg:#f1eafa;--err:#b3261e;--errbg:#fdecea}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 "Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#14213d;color:#fff;padding:14px 24px}header h1{margin:0;font-size:18px;font-weight:600}
header p{margin:2px 0 0;color:#b9c3d6;font-size:13px}
main{display:grid;grid-template-columns:330px 1fr;gap:18px;padding:18px 24px;max-width:1500px;margin:0 auto}
@media(max-width:900px){main{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 10px}
.group{margin-bottom:18px}
.opt{display:block;border:1px solid var(--line);border-radius:8px;padding:9px 11px;margin-bottom:7px;cursor:pointer}
.opt:hover{border-color:#b7c4d8}.opt input{margin-right:8px}
.opt.sel{border-color:var(--acc);background:var(--acc2)}
.opt small{display:block;color:var(--muted);margin-left:24px}
input[type=text]{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:8px;font:inherit}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{border:1px solid var(--line);background:#fff;border-radius:14px;padding:3px 10px;font-size:12px;cursor:pointer}
.chip:hover{border-color:var(--acc);color:var(--acc)}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.types label{border:1px solid var(--line);border-radius:6px;padding:3px 8px;font-size:12px;cursor:pointer}
select{padding:6px;border:1px solid var(--line);border-radius:6px;font:inherit}
button{font:inherit;border-radius:8px;padding:9px 14px;cursor:pointer;border:1px solid var(--acc)}
.primary{background:var(--acc);color:#fff;width:100%;font-weight:600}
.secondary{background:#fff;color:var(--acc)}
.btns{display:grid;gap:8px}
.summary{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.badge{background:var(--acc2);color:var(--acc);border-radius:12px;padding:3px 10px;font-size:12px;font-weight:600}
.badge.cache{background:var(--okbg);color:var(--ok)}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600}td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.bar{height:6px;background:var(--acc2);border-radius:3px;margin-top:4px}.bar i{display:block;height:6px;background:var(--acc);border-radius:3px}
.tag{font-size:11px;border-radius:4px;padding:1px 6px;background:#eef1f6;color:var(--muted);margin-right:3px}
.empty{color:var(--muted);padding:14px 0}
.steps{display:grid;gap:8px;margin-top:6px}
.step{border-left:4px solid var(--line);background:#fafbfd;border-radius:6px;padding:9px 12px}
.step b{display:block;margin-bottom:2px}
.step.ok{border-color:var(--ok);background:var(--okbg)}.step.hit{border-color:var(--ok);background:var(--okbg)}
.step.info{border-color:var(--acc);background:var(--acc2)}.step.strategy{border-color:var(--warn);background:var(--warnbg)}
.step.algo{border-color:#14213d;background:#fff}.step.event{border-color:var(--evt);background:var(--evtbg)}
.step.error{border-color:var(--err);background:var(--errbg)}
.cands{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;margin-top:8px}
.cands h4{margin:0 0 4px;font-size:12px;color:var(--muted)}
.cands table td,.rrf td{padding:4px 6px;font-size:12.5px}
.rrf{margin-top:10px}.rrf th{padding:4px 6px}
.cmp{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}@media(max-width:1100px){.cmp{grid-template-columns:1fr}}
.cmp ol{margin:6px 0 0;padding-left:20px}.cmp li{margin-bottom:4px}
.docs td{font-size:12.5px}.lock{color:var(--err)}
.hidden{display:none}
</style></head><body>
<header><h1>Сервис гибридного поиска search_comp — паттерн «Стратегия»</h1>
<p>Выбери роль и алгоритм поиска: справа — результат и пошаговый разбор того, как его получил SearchService</p></header>
<main>
<section class="panel">
  <div class="group"><h2>Роль пользователя</h2><div id="roles"></div></div>
  <div class="group"><h2>Алгоритм (стратегия)</h2><div id="strategies"></div></div>
  <div class="group"><h2>Запрос</h2>
    <input id="query" type="text" value="презентации кейс внедрения" aria-label="Поисковый запрос">
    <div class="chips" id="presets"></div></div>
  <div class="group"><h2>Фильтры</h2>
    <div class="row types" id="types"></div>
    <div class="row" style="margin-top:8px"><label for="topk">Сколько результатов (top_k):</label>
      <select id="topk"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select></div></div>
  <div class="btns">
    <button class="primary" id="go">Найти</button>
    <button class="secondary" id="cmp">Сравнить все три стратегии</button>
    <button class="secondary" id="clear">Очистить кэш</button>
  </div>
</section>
<section>
  <div class="panel" id="resultPanel">
    <div class="summary" id="summary"></div>
    <h2>Результаты</h2><div id="results" class="empty">Нажми «Найти».</div>
  </div>
  <div class="panel" style="margin-top:14px"><h2>Как работал алгоритм</h2><div class="steps" id="steps"><div class="empty">Здесь появятся шаги SearchService.</div></div></div>
  <div class="panel hidden" id="cmpPanel" style="margin-top:14px"><h2>Сравнение стратегий на одном запросе</h2><div class="cmp" id="cmpBody"></div></div>
  <div class="panel" style="margin-top:14px"><h2>База знаний демонстрации</h2><table class="docs" id="docs"></table></div>
</section>
</main>
<script>
const STRATS=[["fulltext","Полнотекстовый","FullTextStrategy — точные слова запроса"],
["semantic","Семантический","SemanticStrategy — поиск по смыслу"],
["hybrid_rrf","Гибридный (RRF)","HybridRRFStrategy — объединяет оба списка"]];
const PRESETS=["презентации кейс внедрения","бюджет","тарифы SaaS","рынок знаний","закрытый контур"];
let corpus=null;
const $=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function radios(el,name,items,checked){el.innerHTML=items.map(([v,t,s])=>`<label class="opt${v===checked?" sel":""}"><input type="radio" name="${name}" value="${v}"${v===checked?" checked":""}>${esc(t)}<small>${esc(s)}</small></label>`).join("");
 el.querySelectorAll("input").forEach(i=>i.addEventListener("change",()=>{el.querySelectorAll(".opt").forEach(o=>o.classList.toggle("sel",o.querySelector("input").checked));search();}));}
const val=n=>document.querySelector(`input[name=${n}]:checked`).value;
function params(){return{role:val("role"),strategy:val("strat"),query:$("#query").value,top_k:+$("#topk").value,
 doc_types:[...document.querySelectorAll("#types input:checked")].map(i=>i.value)}}
async function post(url,body){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})});return r.json()}
function resultsTable(rows,max){if(!rows.length)return'<div class="empty">Ничего не найдено — либо нет совпадений, либо документы скрыты правами доступа.</div>';
 const m=max||Math.max(...rows.map(r=>r.score),1e-9);
 return`<table><tr><th>#</th><th>Документ</th><th>Тип</th><th>Доступ</th><th>Оценка</th></tr>${rows.map((r,i)=>`<tr><td>${i+1}</td><td><b>${esc(r.title)}</b><br><span style="color:var(--muted)">${esc(r.text)}</span></td><td><span class="tag">${esc(r.doc_type)}</span></td><td>${r.groups.map(g=>`<span class="tag">${esc(g)}</span>`).join("")}</td><td class="num">${r.score.toFixed(4)}<div class="bar"><i style="width:${Math.max(4,100*r.score/m)}%"></i></div></td></tr>`).join("")}</table>`}
function srcName(s){return s==="fulltext"?"Полнотекстовый источник (FullTextSource)":"Семантический источник (SemanticSource)"}
function detailHtml(d){if(!d)return"";let h='<div class="cands">'+d.calls.map(c=>`<div><h4>${srcName(c.source)} — запрошено ${c.limit}, найдено ${c.hits.length}</h4><table>${c.hits.map(x=>`<tr><td>${x.pos}</td><td>${esc(x.title)}</td><td class="num">${x.score.toFixed(4)}</td></tr>`).join("")||'<tr><td>—</td></tr>'}</table></div>`).join("")+"</div>";
 if(d.rrf&&d.rrf.length){const cell=p=>p?`место ${p.pos} → 1/(60+${p.pos}) = ${p.part.toFixed(5)}`:'<span style="color:var(--muted)">не найден → 0</span>';
 h+=`<table class="rrf"><tr><th>Итог</th><th>Документ</th><th>Полнотекстовый</th><th>Семантический</th><th>Сумма RRF</th></tr>${d.rrf.map(r=>`<tr><td>${r.place}</td><td>${esc(r.title)}</td><td>${cell(r.fulltext)}</td><td>${cell(r.semantic)}</td><td class="num"><b>${r.total.toFixed(5)}</b></td></tr>`).join("")}</table>`}
 return h}
async function search(){$("#cmpPanel").classList.add("hidden");const d=await post("/api/search",params());
 if(d.error){$("#summary").innerHTML="";$("#results").innerHTML=`<div class="empty" style="color:var(--err)">${esc(d.error)}</div>`;}
 else{$("#summary").innerHTML=`<span class="badge">${esc(d.role)}</span><span class="badge">группы: ${esc(d.groups.join(", "))}</span><span class="badge">${esc(d.strategy_title)}</span>${d.from_cache?'<span class="badge cache">ответ из кэша</span>':''}<span class="badge">событий usage.event: ${d.events}</span>`;
 $("#results").innerHTML=resultsTable(d.results);$("#results").classList.remove("empty");}
 $("#steps").innerHTML=d.steps.map(s=>`<div class="step ${s.kind}"><b>${esc(s.title)}</b>${esc(s.text)}${detailHtml(s.detail)}</div>`).join("");}
async function compare(){await search();const p=params();const d=await post("/api/compare",p);$("#cmpPanel").classList.remove("hidden");
 $("#cmpBody").innerHTML=d.columns.map(c=>`<div class="panel" style="padding:12px"><b>${esc(c.title)}</b>${c.from_cache?' <span class="badge cache">кэш</span>':''}${c.error?`<div style="color:var(--err)">${esc(c.error)}</div>`:c.results.length?`<ol>${c.results.map(r=>`<li>${esc(r.title)} <span style="color:var(--muted)">(${r.score.toFixed(4)})</span></li>`).join("")}</ol>`:'<div class="empty">ничего не найдено</div>'}</div>`).join("");
 $("#cmpPanel").scrollIntoView({behavior:"smooth"});}
function renderDocs(){const role=corpus.roles.find(r=>r.id===val("role"));
 $("#docs").innerHTML=`<tr><th>Документ</th><th>Тип</th><th>Группы доступа</th><th>Видит ${esc(role.title.toLowerCase())}?</th></tr>`+corpus.documents.map(d=>{const ok=d.groups.some(g=>role.groups.includes(g));return`<tr><td>${esc(d.title)}</td><td><span class="tag">${esc(d.doc_type)}</span></td><td>${d.groups.map(g=>`<span class="tag">${esc(g)}</span>`).join("")}</td><td>${ok?"да":'<span class="lock">нет, скрыт правами</span>'}</td></tr>`}).join("")}
(async()=>{corpus=await (await fetch("/api/corpus")).json();
 radios($("#roles"),"role",corpus.roles.map(r=>[r.id,r.title,"группы: "+r.groups.join(", ")]),"marketer");
 radios($("#strategies"),"strat",STRATS,"hybrid_rrf");
 document.querySelectorAll("input[name=role]").forEach(i=>i.addEventListener("change",renderDocs));
 $("#presets").innerHTML=PRESETS.map(p=>`<button class="chip" type="button">${esc(p)}</button>`).join("");
 $("#presets").querySelectorAll(".chip").forEach(b=>b.addEventListener("click",()=>{$("#query").value=b.textContent;search();}));
 $("#types").innerHTML=corpus.doc_types.map(t=>`<label><input type="checkbox" value="${esc(t)}"> ${esc(t)}</label>`).join("");
 $("#types").querySelectorAll("input").forEach(i=>i.addEventListener("change",search));
 $("#topk").addEventListener("change",search);$("#query").addEventListener("keydown",e=>{if(e.key==="Enter")search()});
 $("#go").addEventListener("click",search);$("#cmp").addEventListener("click",compare);
 $("#clear").addEventListener("click",async()=>{const d=await post("/api/clear_cache");$("#steps").innerHTML=`<div class="step ok"><b>Кэш очищен</b>Удалено записей: ${d.cleared}. Следующий поиск выполнится заново.</div>`;});
 renderDocs();search();})();
</script></body></html>
"""


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Демонстрация search_comp запущена: {url}")
    print("Открой адрес в браузере (откроется сам). Остановить — Ctrl+C.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
