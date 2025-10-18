from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.models import FetchRequest, FetchResponse
from app.services.baidu_index import BaiduIndexClient
from app.services.exceptions import BaiduIndexError, BaiduIndexRateLimitError
from app.utils import aggregate_annual

app = FastAPI(title="Baidu Index Aggregator", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _parse_env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return default


client = BaiduIndexClient(
    cookie=os.getenv("BAIDU_COOKIE"),
    throttle_seconds=_parse_env_float("BAIDU_THROTTLE_SECONDS", 1.25),
    jitter_seconds=_parse_env_float("BAIDU_THROTTLE_JITTER", 0.75),
)


@app.post("/api/fetch", response_model=FetchResponse)
def fetch_indices(request: FetchRequest) -> FetchResponse:
    cookie = request.cookie or client.cookie
    if not cookie:
        raise HTTPException(status_code=400, detail="Baidu cookie must be provided in the request or BAIDU_COOKIE env var.")

    try:
        daily_series = client.fetch_indices(
            keywords=request.keywords,
            cities=request.cities,
            start_date=request.start_date,
            end_date=request.end_date,
            index_types=request.index_types,
            cookie_override=cookie,
        )
    except BaiduIndexRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except BaiduIndexError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    annual_series = aggregate_annual(daily_series)
    return FetchResponse.from_results(daily_series=daily_series, annual_series=annual_series)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
