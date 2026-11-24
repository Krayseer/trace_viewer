"""Select candidate production records, compare transitions, and score route coverage."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
import re
from typing import Iterable, Mapping, TypeVar, TypedDict

from .recipes import RecipeCatalog, Version
from .records import (
    Book, Cell, Delivery, Dose, Downtime, Field, Finishing, Furnace, Order, Percentage, Powder,
    Press, PressNorm, ProductionHistory, RecipeKey, Record, ShiftRecord, SourceRef, ThermalRecord, WagonLoad,
)


ROUTE_FILES = (Book.POWDERS, Book.DOSING, Book.PRESSING, Book.WAGON_LOADING,
               Book.FURNACES, Book.FINISHING, Book.DELIVERIES)
INITIAL_ROUTE_FILES = frozenset((Book.POWDERS, Book.DOSING, Book.PRESSING))
RECIPE_FIELDS = (Field.ORDER_CODE, Field.RECIPE_NUMBER, Field.MARK)
ShiftT = TypeVar("ShiftT", bound=ShiftRecord)
ThermalT = TypeVar("ThermalT", bound=ThermalRecord)
ConflictFields = dict[Book, set[Field]]


@dataclass(frozen=True, slots=True)
class RowMatch:
    source: SourceRef
    tone: str
    basis: str


@dataclass(frozen=True, slots=True)
class Stage:
    file: Book
    tone: str
    summary: str
    rows: list[RowMatch]
    outside_period: bool | None = None


class Transition(TypedDict, total=False):
    to: Book
    tone: str
    title: str
    text: str
    help: str
    missing: str
    left: str
    right: str
    field_conflicts: ConflictFields
    links: list[SourceRef | RowMatch]
    count: int
    matching_slot: bool


@dataclass(frozen=True, slots=True)
class TraceResult:
    month: str
    first: date
    last: date
    mark: Cell
    recipe: str
    versions: list[Version]
    stages: list[Stage]
    gaps: list[Transition]


@dataclass(frozen=True, slots=True)
class Coverage:
    row: int
    covered: int
    conflicts: int
    ambiguous: int
    initial_stages: bool
    same_shift: bool

    def rank(self) -> tuple[int, int, int, bool, int]:
        return (-self.covered, self.conflicts, self.ambiguous, not self.same_shift, self.row)


def print_date(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def stage(file: Book, tone: str, summary: str, rows: list[RowMatch], outside_period: bool | None = None) -> Stage:
    return Stage(file, tone if rows else "empty", summary, rows, outside_period)


def with_basis(rows: Iterable[Record], tone: str, basis: str) -> list[RowMatch]:
    return [RowMatch(row.source, tone, basis) for row in rows]


class Trace:
    def __init__(
        self, history: ProductionHistory, catalogs: Mapping[str, RecipeCatalog], order: Order,
        recipe_filter: str, first: date, last: date, shift: int | None,
    ):
        self.history = history
        self.catalogs = catalogs
        self.order = order
        self.month = order.source.month
        self.first, self.last, self.shift = first, last, shift
        self.versions = catalogs[self.month].for_order(order.mass, order.mark, first, last)
        if recipe_filter == "auto":
            strict = [v for v in self.versions if order.mark in v.marks and v.active(first, last)]
            recipe_filter = strict[0].id if len(strict) == 1 else "all"
        if recipe_filter != "all" and recipe_filter not in {v.id for v in self.versions}:
            raise ValueError("Версия рецептуры отсутствует в каталоге этой марки массы")
        self.recipe_filter = recipe_filter
        self.selected = [v for v in self.versions if recipe_filter == "all" or recipe_filter == v.id]
        self.active = [v for v in self.selected if v.active(first, last)]
        self.active_ids = {v.id for v in self.active}
        self.by_key: dict[RecipeKey, list[Version]] = defaultdict(list)
        for version in self.selected:
            for mark in version.marks:
                key = RecipeKey(version.order_code, version.number, mark)
                self.by_key[key].append(version)
        self.dose = [row for row in self.production(Dose) if self.same_dose(row)]
        # Neighboring dosing rows are shown only when the exact search is empty, for both shifts.
        self.nearby_dose = [] if self.dose else [
            row for row in history.window(Dose, first - timedelta(days=7), last + timedelta(days=7))
            if not first <= row.day <= last and self.same_dose(row)
        ]
        pressing = [(row, self.press_tone(row)) for row in self.production(Press) if order.raw and row.raw == order.raw]
        self.press = [(row, tone) for row, tone in pressing if tone]
        self.press_groups: dict[RecipeKey, list[Press]] = defaultdict(list)
        for row, _ in self.press:
            self.press_groups[row.recipe].append(row)

    def production(self, kind: type[ShiftT]) -> list[ShiftT]:
        return [row for row in self.history.window(kind, self.first, self.last)
                if self.shift is None or row.shift == self.shift]

    def resolve(self, row: Press) -> list[Version]:
        catalog = self.catalogs.get(row.source.month)
        return catalog.resolve(row.recipe, row.day) if catalog is not None else []

    def same_dose(self, row: Dose) -> bool:
        return any(v.mass == row.mass and v.active(row.day, row.day) for v in self.by_key.get(row.recipe, ()))

    def press_tone(self, row: Press) -> str | None:
        resolved = self.resolve(row)
        if len(resolved) == 1 and resolved[0].id in self.active_ids:
            return "match"
        if not all(row.recipe):
            return "conflict"
        # Show conflicts for the order's mark or for a selected number and mark.
        mark = self.order.mark
        if any(v.id in self.active_ids for v in resolved) or any(
            key.number == row.recipe.number and key.mark == row.recipe.mark for key in self.by_key
        ) or (self.recipe_filter == "all" and mark and row.recipe.mark == mark):
            return "conflict"
        if mark and row.recipe.mark == mark and any(mark in v.marks for v in self.selected):
            return "conflict"
        return None

    def recipe_stage(self) -> Stage:
        cards = []
        for version in self.selected:
            same_mark = self.order.mark in version.marks
            basis = "Совпали марка массы и доп. марка заказа." if same_mark else "Совпала марка массы. Доп. марка отличается."
            tone = "match" if same_mark and version in self.active else "candidate"
            if version not in self.active:
                basis += " Срок действия вне выбранного периода."
            cards.extend(with_basis(version.rows, tone, basis))
        return stage(Book.RECIPES, "candidate", "Выберите версию, чтобы увидеть её компоненты. Технологическая допустимость для заказа требует подтверждения.", cards)

    def powders(self) -> Stage:
        parts: dict[Cell, set[str]] = defaultdict(set)
        for version in self.active:
            for row in version.rows:
                parts[row.material].add(version.id)
        rows = self.history.window(Powder, self.first - timedelta(days=1), self.last)
        cards = [
            RowMatch(row.source, "context", f"Материал {row.material} найден в составе выбранных версий ({len(parts[row.material])}). Дата близка к периоду. Привязка к замесу отсутствует.")
            for row in rows if row.material in parts
        ]
        return stage(Book.POWDERS, "context", "Поиск по коду компонента из состава. Включён один день перед периодом. Общего номера партии со стадией дозирования нет.", cards)

    def dosing(self) -> Stage:
        cards = with_basis(self.dose, "match", "Совпали масса, распоряжение, № шихты и доп. марка. Дата входит в срок действия версии. Номер замеса отсутствует.")
        tone = "match" if self.dose else "context"
        text = "Каждая строка описывает компонент. Для связи с прессовкой нужен номер партии смеси."
        if self.nearby_dose:
            text = "В периоде строк по выбранным фильтрам нет. Соседние даты показаны по ключу версии и сроку её действия, для всех смен."
            for row in self.nearby_dose:
                when = "Запись позже выбранного периода." if row.day > self.last else "Запись раньше выбранного периода."
                cards.append(RowMatch(row.source, tone, "Совпали масса, распоряжение, № шихты и доп. марка. " + when))
        return stage(Book.DOSING, tone, text, cards, outside_period=bool(self.nearby_dose))

    def press_norms(self) -> Stage:
        codes = {str(row.press) for row, _ in self.press}
        matching_raw = [row for row in self.history.month_rows(PressNorm, self.month) if row.raw == self.order.raw]
        selected = [row for row in matching_raw if codes.intersection(re.findall(r"\d+", str(row.press)))]
        return stage(Book.PRESS_NORMS, "context", "Справочник по коду сырца и прессу. Запись о применении нормы в выпуске отсутствует.",
                     with_basis(selected or matching_raw, "context", "Совпал код сырца и пресс." if selected else "Совпал код сырца."))

    def pressing(self) -> Stage:
        cards = []
        for row, tone in self.press:
            resolved = self.resolve(row)
            labels = ", ".join(v.label for v in resolved[:4]) or "версия не найдена в каталоге"
            if tone == "match":
                reason = "Совпали сырец заказа, распоряжение, № шихты и доп. марка выбранной версии."
            elif not all(row.recipe):
                missing = ", ".join(name for name, value in zip(("распоряжение", "№ шихты", "доп. марка"), row.recipe) if not value)
                reason = f"Совпал сырец заказа. Не заполнено: {missing}."
            elif len(resolved) > 1:
                reason = "Совпал сырец заказа. По ключу шихты действуют несколько записей справочника."
            else:
                same_number_mark = [key.order_code for key in self.by_key
                                    if key.number == row.recipe.number and key.mark == row.recipe.mark]
                if same_number_mark and row.recipe.order_code not in same_number_mark:
                    expected = ", ".join(map(str, sorted(set(same_number_mark), key=str)))
                    reason = f"Совпали сырец, № шихты и доп. марка. Распоряжение {row.recipe.order_code} отличается от выбранного ({expected})."
                else:
                    reason = "Совпал сырец заказа. Связи по полному ключу с действующей выбранной версией нет."
            cards.append(RowMatch(row.source, tone, f"{reason} По справочнику: {labels}. Номер партии смеси отсутствует."))
        tone = "conflict" if any(tone == "conflict" for _, tone in self.press) else "match"
        return stage(Book.PRESSING, tone, "Поиск по сырцу заказа. Видны записи по выбранной версии и близкие записи с расхождением ключа.", cards)

    def later_production(
        self, kind: type[ThermalT], file: Book, upstream: Iterable[Press | WagonLoad],
    ) -> tuple[Stage, list[ThermalT]]:
        rows = [row for row in self.production(kind)
                if row.raw == self.order.raw and row.recipe in self.press_groups
                and any(press.day <= row.day for press in self.press_groups[row.recipe])]
        origin = "Нет ссылки на выпуск прессовки." if file == Book.WAGON_LOADING else "Нет номера вагонетки или ссылки на садку."
        cards = []
        for row in rows:
            same = sum(previous.recipe == row.recipe and previous.day == row.day and previous.shift == row.shift
                       for previous in upstream)
            cards.append(RowMatch(row.source, "candidate", f"Сырец и поля рецептуры совпали с прессовкой. Записей предыдущего этапа с теми же датой и сменой: {same}. {origin}"))
        text = "Совпадения по сырцу, рецептуре и хронологии дают список кандидатов. Количество не подтверждает перемещение."
        return stage(file, "candidate", text, cards), rows

    def finishing(self, furnaces: list[Furnace]) -> tuple[Stage, Stage, ConflictFields, ConflictFields]:
        exits = [row.exit_day for row in furnaces if row.exit_day]
        earliest = min(exits, default=None)
        horizon = max([self.last] + exits) + timedelta(days=4)
        ops = [row for row in self.history.window(Finishing, self.first, horizon) if row.product == self.order.product]
        deliveries = [row for row in self.history.window(Delivery, self.first, horizon) if row.product == self.order.product]
        op_conflicts: ConflictFields = defaultdict(set)
        press_key_values = [set(values) for values in zip(*self.press_groups)]
        op_cards = []
        for row in ops:
            same = row.recipe in self.press_groups
            early = earliest is not None and row.day < earliest
            if early:
                op_conflicts[Book.FURNACES].add(Field.EXIT_DAY)
                op_conflicts[Book.FINISHING].add(Field.DAY)
            if not same:
                for field, value, expected in zip(RECIPE_FIELDS, row.recipe, press_key_values):
                    if value not in expected:
                        op_conflicts[Book.FINISHING].add(field)
            basis = "Совпал код готового изделия. " + ("Рецептура совпала с одной из прессовок. " if same else "Ключ рецептуры не совпал с показанной прессовкой. ")
            basis += "Дата раньше всех показанных выходов из печи." if early else "Нет номера исходной партии."
            op_cards.append(RowMatch(row.source, "conflict" if early or not same else "candidate", basis))
        delivery_conflicts: ConflictFields = defaultdict(set)
        delivery_cards = []
        for row in deliveries:
            same = row.mark == self.order.mark
            early = earliest is not None and row.day < earliest
            if early:
                delivery_conflicts[Book.DELIVERIES].add(Field.DAY)
            if not same:
                delivery_conflicts[Book.DELIVERIES].add(Field.MARK)
            basis = "Совпал код готового изделия. " + ("Совпала доп. марка. " if same else f"Доп. марка отличается («{row.mark}»). ")
            basis += "Дата раньше всех показанных выходов из печи." if early else "Партия сдачи не указывает на выпуск и версию шихты."
            delivery_cards.append(RowMatch(row.source, "conflict" if early or not same else "candidate", basis))
        text = f"Поиск по коду готового изделия до {print_date(horizon)} включительно."
        return (
            stage(Book.FINISHING, "candidate", text + " Ранние строки и отличающиеся ключи видны как расхождения.", op_cards),
            stage(Book.DELIVERIES, "candidate", text + " В сдаче нет версии шихты. Расхождения дат и доп. марки видны в таблице.", delivery_cards),
            op_conflicts, delivery_conflicts,
        )

    def matching_slot(self) -> bool:
        dose_slots = {(row.day, row.shift, row.recipe) for row in self.dose if row.shift in (1, 2)}
        return any(tone == "match" and (row.day, row.shift, row.recipe) in dose_slots for row, tone in self.press)

    def pressing_gap(self) -> Transition:
        dose_slots: dict[tuple[date, Cell, Cell, Cell], list[Dose]] = defaultdict(list)
        press_slots: dict[tuple[date, Cell, Cell, Cell], list[Press]] = defaultdict(list)
        for row in self.dose:
            dose_slots[row.day, row.shift, row.recipe.number, row.recipe.mark].append(row)
        for row, tone in self.press:
            if tone == "conflict":
                press_slots[row.day, row.shift, row.recipe.number, row.recipe.mark].append(row)
        conflicts = []
        for slot in dose_slots.keys() & press_slots.keys():
            for dose in dose_slots[slot]:
                for press in press_slots[slot]:
                    if dose.recipe.order_code != press.recipe.order_code:
                        conflicts.append((dose, press))
        if conflicts:
            # Prefer a shift with several press entries, then choose the first XLS pair.
            dose, press = min(conflicts, key=lambda pair: (
                -len(press_slots[pair[1].day, pair[1].shift, pair[1].recipe.number, pair[1].recipe.mark]),
                pair[1].day, pair[1].shift, pair[0].source.row, pair[1].source.row,
            ))
            mass = ", ".join(str(v.mass) for v in self.resolve(press)) or "не определена"
            result: Transition = {
                "tone": "conflict", "title": "Расходятся коды распоряжений",
                "text": f"{print_date(dose.day)}, смена {dose.shift}. Совпали № шихты {dose.recipe.number} и доп. марка {dose.recipe.mark}.",
                "missing": "Нет номера партии смеси и записи о её передаче на прессовку.",
                "left": f"Дозирование · {dose.recipe.order_code}/{dose.recipe.number} · масса {dose.mass}",
                "right": f"Прессовка · {press.recipe.order_code}/{press.recipe.number} · масса по шихте {mass}",
                "field_conflicts": {Book.DOSING: {Field.ORDER_CODE}, Book.PRESSING: {Field.ORDER_CODE}},
                "links": [dose.source, press.source],
            }
        elif self.press and not self.dose:
            press = self.press[0][0]
            result = {"tone": "conflict", "title": "За выбранный период дозирование не найдено",
                      "text": f"Прессовка найдена {print_date(press.day)}. В пределах семи соседних дней совпадений по ключу выбранной шихты нет.",
                      "links": [press.source]}
            if self.nearby_dose:
                dose = min(self.nearby_dose, key=lambda row: (row.recipe != press.recipe, abs(row.day - press.day)))
                when = "позже" if dose.day > press.day else "раньше"
                result.update(
                    title=f"Дозирование {when} прессовки · вне периода",
                    text=("Ключ шихты совпал." if dose.recipe == press.recipe
                          else "Ключи шихты у этих записей различаются."),
                    left=f"Дозирование · {print_date(dose.day)}",
                    right=f"Прессовка · {print_date(press.day)}",
                    field_conflicts={Book.DOSING: {Field.DAY}, Book.PRESSING: {Field.DAY}},
                    missing="Для подтверждения передачи смеси нужен номер партии.",
                    links=[dose.source, press.source],
                )
        elif not self.press:
            result = {"tone": "candidate", "title": "Прессовка по выбранным фильтрам не найдена",
                      "help": "Поиск прессовки идёт по сырцу заказа и полям шихты. Для связи с дозированием нужна запись о передаче партии.",
                      "links": []}
        else:
            result = {"tone": "candidate", "title": "Нет записи о передаче смеси",
                      "help": "По коду определяется версия рецептуры. Чтобы связать порцию смеси с выпуском, нужна запись о передаче партии.", "links": []}
        result["matching_slot"] = self.matching_slot()
        result["to"] = Book.PRESSING
        return result

    def wagon_loading_gap(self) -> Transition:
        press_count: dict[tuple[date, Cell, RecipeKey, Cell], list[Press]] = defaultdict(list)
        for row, _ in self.press:
            press_count[row.day, row.shift, row.recipe, row.press].append(row)
        group = next((rows for rows in press_count.values() if len(rows) > 1), None)
        if group:
            day, shift = group[0].day, group[0].shift
            quantities = " и ".join(str(row.good_units) for row in group[:4])
            result: Transition = {"tone": "ambiguous", "title": "Несколько прессовок с одинаковыми полями",
                                  "text": f"{print_date(day)}, смена {shift}. Годное: {quantities} шт. У вагонеток нет ссылки на одну из этих строк.",
                                  "links": [row.source for row in group[:4]]}
        else:
            result = {"tone": "candidate", "title": "У садки нет ссылки на выпуск прессовки",
                      "help": "Кандидатов ищут по сырцу, ключу шихты и дате. Для подтверждения нужна запись о загрузке конкретного выпуска на вагонетку.",
                      "links": []}
        result["to"] = Book.WAGON_LOADING
        return result

    def build(self) -> TraceResult:
        wagon_loading, wagons = self.later_production(WagonLoad, Book.WAGON_LOADING, [row for row, _ in self.press])
        ovens, furnaces = self.later_production(Furnace, Book.FURNACES, wagons)
        ops, delivered, op_conflicts, delivery_conflicts = self.finishing(furnaces)
        percentages = [row for row in self.history.month_rows(Percentage, self.month)
                       if (row.raw_group, row.product_group) == (self.order.raw_group, self.order.product_group)]
        presses = {row.press for row, _ in self.press}
        stops = [row for row in self.history.dated_rows(Downtime) if row.equipment in presses and row.day <= self.last
                 and (row.end_day or row.day) >= self.first]
        stages = [
            stage(Book.ORDERS, "context", "Исходная строка месячного листа. В книге нет сквозного номера заказа.",
                  with_basis([self.order], "context", "Исходная строка заказа.")),
            self.recipe_stage(), self.powders(), self.dosing(), self.press_norms(), self.pressing(),
            wagon_loading, ovens, ops, delivered,
            stage(Book.PERCENTAGES, "context", "Групповые проценты по кодам групп сырца и изделия.",
                  with_basis(percentages, "context", "Совпали обе группы. Результат заказа в этой таблице отсутствует.")),
            stage(Book.DOWNTIMES, "context", "Оборудование и пересечение дат простоя с выбранным периодом.",
                  with_basis(stops, "context", "Совпал код пресса. Связь простоя с конкретным выпуском отсутствует.")),
        ]
        gaps: list[Transition] = [
            self.pressing_gap(), self.wagon_loading_gap(),
            {"to": Book.DOSING, "tone": "candidate", "title": "Нет номера партии порошка",
             "help": "Подача найдена по коду компонента и близкой дате. Нужна запись о том, из какой партии порошка дозировали компонент.",
             "links": []},
            {"to": Book.FURNACES, "tone": "candidate", "title": "В печах нет номера вагонетки",
             "help": "Кандидатов ищут по сырцу, ключу шихты и дате. Для связи с садкой нужна запись о входе конкретной вагонетки в печь.",
             "links": [row.source for row in furnaces[:2]]},
            finishing_gap(ops, op_conflicts, "Нет ссылки на партию из печи",
                          "Дополнительные операции найдены по коду изделия. Проверены ключ шихты относительно прессовки и дата относительно выходов из печи."),
            finishing_gap(delivered, delivery_conflicts, "Нет связи между дополнительными операциями и партией сдачи",
                          "Сдача найдена по коду изделия. Проверены доп. марка заказа и дата относительно выходов из печи. Нужен журнал передачи партии."),
        ]
        return TraceResult(self.month, self.first, self.last, self.order.mark, self.recipe_filter, self.versions, stages, gaps)

    def coverage(self) -> Coverage:
        trace = self.build()
        stages = [item for item in trace.stages if item.file in ROUTE_FILES]
        covered = {
            item.file for item in stages if not item.outside_period
            and any(row.tone != "conflict" for row in item.rows)
        }
        conflicts = {item.file for item in stages if any(row.tone == "conflict" for row in item.rows)}
        conflicts.update(gap["to"] for gap in trace.gaps if gap["tone"] == "conflict")
        return Coverage(self.order.source.row, len(covered), len(conflicts),
                        sum(gap["tone"] == "ambiguous" for gap in trace.gaps), INITIAL_ROUTE_FILES <= covered,
                        next(gap["matching_slot"] for gap in trace.gaps if gap["to"] == Book.PRESSING))


def finishing_gap(item: Stage, fields: ConflictFields, title: str, explanation: str) -> Transition:
    rows = [row for row in item.rows if row.tone == "conflict"]
    return {"to": item.file, "tone": "conflict" if rows else "candidate", "title": title,
            "help": explanation, "count": len(rows), "links": rows[:2], "field_conflicts": fields}
