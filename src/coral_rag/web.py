"""Public-facing, read-only research interface. It never exposes credentials or raw files."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .iai import IAIClient, IAIError
from .observations import find_observations
from .query import answer, retrieve
from .settings import Settings
from .store import KnowledgeStore


ROOT = Path(__file__).resolve().parents[2]
app = FastAPI(title="珊瑚礁浮潛與水肺潛水研究支援", docs_url=None, redoc_url=None)


class QueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    use_llm: bool = False


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.OperationalError:
        return 0


@app.get("/api/health")
def health() -> dict:
    structured = ROOT / "data" / "processed" / "marine_research.sqlite"
    counts = {"mpa_zones": 0, "edna_occurrences": 0, "reefcheck_events": 0}
    if structured.exists():
        with sqlite3.connect(structured) as connection:
            counts = {
                "mpa_zones": _table_count(connection, "mpa_zone"),
                "edna_occurrences": _table_count(connection, "edna_occurrence"),
                "reefcheck_events": _table_count(connection, "reefcheck_event"),
            }
    latest_tide = sorted((ROOT / "data" / "raw" / "external" / "cwa").glob("F-A0021-001_*.provenance.json"))
    return {
        "service": "research-evidence-api",
        "structured_database_ready": structured.exists(),
        "counts": counts,
        "latest_tide_provenance": json.loads(latest_tide[-1].read_text(encoding="utf-8")) if latest_tide else None,
        "safety": "No site is labelled safe. Legal rules and live data must be current and complete.",
    }


@app.get("/api/observations")
def observations(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(default=5, gt=0, le=100),
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    try:
        result = find_observations(
            ROOT / "data" / "processed" / "marine_research.sqlite",
            latitude, longitude, radius_km, start, end, limit,
        )
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"evidence": result, "warning": "Historical observations are not a current-presence, legality, or safety conclusion."}


@app.post("/api/query")
def query(request: QueryRequest) -> dict:
    settings = Settings.from_project_root(ROOT)
    store = KnowledgeStore(settings.db_path)
    try:
        client = IAIClient(settings) if request.use_llm else None
        hits = retrieve(store, request.question, client)
        return {"answer": answer(request.question, hits, client), "llm_used": bool(client)}
    except IAIError as error:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {error}") from error
    finally:
        store.close()


@app.get("/", response_class=HTMLResponse)
def homepage() -> str:
    return """<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>珊瑚礁研究支援</title><style>body{font-family:system-ui,sans-serif;max-width:780px;margin:44px auto;padding:0 20px;line-height:1.65;color:#102a43}h1{color:#006d77}button{background:#006d77;color:white;border:0;border-radius:6px;padding:8px 14px}input{padding:8px;width:130px}pre{background:#f1f5f9;padding:16px;white-space:pre-wrap;border-radius:8px}.warn{background:#fff3cd;padding:12px;border-radius:8px}</style></head><body><h1>珊瑚礁浮潛與水肺潛水研究支援</h1><p class='warn'>本系統僅提供可追溯研究證據，絕不判定潛點或下水「安全」。請以主管機關公告、現場旗號、合格專業人員與最新波流潮位覆核。</p><h2>資料狀態</h2><pre id='status'>讀取中…</pre><h2>查詢歷史生物調查</h2><p>輸入座標，查 eDNA 與 Reef Check 的歷史採樣／觀察證據。</p><input id='lat' value='22.68' aria-label='緯度'><input id='lon' value='121.50' aria-label='經度'><button onclick='lookup()'>查詢</button><pre id='result'></pre><script>fetch('/api/health').then(r=>r.json()).then(x=>status.textContent=JSON.stringify(x,null,2)).catch(()=>status.textContent='資料庫尚未初始化');function lookup(){const u='/api/observations?latitude='+encodeURIComponent(lat.value)+'&longitude='+encodeURIComponent(lon.value);fetch(u).then(r=>r.json()).then(x=>result.textContent=x.evidence||x.detail).catch(()=>result.textContent='查詢失敗');}</script></body></html>"""
