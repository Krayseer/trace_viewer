"""Order browsing, route tracing, coverage caching, and source inspection."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

from .recipes import RecipeCatalog
from .records import Book, Component, Order, ProductionHistory, SourceDetails
from .trace import Coverage, ROUTE_FILES, Trace, TraceResult


class ApplicationData(ProductionHistory, Protocol):
    @property
    def months(self) -> Sequence[str]: ...

    def sheet_name(self, file: int, month: str) -> str: ...

    def order(self, month: str, number: int) -> Order: ...

    def source(self, file: int, month: str, number: int) -> SourceDetails: ...


@dataclass(frozen=True, slots=True)
class CoverageReport:
    stage_count: int
    orders: list[Coverage]


def month_window(month: str) -> tuple[date, date]:
    first = date.fromisoformat(month + "-01")
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])


class TraceApplication:
    def __init__(self, data: ApplicationData):
        self.data = data
        self.catalogs = {month: RecipeCatalog(data.month_rows(Component, month)) for month in data.months}
        self._coverage: dict[str, CoverageReport] = {}

    @property
    def default_month(self) -> str:
        return self.data.months[0]

    def months(self) -> list[tuple[str, str]]:
        return [(month, self.data.sheet_name(Book.ORDERS, month)) for month in self.data.months]

    def orders(self, month: str) -> list[Order]:
        if month not in self.data.months:
            raise ValueError("Нет такого листа заказов")
        return [order for order in self.data.month_rows(Order, month) if order.mass]

    def order_coverage(self, month: str) -> CoverageReport:
        if month not in self._coverage:
            orders = self.orders(month)
            first, last = month_window(month)
            scores = [Trace(self.data, self.catalogs, order, "auto", first, last, None).coverage() for order in orders]
            scores.sort(key=Coverage.rank)
            self._coverage[month] = CoverageReport(len(ROUTE_FILES), scores)
        return self._coverage[month]

    def trace(self, month: str, number: int, recipe: str, first: date, last: date, shift: int | None) -> TraceResult:
        order = self.data.order(month, number)
        if not order.mass:
            raise ValueError("В строке отсутствует марка массы")
        return Trace(self.data, self.catalogs, order, recipe, first, last, shift).build()

    def source(self, file: int, month: str, number: int) -> SourceDetails:
        return self.data.source(file, month, number)
