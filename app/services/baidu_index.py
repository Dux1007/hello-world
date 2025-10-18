from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import random
import time

import requests
from requests import Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .exceptions import BaiduIndexError, BaiduIndexRateLimitError


class IndexType(str, Enum):
    """Supported Baidu index data categories."""

    SEARCH = "search"
    NEWS = "news"


@dataclass(slots=True)
class SeriesPoint:
    """Single observation in an index time series."""

    date: date
    value: Optional[float]


@dataclass(slots=True)
class DailySeries:
    """Collection of daily index values for a keyword/city pair."""

    index_type: IndexType
    keyword: str
    city: str
    points: List[SeriesPoint]


class BaiduIndexClient:
    """Client for retrieving Baidu search and news index data."""

    SEARCH_ENDPOINT = "https://index.baidu.com/api/SearchApi/index"
    NEWS_ENDPOINT = "https://index.baidu.com/api/NewsApi/getNewsIndex"
    PTBK_ENDPOINT = "https://index.baidu.com/Interface/ptbk"

    RATE_LIMIT_KEYWORDS = ("异常访问", "访问频次过高", "异常访问行为", "访问行为异常")

    def __init__(
        self,
        *,
        cookie: str | None = None,
        session: Optional[requests.Session] = None,
        city_map_path: str | os.PathLike[str] | None = None,
        throttle_seconds: float = 1.25,
        jitter_seconds: float = 0.75,
    ) -> None:
        self.cookie = cookie
        self.session = session or requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods={"GET"},
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://index.baidu.com/v2/main/index.html",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Connection": "keep-alive",
            }
        )
        map_path = city_map_path or Path(__file__).resolve().parent.parent / "data" / "cities.json"
        self.city_codes: Dict[str, int] = self._load_city_codes(map_path)
        self.throttle_seconds = max(throttle_seconds, 0.0)
        self.jitter_seconds = max(jitter_seconds, 0.0)

    @staticmethod
    def _load_city_codes(path: Path) -> Dict[str, int]:
        if not path.exists():
            raise RuntimeError(f"City code mapping file missing: {path}")
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def update_cookie(self, cookie: str) -> None:
        """Update the cookie used for authenticated requests."""

        self.cookie = cookie

    # Public API -----------------------------------------------------------------
    def fetch_indices(
        self,
        *,
        keywords: Iterable[str],
        cities: Iterable[str],
        start_date: date,
        end_date: date,
        index_types: Iterable[IndexType],
        cookie_override: Optional[str] = None,
    ) -> List[DailySeries]:
        if start_date > end_date:
            raise BaiduIndexError("start_date cannot be after end_date")
        cookie = cookie_override or self.cookie
        if not cookie:
            raise BaiduIndexError("A valid Baidu cookie is required to fetch index data.")

        keyword_list = [kw.strip() for kw in keywords if kw.strip()]
        if not keyword_list:
            raise BaiduIndexError("At least one keyword is required.")

        city_list = [self._resolve_city_code(city) for city in cities]
        if not city_list:
            raise BaiduIndexError("At least one valid city is required.")

        series: List[DailySeries] = []
        for city_name, city_code in city_list:
            for keyword in keyword_list:
                for index_type in index_types:
                    points = self._fetch_series(
                        index_type=index_type,
                        keyword=keyword,
                        city_code=city_code,
                        start_date=start_date,
                        end_date=end_date,
                        cookie=cookie,
                    )
                    series.append(
                        DailySeries(
                            index_type=index_type,
                            keyword=keyword,
                            city=city_name,
                            points=points,
                        )
                    )
        return series

    # Internal helpers -----------------------------------------------------------
    def _resolve_city_code(self, name_or_code: str) -> tuple[str, int]:
        candidate = name_or_code.strip()
        if not candidate:
            raise BaiduIndexError("Empty city name encountered.")

        if candidate.isdigit():
            code = int(candidate)
            for city_name, mapped_code in self.city_codes.items():
                if int(mapped_code) == code:
                    return city_name, code
            return candidate, code

        if candidate in self.city_codes:
            return candidate, int(self.city_codes[candidate])

        # Attempt fuzzy match ignoring suffix like "市"
        normalized = candidate.replace("市", "")
        for city_name, code in self.city_codes.items():
            if city_name.startswith(normalized):
                return city_name, int(code)
        raise BaiduIndexError(f"Unknown city: {candidate}")

    def _fetch_series(
        self,
        *,
        index_type: IndexType,
        keyword: str,
        city_code: int,
        start_date: date,
        end_date: date,
        cookie: str,
    ) -> List[SeriesPoint]:
        if index_type is IndexType.SEARCH:
            encrypted_data, uniqid = self._request_search(
                keyword=keyword,
                city_code=city_code,
                start_date=start_date,
                end_date=end_date,
                cookie=cookie,
            )
        elif index_type is IndexType.NEWS:
            encrypted_data, uniqid = self._request_news(
                keyword=keyword,
                city_code=city_code,
                start_date=start_date,
                end_date=end_date,
                cookie=cookie,
            )
        else:
            raise BaiduIndexError(f"Unsupported index type: {index_type}")

        ptbk = self._fetch_ptbk(uniqid=uniqid, cookie=cookie)
        decrypted = self._decrypt(ptbk, encrypted_data)
        values = self._parse_values(decrypted)
        return self._combine_with_dates(values, start_date, end_date)

    # HTTP requests --------------------------------------------------------------
    def _request_search(
        self,
        *,
        keyword: str,
        city_code: int,
        start_date: date,
        end_date: date,
        cookie: str,
    ) -> tuple[str, str]:
        self._sleep_before_request()
        params = {
            "word": json.dumps([[{"name": keyword, "word": keyword}]], ensure_ascii=False),
            "area": city_code,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
        }
        response = self._safe_get(
            self.SEARCH_ENDPOINT,
            params=params,
            cookie=cookie,
            context="search index",
        )
        payload = self._parse_json(response, context="search index")
        self._validate_payload_status(payload, context="search index")
        data = payload.get("data") or {}
        user_indexes = data.get("userIndexes") or []
        if not user_indexes:
            raise BaiduIndexError("No search index data returned.")
        encrypted = user_indexes[0]["all"]["data"]
        uniqid = data.get("uniqid")
        if not uniqid:
            raise BaiduIndexError("uniqid missing from search index response")
        return encrypted, uniqid

    def _request_news(
        self,
        *,
        keyword: str,
        city_code: int,
        start_date: date,
        end_date: date,
        cookie: str,
    ) -> tuple[str, str]:
        self._sleep_before_request()
        params = {
            "word": json.dumps([[keyword]], ensure_ascii=False),
            "area": city_code,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
        }
        response = self._safe_get(
            self.NEWS_ENDPOINT,
            params=params,
            cookie=cookie,
            context="news index",
        )
        payload = self._parse_json(response, context="news index")
        self._validate_payload_status(payload, context="news index")
        data = payload.get("data") or {}
        result = data.get("result") or []
        if not result:
            raise BaiduIndexError("No news index data returned.")
        encrypted = result[0]["all"]["data"]
        uniqid = data.get("uniqid")
        if not uniqid:
            raise BaiduIndexError("uniqid missing from news index response")
        return encrypted, uniqid

    def _fetch_ptbk(self, *, uniqid: str, cookie: str) -> str:
        self._sleep_before_request()
        response = self._safe_get(
            self.PTBK_ENDPOINT,
            params={"uniqid": uniqid},
            cookie=cookie,
            context="ptbk",
        )
        payload = self._parse_json(response, context="ptbk")
        self._validate_payload_status(payload, context="ptbk")
        ptbk = payload.get("data")
        if not ptbk:
            raise BaiduIndexError("ptbk payload missing data field")
        return ptbk

    # Data handling --------------------------------------------------------------
    @staticmethod
    def _decrypt(ptbk: str, data: str) -> str:
        half = len(ptbk) // 2
        mapping = {ptbk[i]: ptbk[i + half] for i in range(half)}
        return "".join(mapping.get(ch, "") for ch in data)

    @staticmethod
    def _parse_values(decrypted: str) -> List[Optional[float]]:
        values: List[Optional[float]] = []
        for chunk in decrypted.split(","):
            if not chunk:
                values.append(None)
            else:
                try:
                    values.append(float(chunk))
                except ValueError:
                    values.append(None)
        return values

    @staticmethod
    def _combine_with_dates(
        values: List[Optional[float]], start_date: date, end_date: date
    ) -> List[SeriesPoint]:
        num_days = (end_date - start_date).days + 1
        if len(values) > num_days:
            # Baidu偶尔会返回超出请求范围的日期，需要裁剪。
            values = values[:num_days]
        elif len(values) < num_days:
            values = values + [None] * (num_days - len(values))
        points: List[SeriesPoint] = []
        current = start_date
        for value in values:
            points.append(SeriesPoint(date=current, value=value))
            current += timedelta(days=1)
            if current > end_date:
                break
        return points

    # Networking helpers --------------------------------------------------------
    def _sleep_before_request(self) -> None:
        if self.throttle_seconds <= 0 and self.jitter_seconds <= 0:
            return
        base = self.throttle_seconds
        jitter = random.random() * self.jitter_seconds if self.jitter_seconds > 0 else 0.0
        time.sleep(base + jitter)

    def _safe_get(
        self,
        url: str,
        *,
        params: Dict[str, object],
        cookie: str,
        context: str,
    ) -> Response:
        try:
            response = self.session.get(
                url,
                params=params,
                headers={**self.session.headers, "Cookie": cookie},
                timeout=30,
            )
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise BaiduIndexError(f"Network error while fetching {context}: {exc}") from exc
        self._raise_for_http_status(response, context=context)
        return response

    def _raise_for_http_status(self, response: Response, *, context: str) -> None:
        if response.status_code == 429:
            raise BaiduIndexRateLimitError(
                "百度指数返回 429（请求过于频繁）。请放慢抓取速度、尝试更换网络或稍后再试。"
            )
        if response.status_code != 200:
            raise BaiduIndexError(
                f"Failed to fetch {context} (status {response.status_code}).",
                status_code=response.status_code,
            )

    def _parse_json(self, response: Response, *, context: str) -> Dict[str, object]:
        try:
            return response.json()
        except ValueError as exc:
            raise BaiduIndexError(f"Failed to parse {context} response as JSON.") from exc

    def _validate_payload_status(self, payload: Dict[str, object], *, context: str) -> None:
        status = payload.get("status")
        if status in (0, "0", None):
            return
        message = payload.get("message") or payload.get("msg") or payload.get("error")
        normalized = str(message or f"Unknown {context} error.")
        if any(keyword in normalized for keyword in self.RATE_LIMIT_KEYWORDS):
            raise BaiduIndexRateLimitError(
                "百度指数提示访问频率异常，请减慢抓取速度、尝试更换 IP 或稍后再试。原始信息：" + normalized
            )
        raise BaiduIndexError(f"{context.capitalize()} request failed: {normalized}")
