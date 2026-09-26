"""Public-facing, read-only research interface. It never exposes credentials or raw files."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .iai import IAIClient, IAIError
from .general_weather import GeneralWeatherError, find_general_weather_forecast
from .full_text import search_with_policy
from .knowledge import load_conservation_cards, render_conservation_cards
from .dive_site_profiles import ProfileDataError, load_profile_catalog, profile_api_payload
from .dive_site_media import MediaManifestError, load_media_catalog, media_api_payload
from .marine_forecast import ForecastError, find_marine_forecast, utc_now
from .nearby_marine_context import NearbyMarineContextError, find_nearby_marine_context
from .nearby_edna import DEFAULT_LIMIT, MAX_LIMIT, MAX_OFFSET, MAX_RADIUS_M, find_nearby_edna_evidence
from .nearby_reef_check import (
    ReefCheckLicenseRestrictedError,
    find_nearby_reefcheck_evidence,
)
from .observations import find_observations
from .query import answer, retrieve
from .settings import Settings
from .store import FTSIndexNotReadyError, FTSUnavailableError, KnowledgeStore
from .research_assistant import run_research_assistant
from .research_chat import remaining_model_calls, run_research_chat
from .species_reference import SpeciesReferenceError, find_species_reference_images
from .rag_v2_answer import answer_rag_v2_question
from .map_profile_answer import (
    ProfileAnswerResult,
    ProfileCitation,
    answer_profile_question,
)
from .map_profile_evidence import (
    DEFAULT_CURATED_SITES_PATH,
    ProfileEvidenceError,
    _load_curated_site_ids,
)
from .map_profile_edna_answer import (
    ProfileEdnaAnswerResult,
    ProfileEdnaCitation,
    answer_profile_edna_question,
)
from .map_profile_edna_evidence import ProfileEdnaEvidenceError


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PACKAGE_ROOT / "static"
CURATED_SPECIES_MEDIA_DIR = ROOT / "data" / "curated-media" / "species-reference"
TEMPLATE_ROOT = PACKAGE_ROOT / "templates"
app = FastAPI(title="珊瑚礁浮潛與水肺潛水研究支援", docs_url=None, redoc_url=None)
if CURATED_SPECIES_MEDIA_DIR.exists():
    app.mount(
        "/static/curated-media/species-reference",
        StaticFiles(directory=CURATED_SPECIES_MEDIA_DIR),
        name="species-reference",
    )
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


class RagV2AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)

    model_config = {"extra": "forbid"}


class AskProfileRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)

    model_config = {"extra": "forbid"}

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 2:
            raise ValueError("問題內容過短或全為空白字元，請輸入至少 2 個有效字元。")
        return stripped


def get_profile_llm_client() -> Callable[[str, str], str] | None:
    return None


class AskEdnaRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    radius_m: int = Field(ge=1, le=5000)

    model_config = {"extra": "forbid"}

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        stripped = v.strip()
        if len(stripped) < 2:
            raise ValueError("問題內容過短或全為空白字元，請輸入至少 2 個有效字元。")
        return stripped


def get_edna_llm_client() -> Callable[[str, str], str] | None:
    return None


class QueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    use_llm: bool = False


class ResearchAssistantRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    site_id: str | None = Field(default=None, min_length=1, max_length=160)
    radius_m: int | None = Field(default=None, ge=1, le=MAX_RADIUS_M)
    start_at: str | None = Field(default=None, min_length=20, max_length=40)
    end_at: str | None = Field(default=None, min_length=20, max_length=40)


class ResearchChatRequest(ResearchAssistantRequest):
    question: str = Field(min_length=2, max_length=800)
    use_model: bool = Field(default=False, description="Explicit opt-in to the local Gemini research-chat mode")


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.OperationalError:
        return 0


def _dive_site_payload(row: sqlite3.Row) -> dict:
    return {
        "id": row["site_id"],
        "name": row["name"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "administrative_area": {"county": row["county"], "district": row["district"]},
        "source": {"name": row["source_name"], "reference": row["source_reference"]},
        "last_verified_at": row["last_verified_at"],
        "data_quality": row["data_quality"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _dive_sites_database() -> Path:
    configured = os.getenv("CORAL_RAG_STRUCTURED_DB")
    return Path(configured) if configured else ROOT / "data" / "processed" / "marine_research.sqlite"


def _rag_database() -> Path:
    configured = os.getenv("CORAL_RAG_RAG_DB")
    return Path(configured) if configured else ROOT / "data" / "processed" / "rag.sqlite"


@app.get("/api/dive-sites")
def list_dive_sites(
    region: str | None = Query(default=None, min_length=1, max_length=100),
    keyword: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """List curator-supplied, source-linked site records; never infer a site from observations."""
    database = _dive_sites_database()
    if not database.exists():
        return {"items": [], "count": 0}

    clauses: list[str] = []
    parameters: list[str | int] = []
    if region:
        clauses.append("(county LIKE ? ESCAPE '\\' OR district LIKE ? ESCAPE '\\')")
        pattern = f"%{region.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
        parameters.extend((pattern, pattern))
    if keyword:
        clauses.append("(site_id LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')")
        pattern = f"%{keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
        parameters.extend((pattern, pattern))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    statement = (
        "SELECT site_id, name, latitude, longitude, county, district, source_name, source_reference, "
        "last_verified_at, data_quality, created_at, updated_at FROM dive_sites"
        f"{where} ORDER BY name COLLATE NOCASE, site_id LIMIT ?"
    )
    try:
        connection = sqlite3.connect(database)
        try:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(statement, [*parameters, limit]).fetchall()
        finally:
            connection.close()
    except sqlite3.OperationalError:
        # A database built by an older release has no curated sites yet.
        return {"items": [], "count": 0}
    items = [_dive_site_payload(row) for row in rows]
    return {"items": items, "count": len(items)}


@app.get("/api/dive-sites/{site_id}")
def get_dive_site(site_id: str) -> dict:
    """Return one source-linked site record without any safety, legality, or suitability judgement."""
    database = _dive_sites_database()
    if not database.exists():
        raise HTTPException(status_code=404, detail="Dive site not found")
    try:
        connection = sqlite3.connect(database)
        try:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """SELECT site_id, name, latitude, longitude, county, district, source_name,
                   source_reference, last_verified_at, data_quality, created_at, updated_at
                   FROM dive_sites WHERE site_id = ?""",
                (site_id,),
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.OperationalError:
        row = None
    if row is None:
        raise HTTPException(status_code=404, detail="Dive site not found")
    return _dive_site_payload(row)


@app.get("/api/dive-sites/{site_id}/profile")
def get_dive_site_profile(site_id: str) -> JSONResponse:
    """Return a source-approved static profile without reading biological, weather, or marine tables."""
    site = get_dive_site(site_id)
    try:
        catalog = load_profile_catalog(ROOT)
        payload = profile_api_payload(site, catalog)
    except ProfileDataError:
        return JSONResponse(
            {"status": "profile_data_unavailable", "reason": "profile_source_validation_failed"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    if payload.get("status") != "available":
        payload["media"] = {
            "status": "unavailable", "reason": "no_approved_profile_for_site",
            "message": "目前沒有可公開展示的官方圖片。", "image": None,
            "license_attribution": "官方媒體再利用權利尚未確認。", "last_verified_at": None,
        }
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    try:
        media_catalog = load_media_catalog(ROOT, catalog.profiles)
    except MediaManifestError:
        return JSONResponse(
            {"status": "profile_data_unavailable", "reason": "profile_source_validation_failed"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    payload["media"] = media_api_payload(site_id, media_catalog)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/dive-sites/{site_id}/ask-profile")
def ask_profile(
    site_id: str,
    request: AskProfileRequest,
    llm_client: Callable[[str, str], str] | None = Depends(get_profile_llm_client),
) -> JSONResponse:
    """Execute controlled profile-specific generative question answering for a curated dive site.

    Response adheres strictly to a 4-field whitelist:
    status, answer_zh_hant, citations, safety_route.
    All responses set Cache-Control: no-store.
    """
    csv_path = ROOT / "data" / "curated" / "dive_sites.csv"
    if not csv_path.exists():
        return JSONResponse(
            {
                "status": "profile_source_unavailable",
                "answer_zh_hant": "潛點介紹資料來源或索引校驗失敗，暫時無法提供問答服務。",
                "citations": [],
                "safety_route": None,
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    try:
        curated_ids = _load_curated_site_ids(csv_path)
    except ProfileEvidenceError:
        return JSONResponse(
            {
                "status": "profile_source_unavailable",
                "answer_zh_hant": "潛點介紹資料來源或索引校驗失敗，暫時無法提供問答服務。",
                "citations": [],
                "safety_route": None,
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    if site_id not in curated_ids:
        return JSONResponse(
            {
                "status": "site_not_found",
                "answer_zh_hant": "指定的潛點代碼不存在或未經核驗。",
                "citations": [],
                "safety_route": None,
            },
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )

    clean_q = request.question.strip()
    try:
        result = answer_profile_question(
            question=clean_q,
            site_id=site_id,
            llm_client=llm_client,
        )
    except (ProfileEvidenceError, sqlite3.DatabaseError):
        return JSONResponse(
            {
                "status": "profile_source_unavailable",
                "answer_zh_hant": "潛點介紹資料來源或索引校驗失敗，暫時無法提供問答服務。",
                "citations": [],
                "safety_route": None,
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        return JSONResponse(
            {
                "status": "internal_error",
                "answer_zh_hant": "伺服器處理問答時發生未預期異常，請稍後再試。",
                "citations": [],
                "safety_route": None,
            },
            status_code=500,
            headers={"Cache-Control": "no-store"},
        )

    citations_payload = (
        [c.to_dict() if hasattr(c, "to_dict") else c for c in result.citations]
        if result.status == "answerable"
        else []
    )
    safety_route_payload = (
        result.error_code
        if result.status == "safety_intercepted"
        else None
    )

    payload = {
        "status": result.status,
        "answer_zh_hant": result.answer_zh_hant,
        "citations": citations_payload,
        "safety_route": safety_route_payload,
    }
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/dive-sites/{site_id}/ask-edna")
def ask_edna(
    site_id: str,
    request: AskEdnaRequest,
    llm_client: Callable[[str, str], str] | None = Depends(get_edna_llm_client),
) -> JSONResponse:
    """Execute controlled eDNA historical evidence generative question answering for a curated dive site.

    Response adheres strictly to a 4-field whitelist:
    status, answer_zh_hant, citations, safety_route.
    All responses set Cache-Control: no-store.
    """
    csv_path = ROOT / "data" / "curated" / "dive_sites.csv"
    if not csv_path.exists():
        return JSONResponse(
            {
                "status": "edna_source_unavailable",
                "answer_zh_hant": "潛點資料來源校驗失敗，暫時無法提供問答服務。",
                "citations": [],
                "safety_route": None,
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    try:
        curated_ids = _load_curated_site_ids(csv_path)
    except Exception:
        return JSONResponse(
            {
                "status": "edna_source_unavailable",
                "answer_zh_hant": "潛點資料來源校驗失敗，暫時無法提供問答服務。",
                "citations": [],
                "safety_route": None,
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )

    if site_id not in curated_ids:
        return JSONResponse(
            {
                "status": "site_not_found",
                "answer_zh_hant": "指定的潛點代碼不存在或未經核驗。",
                "citations": [],
                "safety_route": None,
            },
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )

    clean_q = request.question.strip()
    clean_r = request.radius_m
    try:
        result = answer_profile_edna_question(
            clean_q,
            site_id=site_id,
            radius_m=clean_r,
            limit=10,
            llm_callable_override=llm_client,
        )
    except (ProfileEdnaEvidenceError, sqlite3.DatabaseError):
        return JSONResponse(
            {
                "status": "edna_source_unavailable",
                "answer_zh_hant": "結構化 eDNA 資料庫不可用或來源驗證失敗，暫時無法提供問答服務。",
                "citations": [],
                "safety_route": None,
            },
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        return JSONResponse(
            {
                "status": "internal_error",
                "answer_zh_hant": "伺服器處理問答時發生未預期異常，請稍後再試。",
                "citations": [],
                "safety_route": None,
            },
            status_code=500,
            headers={"Cache-Control": "no-store"},
        )

    citations_payload = (
        [c.to_dict() if hasattr(c, "to_dict") else c for c in result.citations]
        if result.status == "answerable"
        else []
    )
    safety_route_payload = (
        result.error_code
        if result.status in ("safety_intercepted", "scope_guidance")
        else None
    )

    payload = {
        "status": result.status,
        "answer_zh_hant": result.answer_zh_hant,
        "citations": citations_payload,
        "safety_route": safety_route_payload,
    }
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/api/dive-sites/{site_id}/nearby-edna")
def nearby_edna(
    site_id: str,
    radius_m: int = Query(..., ge=1, le=MAX_RADIUS_M),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0, le=MAX_OFFSET),
) -> dict:
    """Return nearby historical eDNA evidence without creating a persistent site relationship."""
    try:
        result = find_nearby_edna_evidence(
            _dive_sites_database(), site_id, radius_m, limit=limit, offset=offset
        )
    except (RuntimeError, sqlite3.OperationalError) as error:
        raise HTTPException(status_code=503, detail=f"Structured eDNA data unavailable: {error}") from error
    if result is None:
        raise HTTPException(status_code=404, detail="Dive site not found")
    return result


@app.get("/api/dive-sites/{site_id}/nearby-reef-check")
def nearby_reef_check(
    site_id: str,
    radius_m: int = Query(..., ge=1, le=MAX_RADIUS_M),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0, le=MAX_OFFSET),
) -> JSONResponse:
    """License-gated local research access to historical Reef Check visual evidence."""
    try:
        result = find_nearby_reefcheck_evidence(
            _dive_sites_database(), site_id, radius_m, limit=limit, offset=offset
        )
    except ReefCheckLicenseRestrictedError:
        return JSONResponse(
            {
                "status": "license_restricted",
                "reason": "local_noncommercial_research_mode_required",
                "detail": "Reef Check observations are disabled unless explicit local non-commercial research mode is enabled. No observation content is returned.",
            },
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )
    except (RuntimeError, sqlite3.OperationalError):
        return JSONResponse(
            {"status": "data_unavailable", "reason": "structured_reef_check_data_unavailable"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    if result is None:
        raise HTTPException(status_code=404, detail="Dive site not found")
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.get("/api/dive-sites/{site_id}/marine-forecast")
def marine_forecast(
    site_id: str,
    start_at: str = Query(..., min_length=20, max_length=40, description="Timezone-qualified ISO 8601, inclusive"),
    end_at: str = Query(..., min_length=20, max_length=40, description="Timezone-qualified ISO 8601, exclusive"),
    now: datetime = Depends(utc_now),
) -> JSONResponse:
    """Source-linked, bounded wave/current forecasts; never an activity decision."""
    try:
        try:
            max_age = Settings.from_project_root(ROOT).max_live_data_age_hours
        except (OSError, ValueError, TypeError):
            raise ForecastError("invalid_freshness_configuration") from None
        payload = find_marine_forecast(
            _dive_sites_database(), ROOT / "data" / "raw" / "external" / "cwa",
            site_id, start_at, end_at, now=now, max_age_hours=max_age,
        )
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    except ForecastError as error:
        return JSONResponse(error.payload, status_code=error.status_code, headers={"Cache-Control": "no-store"})


@app.get("/api/dive-sites/{site_id}/nearby-marine-context")
def nearby_marine_context(
    site_id: str,
    start_at: str | None = Query(None, min_length=20, max_length=40, description="Timezone-qualified ISO 8601, inclusive"),
    end_at: str | None = Query(None, min_length=20, max_length=40, description="Timezone-qualified ISO 8601, exclusive"),
    now: datetime = Depends(utc_now),
) -> JSONResponse:
    """Macro numerical model wave/current context from nearest CWA calculation point; never in-situ observation."""
    try:
        try:
            settings_age = os.getenv("NEARBY_MARINE_MAX_DATA_AGE_HOURS")
            max_age = int(settings_age) if settings_age else 24
        except (ValueError, TypeError):
            max_age = 24
        payload = find_nearby_marine_context(
            _dive_sites_database(), ROOT / "data" / "raw" / "external" / "cwa",
            site_id, start_at, end_at, now=now, max_age_hours=max_age,
        )
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    except NearbyMarineContextError as error:
        return JSONResponse(error.payload, status_code=error.status_code, headers={"Cache-Control": "no-store"})


@app.get("/api/dive-sites/{site_id}/species-reference-images")
def species_reference_images(
    site_id: str,
) -> JSONResponse:
    """Public-safe read-only endpoint for species reference images and verified evidence linkage."""
    try:
        payload = find_species_reference_images(ROOT, site_id)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    except SpeciesReferenceError as error:
        return JSONResponse(error.payload, status_code=error.status_code, headers={"Cache-Control": "no-store"})


@app.get("/api/dive-sites/{site_id}/general-weather-forecast")
def general_weather_forecast(
    site_id: str,
    start_at: str = Query(..., min_length=20, max_length=40, description="Timezone-qualified ISO 8601, inclusive"),
    end_at: str = Query(..., min_length=20, max_length=40, description="Timezone-qualified ISO 8601, exclusive"),
    now: datetime = Depends(utc_now),
) -> JSONResponse:
    """Return only an explicitly mapped administrative-area general-weather forecast."""
    try:
        try:
            max_age = Settings.from_project_root(ROOT).general_weather_max_data_age_hours
        except (OSError, ValueError, TypeError):
            raise GeneralWeatherError("invalid_freshness_configuration") from None
        payload = find_general_weather_forecast(
            _dive_sites_database(), ROOT / "data" / "raw" / "external" / "cwa",
            site_id, start_at, end_at, now=now, max_age_hours=max_age,
        )
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    except GeneralWeatherError as error:
        return JSONResponse(error.payload, status_code=error.status_code, headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health() -> dict:
    structured = _dive_sites_database()
    counts = {"mpa_zones": 0, "edna_occurrences": 0, "reefcheck_events": 0, "marine_forecasts": 0}
    forecast_window = None
    if structured.exists():
        with sqlite3.connect(structured) as connection:
            counts = {
                "mpa_zones": _table_count(connection, "mpa_zone"),
                "edna_occurrences": _table_count(connection, "edna_occurrence"),
                "reefcheck_events": _table_count(connection, "reefcheck_event"),
                "marine_forecasts": _table_count(connection, "marine_forecast"),
            }
            if counts["marine_forecasts"]:
                row = connection.execute("SELECT MIN(valid_at), MAX(valid_at) FROM marine_forecast").fetchone()
                forecast_window = {"valid_from": row[0], "valid_to": row[1]}
    latest_tide = sorted((ROOT / "data" / "raw" / "external" / "cwa").glob("F-A0021-001_*.provenance.json"))
    return {
        "service": "research-evidence-api",
        "structured_database_ready": structured.exists(),
        "counts": counts,
        "forecast_window": forecast_window,
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
            _dive_sites_database(),
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


@app.post("/api/research-assistant/query")
def research_assistant_query(request: ResearchAssistantRequest) -> JSONResponse:
    """Read-only structured evidence presentation; never calls iAI or the chat pipeline."""
    payload = run_research_assistant(
        ROOT, _dive_sites_database(), _rag_database(), question=request.question,
        site_id=request.site_id, radius_m=request.radius_m, start_at=request.start_at, end_at=request.end_at,
    )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/api/research-chat/status")
def research_chat_status() -> JSONResponse:
    """Local, secret-free mode status: Gemini configuration presence and budget."""
    from .chat_model import load_gemini_live_configuration

    configuration, configuration_error = load_gemini_live_configuration(ROOT)
    return JSONResponse(
        {
            "mode_name": "gemini",
            "status": "ready" if configuration is not None else (configuration_error or "provider_configuration_missing"),
            "quota_remaining": remaining_model_calls(),
            "model_called_only_when_explicit": True,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/research-chat")
def research_chat(request: ResearchChatRequest) -> JSONResponse:
    """Local Gemini research chat; the model is called only after explicit opt-in and a gate check."""
    payload = run_research_chat(
        ROOT, _dive_sites_database(), _rag_database(), question=request.question,
        use_model=request.use_model, site_id=request.site_id, radius_m=request.radius_m,
        start_at=request.start_at, end_at=request.end_at,
    )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.get("/api/search")
def full_text_search(
    q: str = Query(..., min_length=1, max_length=240),
    limit: int = Query(default=10, ge=1, le=20),
    include_restricted: bool = Query(default=False),
) -> JSONResponse:
    """Read-only, policy-aware FTS evidence retrieval. It never calls an LLM."""
    database = _rag_database()
    if not database.exists():
        return JSONResponse(
            {"error": "fts_index_unavailable", "detail": "FTS index has not been built."},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    try:
        store = KnowledgeStore(database, initialize=False)
        try:
            payload = search_with_policy(
                store, ROOT, q, limit=limit, include_restricted=include_restricted
            )
        finally:
            store.close()
    except (FTSUnavailableError, FTSIndexNotReadyError, sqlite3.Error):
        return JSONResponse(
            {"error": "fts_index_unavailable", "detail": "FTS index is unavailable or not current."},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.post("/api/rag-v2/ask")
def ask_rag_v2(request: RagV2AskRequest) -> JSONResponse:
    """Execute controlled RAG v2 question answering with server-side citation binding.

    Response adheres strictly to a 4-field whitelist:
    status, answer_zh_hant, citations, safety_route.
    Internal diagnostics such as retrieval_summary or used_chunk_ids are not exposed to the browser.
    """
    clean_q = request.question.strip()
    if len(clean_q) < 2:
        return JSONResponse(
            {
                "status": "safety_intercepted",
                "answer_zh_hant": "提問內容過短，請輸入至少 2 個有效字元。",
                "citations": [],
                "safety_route": "empty_query",
            },
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )

    try:
        result = answer_rag_v2_question(question=clean_q, provider_name="env")
        payload = {
            "status": result.status,
            "answer_zh_hant": result.answer_zh_hant,
            "citations": [c.to_dict() if hasattr(c, "to_dict") else c for c in result.citations],
            "safety_route": result.safety_route,
        }
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
    except Exception:
        return JSONResponse(
            {
                "status": "internal_error",
                "answer_zh_hant": "伺服器處理問答時發生異常，請稍後再試。",
                "citations": [],
                "safety_route": None,
            },
            status_code=500,
            headers={"Cache-Control": "no-store"},
        )


@app.get("/", response_class=HTMLResponse)
def homepage() -> HTMLResponse:
    """Render the local research-system entry point without external resources."""
    return HTMLResponse(
        TEMPLATE_ROOT.joinpath("home.html").read_text(encoding="utf-8"),
        headers={
            "Content-Security-Policy": (
                "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
                "script-src 'self' 'unsafe-inline'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; font-src 'self'; form-action 'self'"
            ),
            "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )
@app.get("/map", response_class=HTMLResponse)
def map_page() -> HTMLResponse:
    """Show source-verified representative points with a text-list fallback."""
    return HTMLResponse(
        TEMPLATE_ROOT.joinpath("map.html").read_text(encoding="utf-8"),
        headers={
            "Content-Security-Policy": (
                "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
                "script-src 'self' https://unpkg.com; style-src 'self' https://unpkg.com; "
                "img-src 'self' data: https://unpkg.com https://tile.openstreetmap.org; "
                "connect-src 'self'; font-src 'self'; form-action 'self'"
            ),
            "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/knowledge", response_class=HTMLResponse)
def knowledge_page() -> HTMLResponse:
    """Render only manually reviewed, low-risk conservation material."""
    headers = {
        "Content-Security-Policy": (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; form-action 'self'"
        ),
        "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Content-Type-Options": "nosniff",
    }
    try:
        cards = load_conservation_cards(ROOT)
        template = TEMPLATE_ROOT.joinpath("knowledge.html").read_text(encoding="utf-8")
        content = template.replace("{{knowledge_cards}}", render_conservation_cards(cards))
    except (OSError, ValueError):
        content = (
            "<!doctype html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            "<title>海洋保育知識</title></head><body><main><h1>海洋保育知識</h1>"
            "<p>知識內容目前資料不足，請參考官方單位、合格教練或專業人員。</p>"
            "</main></body></html>"
        )
        return HTMLResponse(content=content, status_code=503, headers=headers)
    return HTMLResponse(content=content, headers=headers)


@app.get("/assistant", response_class=HTMLResponse)
def research_assistant_page() -> HTMLResponse:
    """Local, non-generative research evidence page with no model integration."""
    return HTMLResponse(
        TEMPLATE_ROOT.joinpath("assistant.html").read_text(encoding="utf-8"),
        headers={
            "Content-Security-Policy": "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; form-action 'self'",
            "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )
