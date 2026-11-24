"""Convert application results to the trace viewer's existing JSON contract."""

from __future__ import annotations

from typing import Iterable, Protocol

from .application import CoverageReport
from .records import Book, Cell, Field, Order, SourceDetails, SourceRef, TITLES
from .trace import RowMatch, Stage, TraceResult, Transition


class StageSources(Protocol):
    def book_name(self, file: int) -> str: ...

    def stage_columns(self, file: Book, month: str) -> tuple[tuple[int, ...], list[str]]: ...

    def display_values(self, ref: SourceRef, columns: Iterable[int]) -> list[Cell]: ...

    def column_for_field(self, file: Book, field: Field) -> int: ...


def order_payload(order: Order) -> dict:
    return {
        "row": order.source.row, "mass": order.mass, "raw": order.raw, "product": order.product,
        "name": order.name, "mark": order.mark, "base": order.base_tonnes, "extra": order.extra_tonnes,
    }


def coverage_payload(report: CoverageReport) -> dict:
    return {
        "stage_count": report.stage_count,
        "orders": [
            {"row": score.row, "covered": score.covered, "conflicts": score.conflicts,
             "ambiguous": score.ambiguous, "initial_stages": score.initial_stages, "same_shift": score.same_shift}
            for score in report.orders
        ],
    }


def source_payload(source: SourceDetails) -> dict:
    return {
        "file": source.book, "sheet": source.sheet, "row": source.row,
        "columns": [{"name": name, "value": value} for name, value in source.fields],
    }


def stage_payload(stage: Stage, month: str, sources: StageSources) -> dict:
    column_ids, headings = sources.stage_columns(stage.file, month)
    rows = [
        {"month": row.source.month, "sheet": row.source.sheet, "row": row.source.row,
         "tone": row.tone, "basis": row.basis, "values": sources.display_values(row.source, column_ids)}
        for row in stage.rows
    ]
    result = {
        "file": stage.file, "title": TITLES[stage.file - 1], "source": sources.book_name(stage.file),
        "tone": stage.tone, "summary": stage.summary, "rows": rows, "column_ids": column_ids, "columns": headings,
    }
    if stage.outside_period is not None:
        result["outside_period"] = stage.outside_period
    return result


def link_payload(link: SourceRef | RowMatch) -> dict:
    ref = link.source if isinstance(link, RowMatch) else link
    result = {"file": ref.file, "month": ref.month, "row": ref.row, "label": f"{TITLES[ref.file - 1]}, строка {ref.row}"}
    if isinstance(link, RowMatch):
        result["basis"] = link.basis
    return result


def transition_payload(gap: Transition, sources: StageSources) -> dict:
    result = dict(gap)
    result["links"] = [link_payload(link) for link in gap["links"]]
    if "field_conflicts" in gap:
        result["field_conflicts"] = {
            file: sorted(sources.column_for_field(file, field) for field in fields)
            for file, fields in gap["field_conflicts"].items()
        }
    return result


def trace_payload(trace: TraceResult, sources: StageSources) -> dict:
    versions = [
        {"id": version.id, "label": version.label, "mass": version.mass,
         "order_code": version.order_code, "number": version.number, "marks": version.marks,
         "first": version.start.isoformat(), "last": version.end.isoformat(), "rows": len(version.rows),
         "order_mark": trace.mark in version.marks, "active": version.active(trace.first, trace.last)}
        for version in trace.versions
    ]
    return {
        "recipe": trace.recipe, "versions": versions,
        "active_count": sum(version["active"] for version in versions),
        "stages": [stage_payload(stage, trace.month, sources) for stage in trace.stages],
        "gaps": [transition_payload(gap, sources) for gap in trace.gaps],
    }
