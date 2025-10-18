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


def _normalize_proxy(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _build_proxy_mapping(
    *,
    all_proxy: str | None = None,
    http_proxy: str | None = None,
    https_proxy: str | None = None,
) -> dict[str, str] | None:
    proxies: dict[str, str] = {}
    normalized_all = _normalize_proxy(all_proxy)
    normalized_http = _normalize_proxy(http_proxy)
    normalized_https = _normalize_proxy(https_proxy)
    if normalized_all:
        proxies["http"] = normalized_all
        proxies["https"] = normalized_all
    if normalized_http:
        proxies["http"] = normalized_http
    if normalized_https:
        proxies["https"] = normalized_https
    return proxies or None


def _load_default_proxies() -> dict[str, str] | None:
    return _build_proxy_mapping(
        all_proxy=os.getenv("BAIDU_ALL_PROXY"),
        http_proxy=os.getenv("BAIDU_HTTP_PROXY"),
        https_proxy=os.getenv("BAIDU_HTTPS_PROXY"),
    )


client = BaiduIndexClient(
    cookie=os.getenv("BAIDU_COOKIE"),
    throttle_seconds=_parse_env_float("BAIDU_THROTTLE_SECONDS", 1.25),
    jitter_seconds=_parse_env_float("BAIDU_THROTTLE_JITTER", 0.75),
    proxies=_load_default_proxies(),
)


@app.post("/api/fetch", response_model=FetchResponse)
def fetch_indices(request: FetchRequest) -> FetchResponse:
    cookie = request.cookie or client.cookie
    if not cookie:
        raise HTTPException(status_code=400, detail="Baidu cookie must be provided in the request or BAIDU_COOKIE env var.")

    try:
        proxies_override = _build_proxy_mapping(
            all_proxy=request.proxy,
            http_proxy=request.http_proxy,
            https_proxy=request.https_proxy,
        )

        daily_series = client.fetch_indices(
            keywords=request.keywords,
            cities=request.cities,
            start_date=request.start_date,
            end_date=request.end_date,
            index_types=request.index_types,
            cookie_override=cookie,
            proxies_override=proxies_override,
        )
    except BaiduIndexRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except BaiduIndexError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    annual_series = aggregate_annual(daily_series)
    return FetchResponse.from_results(daily_series=daily_series, annual_series=annual_series)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
