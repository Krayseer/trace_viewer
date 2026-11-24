"""Read the project XLS books and map spreadsheet columns to production records."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from operator import attrgetter
from pathlib import Path
from typing import Iterable, Sequence, cast

import xlrd

from .records import (
    Book, Cell, Component, DatedRecord, DatedT, Delivery, Dose, Downtime, Field,
    Finishing, Furnace, Order, Percentage, Powder, Press, PressNorm, RecipeKey, Record, RecordT,
    SourceDetails, SourceRef, TITLES, WagonLoad,
)


MONTHS = {
    "январь": 1, "февраль": 2, "март": 3, "апрель": 4, "аперль": 4, "май": 5,
    "июнь": 6, "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10,
    "ноябрь": 11, "декабрь": 12,
}
DATE_COLUMNS = {2: (3, 4), 3: (1,), 4: (0,), 6: (0,), 7: (0,), 8: (2, 4),
                9: (0,), 10: (0,), 12: (5, 6)}
DAY_COLUMN = {3: 1, 4: 0, 6: 0, 7: 0, 8: 2, 9: 0, 10: 0, 12: 5}
SHIFT_COLUMN = {4: 1, 6: 1, 7: 1, 8: 3}
PRODUCTION_DAY = attrgetter("day")
# Key as recorded at each operation: распоряжение, № шихты, доп. марка.
RECIPE_COLUMNS = {2: (0, 7, 8), 4: (6, 8, 9), 6: (8, 10, 11),
                  7: (7, 9, 10), 8: (10, 12, 13), 9: (7, 9, 10)}
DISPLAY_COLUMNS = {
    1: (3, 4, 5, 7, 8, 9), 2: (1, 0, 7, 8, 3, 4, 9, 10, 12),
    3: (1, 2, 4, 3, 8), 4: (0, 1, 2, 4, 6, 8, 9, 12, 14, 15),
    5: (0, 2, 4, 5, 8), 6: (0, 1, 2, 6, 8, 10, 11, 16, 18, 20),
    7: (0, 1, 2, 5, 7, 9, 10, 11), 8: (2, 4, 3, 0, 8, 10, 12, 13, 14),
    9: (0, 2, 5, 7, 9, 10, 11, 13), 10: (0, 1, 6, 8, 9, 10),
    11: (1, 2, 3, 4, 5, 6, 7), 12: (2, 5, 6, 7, 12),
}
DISPLAY_HEADINGS = {
    2: {3: "Начало действия", 4: "Окончание действия"},
    8: {2: "Вход в печь", 4: "Выход из печи"},
}

RECORD_TYPES = (
    Order, Component, Powder, Dose, PressNorm, Press, WagonLoad, Furnace, Finishing, Delivery, Percentage, Downtime,
)
BOOK_BY_RECORD = {kind: book for kind, book in zip(RECORD_TYPES, Book)}
FIELD_COLUMNS = {
    Book.DOSING: {Field.DAY: 0, Field.ORDER_CODE: 6},
    Book.PRESSING: {Field.DAY: 0, Field.ORDER_CODE: 8},
    Book.FURNACES: {Field.EXIT_DAY: 4},
    Book.FINISHING: {Field.DAY: 0, Field.ORDER_CODE: 7, Field.RECIPE_NUMBER: 9, Field.MARK: 10},
    Book.DELIVERIES: {Field.DAY: 0, Field.MARK: 8},
}


def month_id(sheet_name: str) -> str | None:
    parts = sheet_name.casefold().split()
    if len(parts) != 2 or parts[0] not in MONTHS or not parts[1].isdigit():
        return None
    return f"{int(parts[1]):04d}-{MONTHS[parts[0]]:02d}"


def normalize_cell(value: Cell) -> Cell:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.strip()
    return value


def workbook_paths(directory: Path) -> Iterable[tuple[Book, Path]]:
    for file, title in zip(Book, TITLES):
        path = directory / f"{int(file)}. {title}.xls"
        yield file, path if path.is_file() else directory / f"{title}.xls"


@dataclass(frozen=True, slots=True)
class SourceRow:
    ref: SourceRef
    original: tuple[Cell, ...]
    dates: dict[int, datetime]

    def cell(self, column: int) -> Cell:
        return normalize_cell(self.original[column])

    def day(self, column: int) -> date | None:
        return self.dates[column].date() if column in self.dates else None

    def display(self, column: int) -> Cell:
        if column in self.dates:
            value = self.dates[column]
            return value.isoformat(timespec="minutes") if self.ref.file == Book.DOWNTIMES else value.date().isoformat()
        return self.original[column]


@dataclass(slots=True)
class Sheet:
    name: str
    headings: list[str]
    raw_rows: dict[int, SourceRow]
    records: dict[int, Record]


def production_record(row: SourceRow) -> Record | None:
    ref = row.ref
    file = ref.file
    value = row.cell
    if file == Book.ORDERS:
        return Order(ref, value(1), value(2), value(3), value(4), value(5), value(6), value(7), value(8), value(9))
    if file == Book.PRESS_NORMS:
        return PressNorm(ref, value(0), value(2))
    if file == Book.PERCENTAGES:
        return Percentage(ref, value(1), value(2))

    def recipe() -> RecipeKey:
        code, number, mark = RECIPE_COLUMNS[file]
        return RecipeKey(value(code), value(number), value(mark))

    if file == Book.RECIPES:
        return Component(ref, value(1), recipe(), row.day(3), row.day(4), value(9))

    day = row.day(DAY_COLUMN[file])
    if day is None:
        # The original row is still available for inspection by its XLS address.
        return None
    if file == Book.POWDERS:
        return Powder(ref, day, value(2))
    if file == Book.FINISHING:
        return Finishing(ref, day, value(5), recipe())
    if file == Book.DELIVERIES:
        return Delivery(ref, day, value(6), value(8))
    if file == Book.DOWNTIMES:
        return Downtime(ref, day, value(2), row.day(6))

    shift = value(SHIFT_COLUMN[file])
    if file == Book.DOSING:
        return Dose(ref, day, shift, value(4), recipe())
    if file == Book.PRESSING:
        return Press(ref, day, shift, value(2), value(6), recipe(), value(16))
    if file == Book.WAGON_LOADING:
        return WagonLoad(ref, day, shift, value(5), recipe())
    if file == Book.FURNACES:
        return Furnace(ref, day, shift, value(8), recipe(), row.day(4))
    raise ValueError(f"Неизвестная книга: {file}")


class XlsDataset:
    def __init__(self, directory: Path):
        self._paths: dict[int, str] = {}
        self._sheets: dict[tuple[int, str], Sheet] = {}
        self._sheets_by_name: dict[tuple[int, str], Sheet] = {}
        self._by_day: dict[type[DatedRecord], list[DatedRecord]] = defaultdict(list)
        for file, path in workbook_paths(directory):
            self._read_book(file, path)

        self.months = sorted(month for file, month in self._sheets if file == Book.ORDERS)
        if not self.months:
            raise ValueError("В книге заказов не найдены месячные листы")
        for records in self._by_day.values():
            records.sort(key=lambda record: (record.day, record.source.month, record.source.row))

    def _read_book(self, file: Book, path: Path) -> None:
        book = xlrd.open_workbook(str(path), on_demand=True)
        self._paths[file] = path.name
        try:
            for sheet_name in book.sheet_names():
                month = month_id(sheet_name)
                if month is None:
                    continue
                sheet = book.sheet_by_name(sheet_name)
                content = Sheet(sheet_name, list(map(str, sheet.row_values(0))), {}, {})
                self._sheets[file, month] = self._sheets_by_name[file, sheet_name] = content
                for index in range(1, sheet.nrows):
                    values = tuple(sheet.row_values(index))
                    if not any(value != "" for value in values):
                        continue
                    dates = {}
                    for column in DATE_COLUMNS.get(file, ()):
                        if isinstance(values[column], (int, float)) and values[column] > 0:
                            dates[column] = xlrd.xldate_as_datetime(values[column], book.datemode)
                    number = index + 1  # XLS counts the header row and starts at 1.
                    row = SourceRow(SourceRef(file, month, sheet_name, number), values, dates)
                    content.raw_rows[number] = row
                    record = production_record(row)
                    if record is not None:
                        content.records[number] = record
                    if isinstance(record, DatedRecord):
                        self._by_day[type(record)].append(record)
        finally:
            book.release_resources()

    def month_rows(self, kind: type[RecordT], month: str) -> Iterable[RecordT]:
        sheet = self._sheets.get((BOOK_BY_RECORD[kind], month))
        return cast(Iterable[RecordT], sheet.records.values()) if sheet is not None else ()

    def order(self, month: str, number: int) -> Order:
        return cast(Order, self._sheets[Book.ORDERS, month].records[number])

    def dated_rows(self, kind: type[DatedT]) -> Sequence[DatedT]:
        return cast(Sequence[DatedT], self._by_day.get(kind, ()))

    def window(self, kind: type[DatedT], first: date, last: date) -> Sequence[DatedT]:
        records = self.dated_rows(kind)
        start = bisect_left(records, first, key=PRODUCTION_DAY)
        end = bisect_right(records, last, lo=start, key=PRODUCTION_DAY)
        return records[start:end]

    def book_name(self, file: int) -> str:
        return self._paths[file]

    def sheet_name(self, file: int, month: str) -> str:
        return self._sheets[file, month].name

    def source(self, file: int, month: str, number: int) -> SourceDetails:
        sheet = self._sheets[file, month]
        row = sheet.raw_rows[number]
        return SourceDetails(self.book_name(file), sheet.name, number,
                             [(heading, row.display(i)) for i, heading in enumerate(sheet.headings)])

    def stage_columns(self, file: Book, month: str) -> tuple[tuple[int, ...], list[str]]:
        sheet = self._sheets.get((file, month))
        if sheet is None:
            sheet = next(sheet for (book, _), sheet in self._sheets.items() if book == file)
        columns = DISPLAY_COLUMNS[file]
        titles = DISPLAY_HEADINGS.get(file, {})
        return columns, [titles.get(index, sheet.headings[index].strip()) for index in columns]

    def display_values(self, ref: SourceRef, columns: Iterable[int]) -> list[Cell]:
        row = self._sheets_by_name[ref.file, ref.sheet].raw_rows[ref.row]
        return [row.display(column) for column in columns]

    def column_for_field(self, file: Book, field: Field) -> int:
        return FIELD_COLUMNS[file][field]
