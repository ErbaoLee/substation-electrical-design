#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load calculation and database-backed capacity recommendations."""

from __future__ import annotations

import math
from typing import Any

from equipment_db import EquipmentDatabase, parse_float, parse_range


def _normalize_station_load_type(load_type: str) -> str:
    text = str(load_type or "").strip().lower()
    mapping = {
        "frequent_continuous": "frequent_continuous",
        "continuous_infrequent": "continuous_infrequent",
        "frequent_intermittent": "frequent_intermittent",
        "short_intermittent_infrequent": "short_intermittent_infrequent",
        "standby": "short_intermittent_infrequent",
        "maintenance_test": "short_intermittent_infrequent",
        "经常连续": "frequent_continuous",
        "经常、连续": "frequent_continuous",
        "连续不经常": "continuous_infrequent",
        "不经常、连续": "continuous_infrequent",
        "经常而断续": "frequent_intermittent",
        "经常、短时": "frequent_intermittent",
        "短时断续且不经常": "short_intermittent_infrequent",
        "不经常、短时": "short_intermittent_infrequent",
    }
    return mapping.get(text, "short_intermittent_infrequent")


class LoadCalculator:
    """Compute design loads and map results to curated equipment models."""

    def __init__(self, catalog: EquipmentDatabase | None = None):
        self.catalog = catalog or EquipmentDatabase()

    def calc_max_comprehensive_load(
        self,
        loads: list[dict[str, Any]],
        cos_phi: float = 0.85,
        kt: float = 0.9,
        loss_percent: float = 4,
    ) -> float:
        total_power = sum(float(load["power"]) for load in loads)
        return kt * (total_power / cos_phi) * (1 + loss_percent / 100)

    def _available_main_transformers(self) -> list[dict[str, Any]]:
        return sorted(
            self.catalog.get_models("main_transformer"),
            key=lambda item: parse_float(item.get("rated_capacity_mva")) or float("inf"),
        )

    def calc_transformer_capacity(
        self,
        s_max: float,
        n: int = 2,
        k_factor: float = 0.6,
        class_i_ii_load: float = 0,
    ) -> dict[str, Any]:
        sn_by_max = k_factor * s_max / max(n - 1, 1)
        sn_by_class = class_i_ii_load / max(n - 1, 1) if class_i_ii_load else 0.0
        sn_required = max(sn_by_max, sn_by_class)

        selected_model = None
        for model in self._available_main_transformers():
            if (parse_float(model.get("rated_capacity_mva")) or 0.0) >= sn_required:
                selected_model = model
                break
        if selected_model is None:
            selected_model = self._available_main_transformers()[-1]

        sn_standard = parse_float(selected_model.get("rated_capacity_mva")) or 0.0
        total_capacity = n * sn_standard

        return {
            "s_max": round(s_max, 2),
            "sn_by_max": round(sn_by_max, 2),
            "sn_by_class": round(sn_by_class, 2),
            "sn_required": round(sn_required, 2),
            "sn_standard": sn_standard,
            "n": n,
            "total_capacity": total_capacity,
            "check_total": total_capacity >= s_max,
            "check_n1": sn_standard >= k_factor * s_max,
            "selected_model": selected_model["model"],
            "selected_transformer": dict(selected_model),
        }

    def calc_station_load(self, loads: list[dict[str, Any]], k_conversion: float = 0.85) -> dict[str, Any]:
        included_types = {
            "frequent_continuous",
            "continuous_infrequent",
            "frequent_intermittent",
        }
        counted_power_kw = 0.0
        excluded_power_kw = 0.0
        breakdown: list[dict[str, Any]] = []
        for load in loads:
            input_type = str(load.get("type") or "")
            normalized_type = _normalize_station_load_type(input_type)
            power = float(load["power"])
            included = normalized_type in included_types
            counted_power = power if included else 0.0
            counted_power_kw += counted_power
            excluded_power_kw += 0.0 if included else power
            breakdown.append(
                {
                    "name": load.get("name"),
                    "input_type": input_type,
                    "normalized_type": normalized_type,
                    "power": power,
                    "included": included,
                    "counted_power_kw": round(counted_power, 3),
                    "rule": "counted" if included else "excluded_short_time_infrequent",
                }
            )
        return {
            "method": "conversion_coefficient_by_load_nature",
            "reference_rule": "Count frequent/continuous loads, exclude short-time and infrequent loads.",
            "counted_power_kw": round(counted_power_kw, 2),
            "excluded_power_kw": round(excluded_power_kw, 2),
            "total_power": round(counted_power_kw, 2),
            "k_conversion": k_conversion,
            "s_station": round(k_conversion * counted_power_kw, 2),
            "breakdown": breakdown,
        }

    def select_station_transformer(self, s_station: float) -> dict[str, Any]:
        models = sorted(
            self.catalog.get_models("station_service_transformer"),
            key=lambda item: parse_float(item.get("rated_capacity_kva")) or float("inf"),
        )
        selected = None
        for model in models:
            if (parse_float(model.get("rated_capacity_kva")) or 0.0) >= s_station:
                selected = model
                break
        if selected is None and models:
            selected = models[-1]
        if not selected:
            return {}

        return {
            "model": selected["model"],
            "rated_capacity": f"{int(parse_float(selected.get('rated_capacity_kva')) or 0)} kVA",
            "primary_voltage": f"{parse_float(selected.get('rated_voltage_primary_kv')) or 10:g} kV",
            "secondary_voltage": f"{parse_float(selected.get('rated_voltage_secondary_v')) or 400:g} V",
            "selected_transformer": dict(selected),
        }

    def calc_reactive_power_compensation(
        self,
        transformer_capacity: float,
        compensation_ratio: float = 0.15,
        groups: int = 2,
    ) -> dict[str, Any]:
        total_required = transformer_capacity * compensation_ratio * 1000
        per_group_required = total_required / groups

        models = sorted(
            self.catalog.get_models("shunt_capacitor"),
            key=lambda item: parse_float(item.get("capacity_per_group_kvar")) or float("inf"),
        )
        selected = None
        for model in models:
            group_count = int(parse_float(model.get("group_count")) or 0)
            per_group_capacity = parse_float(model.get("capacity_per_group_kvar")) or 0.0
            if group_count == groups and per_group_capacity >= per_group_required:
                selected = model
                break
        if selected is None and models:
            selected = models[-1]
        if not selected:
            return {}

        actual_total = parse_float(selected.get("rated_capacity_kvar")) or 0.0
        return {
            "transformer_capacity": transformer_capacity,
            "compensation_ratio_target": compensation_ratio * 100,
            "total_compensation_required": round(total_required, 2),
            "groups": groups,
            "per_group_capacity": round(per_group_required, 2),
            "selected_model": selected["model"],
            "selected_per_group": parse_float(selected.get("capacity_per_group_kvar")) or 0.0,
            "actual_total_compensation": actual_total,
            "actual_compensation_ratio": round(actual_total / (transformer_capacity * 1000) * 100, 2),
            "selected_capacitor": dict(selected),
        }

    def select_arc_suppression_coil(
        self,
        transformer_capacity: float | None = None,
        capacitive_current: float | None = None,
    ) -> dict[str, Any]:
        models = sorted(
            self.catalog.get_models("arc_suppression_grounding_transformer"),
            key=lambda item: parse_float(item.get("arc_suppression_coil_capacity_kva")) or float("inf"),
        )
        selected = None
        if transformer_capacity is not None:
            selected = min(
                models,
                key=lambda item: abs((parse_float(item.get("grounding_transformer_capacity_kva")) or 0.0) - transformer_capacity),
            )
        elif capacitive_current is not None:
            for model in models:
                current_range = parse_range(model.get("compensation_current_range_a"))
                if (current_range[0] or 0.0) <= capacitive_current <= (current_range[1] or float("inf")):
                    selected = model
                    break
        if selected is None and models:
            selected = models[0]
        if not selected:
            return {}

        return {
            "model": selected["model"],
            "transformer_capacity": f"{int(parse_float(selected.get('grounding_transformer_capacity_kva')) or 0)} kVA",
            "coil_capacity": f"{int(parse_float(selected.get('arc_suppression_coil_capacity_kva')) or 0)} kVA",
            "applicable_current_range": selected.get("compensation_current_range_a"),
            "type": selected.get("device_type"),
            "selected_device": dict(selected),
        }

    def select_grounding_resistor(
        self,
        grounding_current: float = 600,
        duration: float = 10,
        voltage_level_kv: float = 10,
    ) -> dict[str, Any]:
        phase_voltage = voltage_level_kv / math.sqrt(3)
        required_resistance = (phase_voltage * 1000) / grounding_current
        models = sorted(
            self.catalog.get_models("grounding_resistor"),
            key=lambda item: abs((parse_float(item.get("resistance_ohm")) or 0.0) - required_resistance),
        )
        selected = None
        for model in models:
            if (parse_float(model.get("grounding_current_a")) or 0.0) >= grounding_current:
                selected = model
                break
        if selected is None and models:
            selected = models[0]
        if not selected:
            return {}

        return {
            "model": selected["model"],
            "resistance": f"{parse_float(selected.get('resistance_ohm')) or 0:g} ohm",
            "grounding_current": f"{parse_float(selected.get('grounding_current_a')) or 0:g} A",
            "duration": f"{duration:g} s",
            "type": selected.get("material"),
            "voltage_level": f"{parse_float(selected.get('voltage_level_kv')) or voltage_level_kv:g} kV",
            "required_resistance_ohm": round(required_resistance, 3),
            "selected_resistor": dict(selected),
        }


