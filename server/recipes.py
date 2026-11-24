"""Recipe versions and matching keys in each monthly snapshot of the catalog."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .records import Cell, Component, RecipeKey


@dataclass
class Version:
    mass: Cell
    order_code: Cell
    number: Cell
    start: date
    end: date
    rows: list[Component]

    @property
    def id(self) -> str:
        return f"{self.mass}/{self.order_code}/{self.number}/{self.start}/{self.end}"

    @property
    def label(self) -> str:
        return f"масса {self.mass} · {self.order_code}/{self.number}"

    @property
    def marks(self) -> list[Cell]:
        return sorted({row.recipe.mark for row in self.rows if row.recipe.mark})

    def active(self, first: date, last: date) -> bool:
        """Both the version life span and the planning interval include their endpoints."""
        return self.start <= last and first <= self.end


class RecipeCatalog:
    def __init__(self, components: Iterable[Component]):
        self._versions: dict[str, Version] = {}
        self._by_key: dict[RecipeKey, list[Version]] = defaultdict(list)
        for row in components:
            if not (row.first and row.last and row.mass and row.recipe.order_code and row.recipe.number):
                continue
            version = Version(row.mass, row.recipe.order_code, row.recipe.number, row.first, row.last, [])
            self._versions.setdefault(version.id, version).rows.append(row)
        for version in self._versions.values():
            for mark in version.marks:
                key = RecipeKey(version.order_code, version.number, mark)
                self._by_key[key].append(version)

    def for_order(self, mass: Cell, mark: Cell, first: date, last: date) -> list[Version]:
        return sorted(
            (version for version in self._versions.values() if version.mass == mass),
            key=lambda version: (
                mark not in version.marks, not version.active(first, last), version.number, version.order_code,
            ),
        )

    def resolve(self, key: RecipeKey, day: date) -> list[Version]:
        return [version for version in self._by_key.get(key, ()) if version.active(day, day)]
