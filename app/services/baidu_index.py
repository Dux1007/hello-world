from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests

from .exceptions import BaiduIndexError


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

    def __init__(
        self,
        *,
        cookie: str | None = None,
        session: Optional[requests.Session] = None,
        city_map_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.cookie = cookie
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://index.baidu.com/v2/main/index.html",
                "Accept": "application/json, text/plain, */*",
                "Connection": "keep-alive",
            }
        )
        map_path = city_map_path or Path(__file__).resolve().parent.parent / "data" / "cities.json"
        self.city_codes: Dict[str, int] = self._load_city_codes(map_path)

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
        params = {
            "word": json.dumps([[{"name": keyword, "word": keyword}]], ensure_ascii=False),
            "area": city_code,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
        }
        response = self.session.get(
            self.SEARCH_ENDPOINT,
            params=params,
            headers={"Cookie": cookie, **self.session.headers},
            timeout=30,
        )
        if response.status_code != 200:
            raise BaiduIndexError(
                f"Failed to fetch search index (status {response.status_code}).",
                status_code=response.status_code,
            )
        payload = response.json()
        if payload.get("status") != 0:
            raise BaiduIndexError(payload.get("message", "Unknown search index error."))
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
        params = {
            "word": json.dumps([[keyword]], ensure_ascii=False),
            "area": city_code,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
        }
        response = self.session.get(
            self.NEWS_ENDPOINT,
            params=params,
            headers={"Cookie": cookie, **self.session.headers},
            timeout=30,
        )
        if response.status_code != 200:
            raise BaiduIndexError(
                f"Failed to fetch news index (status {response.status_code}).",
                status_code=response.status_code,
            )
        payload = response.json()
        if payload.get("status") != 0:
            raise BaiduIndexError(payload.get("message", "Unknown news index error."))
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
        response = self.session.get(
            self.PTBK_ENDPOINT,
            params={"uniqid": uniqid},
            headers={"Cookie": cookie, **self.session.headers},
            timeout=30,
        )
        if response.status_code != 200:
            raise BaiduIndexError(
                f"Failed to fetch ptbk (status {response.status_code}).",
                status_code=response.status_code,
            )
        payload = response.json()
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