def example_calculation() -> dict[str, Any]:
    calc = LoadCalculator()
    loads = [
        {"name": "chemical", "power": 11.0, "class": "I"},
        {"name": "smelting", "power": 20.0, "class": "I"},
        {"name": "substation_load", "power": 18.0, "class": "II"},
        {"name": "new_load", "power": 13.0, "class": "I/II"},
        {"name": "manufacturing", "power": 5.0, "class": "III"},
    ]
    station_loads = [
        {"name": "main_transformer_fan_1", "power": 3.1, "type": "frequent_continuous"},
        {"name": "main_transformer_fan_2", "power": 3.2, "type": "frequent_continuous"},
        {"name": "charger", "power": 4.3, "type": "frequent_continuous"},
        {"name": "lighting", "power": 8.7, "type": "frequent_continuous"},
        {"name": "life_service", "power": 9.1, "type": "continuous_infrequent"},
        {"name": "maintenance_test", "power": 5.3, "type": "short_intermittent_infrequent"},
    ]
    s_max = calc.calc_max_comprehensive_load(loads)
    transformer = calc.calc_transformer_capacity(s_max, n=2, k_factor=0.6, class_i_ii_load=51.4)
    station = calc.calc_station_load(station_loads)
    return {
        "s_max": round(s_max, 2),
        "transformer": transformer,
        "station_load": station,
        "station_transformer": calc.select_station_transformer(station["s_station"]),
        "reactive_compensation": calc.calc_reactive_power_compensation(transformer["sn_standard"], 0.15, 2),
        "arc_suppression": calc.select_arc_suppression_coil(transformer_capacity=315),
        "grounding_resistor": calc.select_grounding_resistor(grounding_current=600, duration=10),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(example_calculation(), ensure_ascii=False, indent=2))
