from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field, validator

from app.services.baidu_index import DailySeries, IndexType
from app.utils.aggregation import AnnualSeries


class FetchRequest(BaseModel):
    """Request body for fetching Baidu index data."""

    keywords: List[str] = Field(..., min_items=1, description="List of keywords to query")
    cities: List[str] = Field(..., min_items=1, description="List of cities or Baidu area codes")
    start_date: date = Field(..., description="Start date (inclusive)")
    end_date: date = Field(..., description="End date (inclusive)")
    index_types: List[IndexType] = Field(
        default_factory=lambda: [IndexType.SEARCH, IndexType.NEWS],
        description="Index categories to retrieve",
    )
    cookie: Optional[str] = Field(
        default=None,
        description="Cookie string exported from a logged-in Baidu Index session.",
    )

    @validator("end_date")
    def _validate_dates(cls, end_date: date, values: dict) -> date:
        start_date: Optional[date] = values.get("start_date")
        if start_date and end_date < start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return end_date


class SeriesPointModel(BaseModel):
    date: date
    value: Optional[float]

    @classmethod
    def from_dataclass(cls, point) -> "SeriesPointModel":
        return cls(date=point.date, value=point.value)


class DailySeriesModel(BaseModel):
    index_type: IndexType
    keyword: str
    city: str
    points: List[SeriesPointModel]

    @classmethod
    def from_dataclass(cls, series: DailySeries) -> "DailySeriesModel":
        return cls(
            index_type=series.index_type,
            keyword=series.keyword,
            city=series.city,
            points=[SeriesPointModel.from_dataclass(point) for point in series.points],
        )


class AnnualSeriesModel(BaseModel):
    index_type: IndexType
    keyword: str
    city: str
    year: int
    average: Optional[float]
    total: Optional[float]
    non_null_days: int

    @classmethod
    def from_dataclass(cls, series: AnnualSeries) -> "AnnualSeriesModel":
        return cls(
            index_type=series.index_type,
            keyword=series.keyword,
            city=series.city,
            year=series.year,
            average=series.average,
            total=series.total,
            non_null_days=series.non_null_days,
        )


class FetchResponse(BaseModel):
    daily: List[DailySeriesModel]
    annual: List[AnnualSeriesModel]

    @classmethod
    def from_results(
        cls,
        *,
        daily_series: List[DailySeries],
        annual_series: List[AnnualSeries],
    ) -> "FetchResponse":
        return cls(
            daily=[DailySeriesModel.from_dataclass(item) for item in daily_series],
            annual=[AnnualSeriesModel.from_dataclass(item) for item in annual_series],
        )
