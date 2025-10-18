from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from app.services.baidu_index import DailySeries, IndexType


@dataclass(slots=True)
class AnnualSeries:
    """Aggregated index values for a given year."""

    index_type: IndexType
    keyword: str
    city: str
    year: int
    average: Optional[float]
    total: Optional[float]
    non_null_days: int


def aggregate_annual(series_list: Iterable[DailySeries]) -> List[AnnualSeries]:
    """Aggregate daily series into annual summaries."""

    aggregates: List[AnnualSeries] = []
    for series in series_list:
        buckets: Dict[int, List[float]] = defaultdict(list)
        for point in series.points:
            if point.value is not None:
                buckets[point.date.year].append(point.value)
        for year, values in sorted(buckets.items()):
            if values:
                total = float(sum(values))
                average = total / len(values)
            else:
                total = None
                average = None
            aggregates.append(
                AnnualSeries(
                    index_type=series.index_type,
                    keyword=series.keyword,
                    city=series.city,
                    year=year,
                    average=average,
                    total=total,
                    non_null_days=len(values),
                )
            )
    return aggregates
