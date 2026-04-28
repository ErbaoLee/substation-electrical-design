#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared database access helpers for the substation design skill."""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
CURATED_DB_PATH = ROOT_DIR / "substation_curated.sqlite"

def ensure_curated_database() -> Path:
    """Make sure the curated database exists and contains tables."""
    if not CURATED_DB_PATH.exists():
        raise FileNotFoundError(f"Curated database not found: {CURATED_DB_PATH}")

    with sqlite3.connect(CURATED_DB_PATH) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
    if not count:
        raise RuntimeError(f"Curated database is empty: {CURATED_DB_PATH}")
    return CURATED_DB_PATH


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    for chunk in (text.split("~")[0], text):
        try:
            return float(chunk)
        except ValueError:
            continue
    return None


def parse_current_ratio_primary(ratio: str | None) -> float | None:
    if not ratio:
        return None
    primary = str(ratio).split("/")[0]
    primary = primary.split("x")[-1]
    return parse_float(primary)


def parse_range(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return (None, None)
    raw = str(text).replace("A", "").replace(" ", "")
    if "~" not in raw:
        value = parse_float(raw)
        return (value, value)
    left, right = raw.split("~", 1)
    return (parse_float(left), parse_float(right))


class EquipmentDatabase:
    """Thin repository over the curated SQLite catalog."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or ensure_curated_database()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _coerce_value(row: sqlite3.Row) -> Any:
        if row["value_number"] is not None:
            return float(row["value_number"])
        if row["value_bool"] is not None:
            return bool(row["value_bool"])
        return row["value_text"]

    @lru_cache(maxsize=None)
    def get_models(self, category_code: str) -> tuple[dict[str, Any], ...]:
        query = """
        SELECT
            em.equipment_id,
            em.model,
            pd.field_code,
            epv.value_text,
            epv.value_number,
            epv.value_bool
        FROM equipment_model em
        LEFT JOIN equipment_parameter_value epv ON epv.equipment_id = em.equipment_id
        LEFT JOIN parameter_dictionary pd ON pd.param_id = epv.param_id
        WHERE em.category_code = ?
        ORDER BY em.model, pd.sort_order
        """
        grouped: dict[int, dict[str, Any]] = {}
        with self.connect() as conn:
            for row in conn.execute(query, (category_code,)):
                equipment_id = int(row["equipment_id"])
                model = grouped.setdefault(
                    equipment_id,
                    {
                        "equipment_id": equipment_id,
                        "category_code": category_code,
                        "model": row["model"],
                    },
                )
                if row["field_code"]:
                    model[row["field_code"]] = self._coerce_value(row)
        return tuple(grouped.values())

    def find_models(self, category_code: str, predicate) -> list[dict[str, Any]]:
        return [model for model in self.get_models(category_code) if predicate(model)]

    def first_model(self, category_code: str, predicate, sort_key=None) -> dict[str, Any] | None:
        matches = self.find_models(category_code, predicate)
        if sort_key is not None:
            matches.sort(key=sort_key)
        return matches[0] if matches else None

    def summarize(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT category_code, COUNT(*) AS model_count
                FROM equipment_model
                GROUP BY category_code
                ORDER BY category_code
                """
            ).fetchall()
