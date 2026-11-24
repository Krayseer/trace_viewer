"""Named production values and references to their original XLS rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum, IntEnum
from typing import Iterable, NamedTuple, Protocol, Sequence, TypeVar


Cell = str | int | float


class Book(IntEnum):
    ORDERS = 1
    RECIPES = 2
    POWDERS = 3
    DOSING = 4
    PRESS_NORMS = 5
    PRESSING = 6
    WAGON_LOADING = 7
    FURNACES = 8
    FINISHING = 9
    DELIVERIES = 10
    PERCENTAGES = 11
    DOWNTIMES = 12


class Field(Enum):
    DAY = "day"
    EXIT_DAY = "exit_day"
    ORDER_CODE = "order_code"
    RECIPE_NUMBER = "recipe_number"
    MARK = "mark"


TITLES = (
    "Заказы", "Шихта", "Подача порошков", "Линии дозирования", "Нормы прессовки",
    "Прессовка", "Садка", "Печи", "Доп операции", "Сдача", "Проценты", "Простои",
)


@dataclass(frozen=True, slots=True)
class SourceRef:
    file: Book
    month: str
    sheet: str
    row: int


@dataclass(frozen=True, slots=True)
class SourceDetails:
    book: str
    sheet: str
    row: int
    fields: list[tuple[str, Cell]]


class RecipeKey(NamedTuple):
    order_code: Cell
    number: Cell
    mark: Cell


@dataclass(frozen=True, slots=True)
class Record:
    source: SourceRef


@dataclass(frozen=True, slots=True)
class Order(Record):
    raw_group: Cell
    product_group: Cell
    mass: Cell
    raw: Cell
    product: Cell
    name: Cell
    mark: Cell
    base_tonnes: Cell
    extra_tonnes: Cell


@dataclass(frozen=True, slots=True)
class Component(Record):
    mass: Cell
    recipe: RecipeKey
    first: date | None
    last: date | None
    material: Cell


@dataclass(frozen=True, slots=True)
class DatedRecord(Record):
    day: date


@dataclass(frozen=True, slots=True)
class Powder(DatedRecord):
    material: Cell


@dataclass(frozen=True, slots=True)
class ShiftRecord(DatedRecord):
    shift: Cell


@dataclass(frozen=True, slots=True)
class Dose(ShiftRecord):
    mass: Cell
    recipe: RecipeKey


@dataclass(frozen=True, slots=True)
class PressNorm(Record):
    raw: Cell
    press: Cell


@dataclass(frozen=True, slots=True)
class Press(ShiftRecord):
    press: Cell
    raw: Cell
    recipe: RecipeKey
    good_units: Cell


@dataclass(frozen=True, slots=True)
class ThermalRecord(ShiftRecord):
    raw: Cell
    recipe: RecipeKey


class WagonLoad(ThermalRecord):
    __slots__ = ()


@dataclass(frozen=True, slots=True)
class Furnace(ThermalRecord):
    exit_day: date | None


@dataclass(frozen=True, slots=True)
class Finishing(DatedRecord):
    product: Cell
    recipe: RecipeKey


@dataclass(frozen=True, slots=True)
class Delivery(DatedRecord):
    product: Cell
    mark: Cell


@dataclass(frozen=True, slots=True)
class Percentage(Record):
    raw_group: Cell
    product_group: Cell


@dataclass(frozen=True, slots=True)
class Downtime(DatedRecord):
    equipment: Cell
    end_day: date | None


RecordT = TypeVar("RecordT", bound=Record)
DatedT = TypeVar("DatedT", bound=DatedRecord)


class ProductionHistory(Protocol):
    def month_rows(self, kind: type[RecordT], month: str) -> Iterable[RecordT]: ...

    def window(self, kind: type[DatedT], first: date, last: date) -> Sequence[DatedT]: ...

    def dated_rows(self, kind: type[DatedT]) -> Sequence[DatedT]: ...
