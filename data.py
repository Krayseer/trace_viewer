"""Read XLS snapshots and expose inspectable, explicitly tentative links."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from operator import attrgetter
from pathlib import Path
import re

import xlrd


TITLES = (
    "Заказы", "Шихта", "Подача порошков", "Линии дозирования", "Нормы прессовки",
    "Прессовка", "Садка", "Печи", "Доп операции", "Сдача", "Проценты", "Простои",
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
ROUTE_FILES = (3, 4, 6, 7, 8, 9, 10)
INITIAL_ROUTE_FILES = frozenset((3, 4, 6))
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


def month_id(sheet_name: str) -> str | None:
    parts = sheet_name.casefold().split()
    if len(parts) != 2 or parts[0] not in MONTHS or not parts[1].isdigit():
        return None
    return f"{int(parts[1]):04d}-{MONTHS[parts[0]]:02d}"


def cell(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.strip()
    return value


def print_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


@dataclass(frozen=True)
class Row:
    file: int
    month: str
    number: int
    original: tuple
    parsed_dates: dict[int, datetime]

    def __getitem__(self, column):
        return cell(self.original[column])

    def day_at(self, column):
        return self.parsed_dates[column].date() if column in self.parsed_dates else None

    @property
    def day(self):
        return self.day_at(DAY_COLUMN[self.file])

    @property
    def shift(self):
        return self[SHIFT_COLUMN[self.file]]

    @property
    def recipe(self):
        return tuple(self[i] for i in RECIPE_COLUMNS[self.file])

    def display(self, column):
        if column in self.parsed_dates:
            return self.parsed_dates[column].isoformat(timespec="minutes") if self.file == 12 else self.day_at(column).isoformat()
        return self.original[column]


@dataclass
class Version:
    month: str
    mass: int
    order_code: int
    number: int
    start: date
    end: date
    rows: list[Row]

    @property
    def id(self):
        return f"{self.mass}/{self.order_code}/{self.number}/{self.start}/{self.end}"

    @property
    def label(self):
        return f"масса {self.mass} · {self.order_code}/{self.number}"

    @property
    def marks(self):
        return sorted({r[8] for r in self.rows if r[8]})

    def active(self, first, last):
        return self.start <= last and first <= self.end

    def as_dict(self, mark, first, last):
        return {"id": self.id, "label": self.label, "mass": self.mass,
                "order_code": self.order_code, "number": self.number, "marks": self.marks,
                "first": self.start.isoformat(), "last": self.end.isoformat(),
                "rows": len(self.rows), "order_mark": mark in self.marks,
                "active": self.active(first, last)}


class Dataset:
    def __init__(self, directory: Path):
        self.paths = {}
        self.headers = {}
        self.sheets = {}
        self.rows = {}
        self.by_day = defaultdict(list)
        self.coverage_by_month = {}
        for file, title in enumerate(TITLES, 1):
            path = directory / f"{file}. {title}.xls"
            if not path.is_file():
                path = directory / f"{title}.xls"
            book = xlrd.open_workbook(str(path), on_demand=True)
            self.paths[file] = path.name
            try:
                for sheet_name in book.sheet_names():
                    month = month_id(sheet_name)
                    if month is None:
                        continue
                    sheet = book.sheet_by_name(sheet_name)
                    key = (file, month)
                    self.sheets[key] = sheet_name
                    self.headers[key] = list(map(str, sheet.row_values(0)))
                    content = {}
                    for i in range(1, sheet.nrows):
                        values = tuple(sheet.row_values(i))
                        if not any(x != "" for x in values):
                            continue
                        parsed = {}
                        for col in DATE_COLUMNS.get(file, ()):
                            if isinstance(values[col], (int, float)) and values[col] > 0:
                                parsed[col] = xlrd.xldate_as_datetime(values[col], book.datemode)
                        row = Row(file, month, i + 1, values, parsed)
                        content[row.number] = row
                        if file in DAY_COLUMN and row.day:
                            self.by_day[file].append(row)
                    self.rows[key] = content
            finally:
                book.release_resources()
        self.months = sorted(month for file, month in self.rows if file == 1)
        if not self.months:
            raise ValueError("В книге заказов не найдены месячные листы")
        for entries in self.by_day.values():
            entries.sort(key=lambda r: (r.day, r.month, r.number))
        self.versions = defaultdict(dict)
        self.catalog_keys = defaultdict(list)
        for month in self.months:
            for row in self.month_rows(2, month):
                first, last = row.day_at(3), row.day_at(4)
                if not (first and last and row[1] and row[0] and row[7]):
                    continue
                version = Version(month, row[1], row[0], row[7], first, last, [])
                self.versions[month].setdefault(version.id, version).rows.append(row)
            for version in self.versions[month].values():
                for mark in version.marks:
                    self.catalog_keys[month, (version.order_code, version.number, mark)].append(version)

    def month_rows(self, file, month):
        return self.rows.get((file, month), {}).values()

    def window(self, file, first, last):
        rows = self.by_day[file]
        start = bisect_left(rows, first, key=PRODUCTION_DAY)
        end = bisect_right(rows, last, lo=start, key=PRODUCTION_DAY)
        return rows[start:end]

    def row(self, file, month, number):
        return self.rows[file, month][number]

    def source(self, file, month, number):
        row = self.row(file, month, number)
        return {"file": self.paths[file], "sheet": self.sheets[file, month], "row": number,
                "columns": [{"name": header, "value": row.display(i)}
                            for i, header in enumerate(self.headers[file, month])]}

    def orders(self, month):
        if month not in self.months:
            raise ValueError("Нет такого листа заказов")
        return [{"row": r.number, "mass": r[3], "raw": r[4], "product": r[5], "name": r[6],
                 "mark": r[7], "base": r[8], "extra": r[9]} for r in self.month_rows(1, month) if r[3]]

    def order_coverage(self, month):
        if month not in self.coverage_by_month:
            orders = self.orders(month)
            first, last = month_window(month)
            scores = [
                Trace(self, self.row(1, month, order["row"]), "auto", first, last, None).coverage()
                for order in orders
            ]
            scores.sort(key=lambda score: (-score["covered"], score["conflicts"], score["ambiguous"],
                                           not score["same_shift"], score["row"]))
            self.coverage_by_month[month] = {"stage_count": len(ROUTE_FILES), "orders": scores}
        return self.coverage_by_month[month]

    def resolve(self, row):
        return [v for v in self.catalog_keys.get((row.month, row.recipe), ()) if v.active(row.day, row.day)]

    def row_card(self, row, tone, basis):
        return {"month": row.month, "sheet": self.sheets[row.file, row.month], "row": row.number,
                "tone": tone, "basis": basis,
                "values": [row.display(i) for i in DISPLAY_COLUMNS[row.file]]}

    def stage(self, file, month, tone, text, rows):
        headings = self.headers.get((file, month))
        if headings is None:
            headings = next(value for (f, _), value in self.headers.items() if f == file)
        titles = DISPLAY_HEADINGS.get(file, {})
        return {"file": file, "title": TITLES[file - 1], "source": self.paths[file], "tone": tone,
                "summary": text, "rows": rows,
                "column_ids": DISPLAY_COLUMNS[file],
                "columns": [titles.get(i, headings[i].strip()) for i in DISPLAY_COLUMNS[file]]}

    def trace(self, month, number, recipe_filter, first, last, shift=None):
        order = self.row(1, month, number)
        if not order[3]:
            raise ValueError("В строке отсутствует марка массы")
        trace = Trace(self, order, recipe_filter, first, last, shift)
        return trace.build()


class Trace:
    def __init__(self, data, order, recipe_filter, first, last, shift):
        self.data, self.order = data, order
        self.month, self.first, self.last, self.shift = order.month, first, last, shift
        self.raw, self.product, self.mark = order[4], order[5], order[7]
        self.versions = sorted(
            (v for v in data.versions[self.month].values() if v.mass == order[3]),
            key=lambda v: (self.mark not in v.marks, not v.active(first, last), v.number, v.order_code),
        )
        if recipe_filter == "auto":
            strict = [v for v in self.versions if self.mark in v.marks and v.active(first, last)]
            recipe_filter = strict[0].id if len(strict) == 1 else "all"
        if recipe_filter != "all" and recipe_filter not in {v.id for v in self.versions}:
            raise ValueError("Версия рецептуры отсутствует в каталоге этой марки массы")
        self.recipe_filter = recipe_filter
        self.selected = [v for v in self.versions if recipe_filter == "all" or recipe_filter == v.id]
        self.active = [v for v in self.selected if v.active(first, last)]
        self.active_ids = {v.id for v in self.active}
        self.by_key = defaultdict(list)
        for v in self.selected:
            for mark in v.marks:
                self.by_key[v.order_code, v.number, mark].append(v)
        self.dose = [r for r in self.production(4) if self.same_dose(r)]
        self.nearby_dose = [] if self.dose else [
            r for r in self.data.window(4, self.first - timedelta(days=7), self.last + timedelta(days=7))
            if not self.first <= r.day <= self.last and self.same_dose(r)
        ]
        self.press = [(r, self.press_tone(r)) for r in self.production(6) if self.raw and r[6] == self.raw]
        self.press = [(r, tone) for r, tone in self.press if tone]
        self.press_groups = defaultdict(list)
        for r, _ in self.press:
            self.press_groups[r.recipe].append(r)

    def production(self, file):
        return [r for r in self.data.window(file, self.first, self.last)
                if self.shift is None or r.shift == self.shift]

    def same_dose(self, row):
        return any(v.mass == row[4] and v.active(row.day, row.day) for v in self.by_key.get(row.recipe, ()))

    def press_tone(self, row):
        resolved = self.data.resolve(row)
        if len(resolved) == 1 and resolved[0].id in self.active_ids:
            return "match"
        if not all(row.recipe):
            return "conflict"
        # Show conflicts for the order's mark or for a selected number and mark.
        if any(v.id in self.active_ids for v in resolved) or any(
            key[1:] == row.recipe[1:] for key in self.by_key
        ) or (self.recipe_filter == "all" and self.mark and row[11] == self.mark):
            return "conflict"
        if self.mark and row[11] == self.mark and any(self.mark in v.marks for v in self.selected):
            return "conflict"
        return None

    def make(self, file, tone, summary, cards):
        return self.data.stage(file, self.month, tone if cards else "empty", summary, cards)

    def cards(self, rows, tone, basis):
        return [self.data.row_card(r, tone, basis(r) if callable(basis) else basis) for r in rows]

    def recipe_stage(self):
        cards = []
        for v in self.selected:
            basis = "Совпали марка массы и доп. марка заказа." if self.mark in v.marks else "Совпала марка массы. Доп. марка отличается."
            tone = "match" if self.mark in v.marks and v in self.active else "candidate"
            if v not in self.active:
                basis += " Срок действия вне выбранного периода."
            cards.extend(self.cards(v.rows, tone, basis))
        return self.make(2, "candidate", "Выберите версию, чтобы увидеть её компоненты. Технологическая допустимость для заказа требует подтверждения.", cards)

    def powders(self):
        parts = defaultdict(set)
        for v in self.active:
            for r in v.rows:
                parts[r[9]].add(v.id)
        rows = [r for r in self.data.window(3, self.first - timedelta(days=1), self.last) if r[2] in parts]
        cards = self.cards(rows, "context", lambda r:
            f"Материал {r[2]} найден в составе выбранных версий ({len(parts[r[2]])}). Дата близка к периоду. Привязка к замесу отсутствует.")
        return self.make(3, "context", "Поиск по коду компонента из состава. Включён один день перед периодом. Общего номера партии со стадией дозирования нет.", cards)

    def dosing(self):
        cards = self.cards(self.dose, "match", "Совпали масса, распоряжение, № шихты и доп. марка. Дата входит в срок действия версии. Номер замеса отсутствует.")
        if not cards:
            cards = self.cards(self.nearby_dose, "context", lambda r:
                "Совпали масса, распоряжение, № шихты и доп. марка. " +
                ("Запись позже выбранного периода." if r.day > self.last else "Запись раньше выбранного периода."))
        tone = "match" if self.dose else "context"
        text = "Каждая строка описывает компонент. Для связи с прессовкой нужен номер партии смеси."
        if self.nearby_dose:
            text = "В периоде строк по выбранным фильтрам нет. Соседние даты показаны по ключу версии и сроку её действия, для всех смен."
        stage = self.make(4, tone, text, cards)
        stage["outside_period"] = bool(self.nearby_dose)
        return stage

    def press_norms(self):
        codes = {str(r[2]) for r, _ in self.press}
        matching_raw = [r for r in self.data.month_rows(5, self.month) if r[0] == self.raw]
        selected = [r for r in matching_raw if codes.intersection(re.findall(r"\d+", str(r[2])))]
        return self.make(5, "context", "Справочник по коду сырца и прессу. Запись о применении нормы в выпуске отсутствует.",
                         self.cards(selected or matching_raw, "context", "Совпал код сырца и пресс." if selected else "Совпал код сырца."))

    def pressing(self):
        cards = []
        for r, tone in self.press:
            resolved = self.data.resolve(r)
            labels = ", ".join(v.label for v in resolved[:4]) or "версия не найдена в каталоге"
            if tone == "match":
                reason = "Совпали сырец заказа, распоряжение, № шихты и доп. марка выбранной версии."
            elif not all(r.recipe):
                missing = ", ".join(name for name, value in zip(("распоряжение", "№ шихты", "доп. марка"), r.recipe) if not value)
                reason = f"Совпал сырец заказа. Не заполнено: {missing}."
            elif len(resolved) > 1:
                reason = "Совпал сырец заказа. По ключу шихты действуют несколько записей справочника."
            else:
                same_number_mark = [k[0] for k in self.by_key if k[1:] == r.recipe[1:]]
                if same_number_mark and r[8] not in same_number_mark:
                    expected = ", ".join(map(str, sorted(set(same_number_mark), key=str)))
                    reason = f"Совпали сырец, № шихты и доп. марка. Распоряжение {r[8]} отличается от выбранного ({expected})."
                else:
                    reason = "Совпал сырец заказа. Связи по полному ключу с действующей выбранной версией нет."
            cards.append(self.data.row_card(r, tone, f"{reason} По справочнику: {labels}. Номер партии смеси отсутствует."))
        tone = "conflict" if any(t == "conflict" for _, t in self.press) else "match"
        return self.make(6, tone, "Поиск по сырцу заказа. Видны записи по выбранной версии и близкие записи с расхождением ключа.", cards)

    def later_production(self, file, raw_col, upstream):
        rows = [r for r in self.production(file) if r[raw_col] == self.raw and r.recipe in self.press_groups
                and any(p.day <= r.day for p in self.press_groups[r.recipe])]
        cards = []
        for r in rows:
            same = sum(p.recipe == r.recipe and p.day == r.day and p.shift == r.shift for p in upstream)
            origin = "Нет ссылки на выпуск прессовки." if file == 7 else "Нет номера вагонетки или ссылки на садку."
            cards.append(self.data.row_card(r, "candidate", f"Сырец и поля рецептуры совпали с прессовкой. Записей предыдущего этапа с теми же датой и сменой: {same}. {origin}"))
        text = "Совпадения по сырцу, рецептуре и хронологии дают список кандидатов. Количество не подтверждает перемещение."
        return self.make(file, "candidate", text, cards), rows

    def finishing(self, furnaces):
        exits = [r.day_at(4) for r in furnaces if r.day_at(4)]
        earliest = min(exits, default=None)
        horizon = max([self.last] + exits) + timedelta(days=4)
        ops = [r for r in self.data.window(9, self.first, horizon) if r[5] == self.product]
        deliveries = [r for r in self.data.window(10, self.first, horizon) if r[6] == self.product]
        conflict_fields = {9: defaultdict(set), 10: defaultdict(set)}
        press_key_values = [set(values) for values in zip(*self.press_groups)]
        op_cards = []
        for r in ops:
            recipe = r.recipe
            same = recipe in self.press_groups
            early = earliest is not None and r.day < earliest
            if early:
                conflict_fields[9][8].add(4)
                conflict_fields[9][9].add(0)
            if not same:
                for column, value, expected in zip(RECIPE_COLUMNS[9], recipe, press_key_values):
                    if value not in expected:
                        conflict_fields[9][9].add(column)
            basis = "Совпал код готового изделия. " + ("Рецептура совпала с одной из прессовок. " if same else "Ключ рецептуры не совпал с показанной прессовкой. ")
            basis += "Дата раньше всех показанных выходов из печи." if early else "Нет номера исходной партии."
            op_cards.append(self.data.row_card(r, "conflict" if early or not same else "candidate", basis))
        delivery_cards = []
        for r in deliveries:
            same = r[8] == self.mark
            early = earliest is not None and r.day < earliest
            if early:
                conflict_fields[10][10].add(0)
            if not same:
                conflict_fields[10][10].add(8)
            basis = "Совпал код готового изделия. " + ("Совпала доп. марка. " if same else f"Доп. марка отличается («{r[8]}»). ")
            basis += "Дата раньше всех показанных выходов из печи." if early else "Партия сдачи не указывает на выпуск и версию шихты."
            delivery_cards.append(self.data.row_card(r, "conflict" if early or not same else "candidate", basis))
        text = f"Поиск по коду готового изделия до {print_date(horizon)} включительно."
        return (self.make(9, "candidate", text + " Ранние строки и отличающиеся ключи видны как расхождения.", op_cards),
                self.make(10, "candidate", text + " В сдаче нет версии шихты. Расхождения дат и доп. марки видны в таблице.", delivery_cards),
                conflict_fields)

    def gaps(self, stages, furnaces, conflict_fields):
        dose_slots = defaultdict(list)
        press_slots = defaultdict(list)
        for r in self.dose:
            dose_slots[r.day, r.shift, r.recipe[1:]].append(r)
        for r, tone in self.press:
            if tone == "conflict":
                press_slots[r.day, r.shift, r.recipe[1:]].append(r)
        conflicts = []
        for slot in dose_slots.keys() & press_slots.keys():
            for d in dose_slots[slot]:
                for p in press_slots[slot]:
                    if d[6] != p[8]:
                        conflicts.append((d, p))
        if conflicts:
            # Prefer a shift with several press entries, then choose the first XLS pair.
            d, p = min(conflicts, key=lambda pair: (
                -len(press_slots[pair[1].day, pair[1].shift, pair[1].recipe[1:]]),
                pair[1].day, pair[1].shift, pair[0].number, pair[1].number,
            ))
            mass = ", ".join(str(v.mass) for v in self.data.resolve(p)) or "не определена"
            main = {"tone": "conflict", "title": "Расходятся коды распоряжений",
                    "text": f"{print_date(d.day)}, смена {d.shift}. Совпали № шихты {d[8]} и доп. марка {d[9]}.",
                    "missing": "Нет номера партии смеси и записи о её передаче на прессовку.",
                    "left": f"Дозирование · {d[6]}/{d[8]} · масса {d[4]}",
                    "right": f"Прессовка · {p[8]}/{p[10]} · масса по шихте {mass}",
                    "field_conflicts": {4: [6], 6: [8]},
                    "links": [self.ref(d), self.ref(p)]}
        elif self.press and not self.dose:
            p = self.press[0][0]
            main = {"tone": "conflict", "title": "За выбранный период дозирование не найдено",
                    "text": f"Прессовка найдена {print_date(p.day)}. В пределах семи соседних дней совпадений по ключу выбранной шихты нет.",
                    "links": [self.ref(p)]}
            if self.nearby_dose:
                d = min(self.nearby_dose, key=lambda r: (r.recipe != p.recipe, abs(r.day - p.day)))
                order = "позже" if d.day > p.day else "раньше"
                main.update(
                    title=f"Дозирование {order} прессовки · вне периода",
                    text=("Ключ шихты совпал." if d.recipe == p.recipe
                          else "Ключи шихты у этих записей различаются."),
                    left=f"Дозирование · {print_date(d.day)}",
                    right=f"Прессовка · {print_date(p.day)}",
                    field_conflicts={4: [0], 6: [0]},
                    missing="Для подтверждения передачи смеси нужен номер партии.",
                    links=[self.ref(d), self.ref(p)],
                )
        elif not self.press:
            main = {"tone": "candidate", "title": "Прессовка по выбранным фильтрам не найдена",
                    "help": "Поиск прессовки идёт по сырцу заказа и полям шихты. Для связи с дозированием нужна запись о передаче партии.",
                    "links": []}
        else:
            main = {"tone": "candidate", "title": "Нет записи о передаче смеси",
                    "help": "По коду определяется версия рецептуры. Чтобы связать порцию смеси с выпуском, нужна запись о передаче партии.", "links": []}
        main["matching_slot"] = self.matching_slot()
        press_count = defaultdict(list)
        for p, _ in self.press:
            press_count[p.day, p.shift, p.recipe, p[2]].append(p)
        group = next((rows for rows in press_count.values() if len(rows) > 1), None)
        if group:
            day, shift = group[0].day, group[0].shift
            quantities = " и ".join(str(r[16]) for r in group[:4])
            second = {"tone": "ambiguous", "title": "Несколько прессовок с одинаковыми полями",
                      "text": f"{print_date(day)}, смена {shift}. Годное: {quantities} шт. У вагонеток нет ссылки на одну из этих строк.",
                      "links": [self.ref(p) for p in group[:4]]}
        else:
            second = {"tone": "candidate", "title": "У садки нет ссылки на выпуск прессовки",
                      "help": "Кандидатов ищут по сырцу, ключу шихты и дате. Для подтверждения нужна запись о загрузке конкретного выпуска на вагонетку.",
                      "links": []}

        def finishing_gap(file, title, explanation):
            rows = [r for r in stages[file - 1]["rows"] if r["tone"] == "conflict"]
            links = [{**self.ref(self.data.row(file, r["month"], r["row"])), "basis": r["basis"]} for r in rows[:2]]
            return {"to": file, "tone": "conflict" if rows else "candidate", "title": title,
                    "help": explanation, "count": len(rows), "links": links,
                    "field_conflicts": {source: sorted(fields) for source, fields in conflict_fields[file].items()}}

        main["to"] = 6
        second["to"] = 7
        return [
            main, second,
            {"to": 4, "tone": "candidate", "title": "Нет номера партии порошка",
             "help": "Подача найдена по коду компонента и близкой дате. Нужна запись о том, из какой партии порошка дозировали компонент.",
             "links": []},
            {"to": 8, "tone": "candidate", "title": "В печах нет номера вагонетки",
             "help": "Кандидатов ищут по сырцу, ключу шихты и дате. Для связи с садкой нужна запись о входе конкретной вагонетки в печь.",
             "links": [self.ref(r) for r in furnaces[:2]]},
            finishing_gap(9, "Нет ссылки на партию из печи",
                          "Дополнительные операции найдены по коду изделия. Проверены ключ шихты относительно прессовки и дата относительно выходов из печи."),
            finishing_gap(10, "Нет связи между дополнительными операциями и партией сдачи",
                          "Сдача найдена по коду изделия. Проверены доп. марка заказа и дата относительно выходов из печи. Нужен журнал передачи партии."),
        ]

    def ref(self, row):
        return {"file": row.file, "month": row.month, "row": row.number,
                "label": f"{TITLES[row.file - 1]}, строка {row.number}"}

    def build(self):
        stages = [self.make(1, "context", "Исходная строка месячного листа. В книге нет сквозного номера заказа.",
                            self.cards([self.order], "context", "Исходная строка заказа.")),
                  self.recipe_stage(), self.powders(), self.dosing(), self.press_norms(), self.pressing()]
        sadka, wagons = self.later_production(7, 5, [r for r, _ in self.press])
        ovens, furnaces = self.later_production(8, 8, wagons)
        ops, delivered, conflict_fields = self.finishing(furnaces)
        percent = [r for r in self.data.month_rows(11, self.month) if (r[1], r[2]) == (self.order[1], self.order[2])]
        presses = {p[2] for p, _ in self.press}
        stops = [r for r in self.data.by_day[12] if r[2] in presses and r.day <= self.last
                 and (r.day_at(6) or r.day) >= self.first]
        stages.extend([sadka, ovens, ops, delivered,
                       self.make(11, "context", "Групповые проценты по кодам групп сырца и изделия.",
                                 self.cards(percent, "context", "Совпали обе группы. Результат заказа в этой таблице отсутствует.")),
                       self.make(12, "context", "Оборудование и пересечение дат простоя с выбранным периодом.",
                                 self.cards(stops, "context", "Совпал код пресса. Связь простоя с конкретным выпуском отсутствует."))])
        return {"recipe": self.recipe_filter, "versions": [v.as_dict(self.mark, self.first, self.last) for v in self.versions],
                "active_count": sum(v.active(self.first, self.last) for v in self.versions),
                "stages": stages, "gaps": self.gaps(stages, furnaces, conflict_fields)}

    def coverage(self):
        trace = self.build()
        stages = [stage for stage in trace["stages"] if stage["file"] in ROUTE_FILES]
        covered = {
            stage["file"] for stage in stages if not stage.get("outside_period")
            and any(row["tone"] != "conflict" for row in stage["rows"])
        }
        conflicts = {stage["file"] for stage in stages if any(row["tone"] == "conflict" for row in stage["rows"])}
        conflicts.update(gap["to"] for gap in trace["gaps"] if gap["tone"] == "conflict")
        return {"row": self.order.number, "covered": len(covered), "conflicts": len(conflicts),
                "ambiguous": sum(gap["tone"] == "ambiguous" for gap in trace["gaps"]),
                "initial_stages": INITIAL_ROUTE_FILES <= covered,
                "same_shift": next(gap["matching_slot"] for gap in trace["gaps"] if gap["to"] == 6)}

    def matching_slot(self):
        dose_slots = {(row.day, row.shift, row.recipe) for row in self.dose if row.shift in (1, 2)}
        return any(tone == "match" and (row.day, row.shift, row.recipe) in dose_slots for row, tone in self.press)


def month_window(month):
    first = date.fromisoformat(month + "-01")
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])
