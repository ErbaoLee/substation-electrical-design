#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main wiring generation driven by wiring-specific duties and validation inputs."""

from __future__ import annotations

import json
import math
from typing import Any

from calc_load import LoadCalculator
from calc_short_circuit import (
    DEFAULT_SHOCK_COEFFICIENT,
    FaultSource,
    NetworkBranch,
    PerUnitImpedance,
    ShortCircuitCalculator,
    default_clearing_time,
)
from equipment_db import EquipmentDatabase, parse_float
from select_equipment import EquipmentSelector


def _normalize_reliability(reliability: str) -> str:
    text = str(reliability or "general").strip().lower()
    aliases = {
        "general": "general",
        "normal": "general",
        "important": "important",
        "critical": "critical",
        "very_important": "critical",
    }
    return aliases.get(text, "general")


def select_wiring_type(
    voltage_level: float,
    circuits: int,
    reliability: str = "general",
    transformer_count: int = 2,
    through_power: bool = False,
    line_length: str = "medium",
) -> dict[str, Any]:
    reliability = _normalize_reliability(reliability)
    line_length = str(line_length or "medium").strip().lower()

    if voltage_level <= 10.0:
        if circuits <= 6 and reliability == "general":
            wiring_type = "single_bus"
        elif circuits <= 10:
            wiring_type = "single_bus_sectionalized"
        else:
            wiring_type = "double_bus"
    elif voltage_level <= 35.0:
        if circuits == 2 and transformer_count >= 2 and line_length == "long":
            wiring_type = "inner_bridge"
        elif circuits <= 4 and reliability == "general":
            wiring_type = "single_bus"
        else:
            wiring_type = "single_bus_sectionalized"
    elif voltage_level <= 110.0:
        if circuits == 2 and transformer_count >= 2:
            wiring_type = "outer_bridge" if through_power or line_length != "long" else "inner_bridge"
        elif circuits >= 4 and reliability in {"important", "critical"}:
            wiring_type = "double_bus"
        else:
            wiring_type = "single_bus_sectionalized"
    else:
        if circuits > 6 or reliability == "critical":
            wiring_type = "double_bus_bypass"
        else:
            wiring_type = "double_bus"

    descriptions = {
        "single_bus": "Simple and economic, suitable for fewer bays and ordinary reliability requirements.",
        "single_bus_sectionalized": "Uses bus sections and a coupler to improve transfer capability and N-1 operation.",
        "inner_bridge": "Recommended when two circuits and two transformers are used with longer lines and lower through power.",
        "outer_bridge": "Recommended when two circuits and two transformers are used with shorter lines or through power.",
        "double_bus": "Provides better dispatch flexibility, easier maintenance and stronger continuity for important stations.",
        "double_bus_bypass": "Adds bypass transfer duty for high-voltage stations with frequent breaker maintenance or very high continuity requirements.",
    }

    return {
        "wiring_type": wiring_type,
        "description": descriptions[wiring_type],
        "voltage_level": voltage_level,
        "circuits": circuits,
        "reliability": reliability,
        "through_power": through_power,
        "line_length": line_length,
        "transformer_count": transformer_count,
    }


def _match_main_transformer(
    catalog: EquipmentDatabase,
    capacity_mva: float,
    hv_voltage_kv: float = 110.0,
) -> dict[str, Any] | None:
    models = sorted(
        catalog.get_models("main_transformer"),
        key=lambda item: parse_float(item.get("rated_capacity_mva")) or float("inf"),
    )
    for model in models:
        if (
            (parse_float(model.get("rated_capacity_mva")) or 0.0) >= capacity_mva
            and str(model.get("rated_voltage_hv_kv") or "").startswith(str(int(hv_voltage_kv)))
        ):
            return dict(model)
    return dict(models[-1]) if models else None


def _current_from_mva(capacity_mva: float, voltage_kv: float, factor: float = 1.05) -> float:
    if capacity_mva <= 0 or voltage_kv <= 0:
        return 0.0
    return factor * capacity_mva * 1000.0 / (math.sqrt(3.0) * voltage_kv)


def _section_labels(wiring_type: str) -> list[str]:
    if wiring_type in {"single_bus_sectionalized", "double_bus", "double_bus_bypass", "inner_bridge", "outer_bridge"}:
        return ["A", "B"]
    return ["common"]


def _distribute_count(total: int, labels: list[str]) -> dict[str, int]:
    if not labels:
        return {}
    total = max(int(total or 0), 0)
    base = total // len(labels)
    remainder = total % len(labels)
    return {
        label: base + (1 if index < remainder else 0)
        for index, label in enumerate(labels)
    }


def _normalize_fault_basis(fault: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "method": str(fault.get("method") or "equivalent_impedance"),
        "equivalent_impedance": fault.get("equivalent_impedance"),
        "symmetrical_current_ka": round(float(fault.get("symmetrical_current_ka") or 0.0), 3),
        "breaking_current_ka": round(float(fault.get("breaking_current_ka") or 0.0), 3),
        "peak_current_ka": round(float(fault.get("peak_current_ka") or 0.0), 3),
        "full_current_ka": round(float(fault.get("full_current_ka") or 0.0), 3),
        "short_circuit_capacity_mva": round(float(fault.get("short_circuit_capacity_mva") or 0.0), 3),
        "thermal_effect_a2s": round(float(fault.get("thermal_effect_a2s") or 0.0), 3),
        "clearing_time_s": round(float(fault.get("clearing_time_s") or 0.0), 3),
        "kappa": round(float(fault.get("kappa") or 0.0), 3),
        "shock_coefficient": round(float(fault.get("shock_coefficient") or 0.0), 3),
        "x_sigma_pu": round(float(fault.get("x_sigma_pu") or 0.0), 6),
        "x_js": round(float(fault.get("x_js") or 0.0), 6),
        "i_star": round(float(fault.get("i_star") or 0.0), 6),
        "sn_total_mva": round(float(fault.get("sn_total_mva") or 0.0), 3),
        "curve_type": str(fault.get("curve_type") or ""),
    }
    if fault.get("fault_node") is not None:
        normalized["fault_node"] = str(fault.get("fault_node") or "")
    if fault.get("source_contributions"):
        normalized["source_contributions"] = list(fault.get("source_contributions") or [])
    if fault.get("time_series"):
        normalized["time_series"] = list(fault.get("time_series") or [])
    if fault.get("requested_curve_times_s"):
        normalized["requested_curve_times_s"] = list(fault.get("requested_curve_times_s") or [])
    if fault.get("network_branches"):
        normalized["network_branches"] = list(fault.get("network_branches") or [])
    return normalized


def _fault_basis_from_input(
    voltage_level: float,
    short_circuit_current: float | dict[str, Any],
) -> dict[str, Any]:
    calculator = ShortCircuitCalculator()
    if isinstance(short_circuit_current, dict):
        clearing_time_s = float(short_circuit_current.get("clearing_time_s") or default_clearing_time(voltage_level))
        method = str(short_circuit_current.get("method") or "").strip().lower()
        if short_circuit_current.get("sources"):
            fallback_impedance = _parse_impedance_spec(
                short_circuit_current.get("equivalent_impedance") or short_circuit_current.get("x_sigma_pu"),
                default_x_pu=0.0,
            )
            return {
                "method": "explicit_topology_operation_curve",
                "equivalent_impedance": fallback_impedance.to_dict(),
                "symmetrical_current_ka": 0.0,
                "breaking_current_ka": 0.0,
                "peak_current_ka": 0.0,
                "full_current_ka": 0.0,
                "short_circuit_capacity_mva": 0.0,
                "thermal_effect_a2s": 0.0,
                "clearing_time_s": round(clearing_time_s, 3),
                "kappa": round(float(parse_float(short_circuit_current.get("shock_coefficient")) or DEFAULT_SHOCK_COEFFICIENT), 3),
                "shock_coefficient": round(float(parse_float(short_circuit_current.get("shock_coefficient")) or DEFAULT_SHOCK_COEFFICIENT), 3),
                "x_sigma_pu": round(float(parse_float(short_circuit_current.get("x_sigma_pu")) or 0.0), 6),
                "x_js": round(float(parse_float(short_circuit_current.get("x_js")) or 0.0), 6),
                "i_star": round(float(parse_float(short_circuit_current.get("i_star")) or 0.0), 6),
                "sn_total_mva": round(float(parse_float(short_circuit_current.get("sn_total_mva")) or 0.0), 3),
                "curve_type": str(short_circuit_current.get("curve_type") or ""),
            }
        curve_type = str(short_circuit_current.get("curve_type") or "turbine_finite")
        sn_total_mva = parse_float(short_circuit_current.get("sn_total_mva"))
        x_sigma_pu = parse_float(short_circuit_current.get("x_sigma_pu"))
        x_js = parse_float(short_circuit_current.get("x_js"))
        i_star = parse_float(short_circuit_current.get("i_star"))
        shock_coefficient = parse_float(short_circuit_current.get("shock_coefficient")) or DEFAULT_SHOCK_COEFFICIENT

        if method == "operation_curve" or x_sigma_pu is not None or (x_js is not None and sn_total_mva):
            if sn_total_mva is None or sn_total_mva <= 0:
                raise ValueError("Operation-curve short-circuit input must provide sn_total_mva > 0.")
            if x_sigma_pu is None:
                x_sigma_pu = float(x_js) * calculator.Sb / float(sn_total_mva)
            return _normalize_fault_basis(
                calculator.fault_from_xjs(
                    x_sigma_pu=float(x_sigma_pu),
                    sn_total_mva=float(sn_total_mva),
                    voltage_kv=voltage_level,
                    curve_type=curve_type,
                    i_star=float(i_star) if i_star is not None else None,
                    clearing_time_s=clearing_time_s,
                    shock_coefficient=float(shock_coefficient),
                )
            )

        equivalent_impedance = short_circuit_current.get("equivalent_impedance")
        if isinstance(equivalent_impedance, dict):
            r_pu = parse_float(equivalent_impedance.get("r_pu")) or 0.0
            x_pu = parse_float(equivalent_impedance.get("x_pu")) or 0.0
            if abs(r_pu) > 0 or abs(x_pu) > 0:
                return _normalize_fault_basis(
                    calculator.fault_from_impedance(
                        PerUnitImpedance(r_pu=r_pu, x_pu=x_pu),
                        voltage_kv=voltage_level,
                        clearing_time_s=clearing_time_s,
                        use_operation_curve=method == "operation_curve" and bool(sn_total_mva),
                        sn_total_mva=float(sn_total_mva) if sn_total_mva else None,
                        curve_type=curve_type,
                        i_star=float(i_star) if i_star is not None else None,
                        shock_coefficient=float(shock_coefficient),
                    )
                )

        symmetrical_current = parse_float(short_circuit_current.get("symmetrical_current_ka"))
        if symmetrical_current is None:
            symmetrical_current = parse_float(short_circuit_current.get("breaking_current_ka"))
        if symmetrical_current is None:
            symmetrical_current = parse_float(short_circuit_current.get("short_circuit_current_ka"))
        if symmetrical_current is None or symmetrical_current <= 0:
            raise ValueError("Short-circuit input must provide a positive current level or equivalent impedance.")

        x_over_r = parse_float(short_circuit_current.get("x_over_r"))
        if x_over_r is None and isinstance(equivalent_impedance, dict):
            x_over_r = parse_float(equivalent_impedance.get("x_over_r"))
        return _normalize_fault_basis(
            calculator.fault_from_current_level(
                voltage_kv=voltage_level,
                short_circuit_current_ka=float(symmetrical_current),
                x_over_r=float(x_over_r or 10.0),
                clearing_time_s=clearing_time_s,
            )
        )

    return _normalize_fault_basis(
        calculator.fault_from_current_level(
            voltage_kv=voltage_level,
            short_circuit_current_ka=float(short_circuit_current),
            clearing_time_s=default_clearing_time(voltage_level),
        )
    )


def _parse_impedance_spec(data: Any, default_x_pu: float = 0.0) -> PerUnitImpedance:
    if isinstance(data, dict):
        return PerUnitImpedance(
            r_pu=float(parse_float(data.get("r_pu")) or 0.0),
            x_pu=float(parse_float(data.get("x_pu")) or default_x_pu),
        )
    value = parse_float(data)
    return PerUnitImpedance(r_pu=0.0, x_pu=float(value if value is not None else default_x_pu))


def _normalize_source_section(section: Any, sections: list[str]) -> str:
    text = str(section or "").strip().upper()
    if not sections:
        return "common"
    aliases = {
        "1": sections[0],
        "2": sections[-1],
        "I": sections[0],
        "II": sections[-1],
        "W1": sections[0],
        "W2": sections[-1],
        "A": sections[0],
        "B": sections[-1],
        "COMMON": "common",
    }
    if text in sections:
        return text
    return aliases.get(text, "common")


def _build_source_definitions(
    short_circuit_current: float | dict[str, Any],
    sections: list[str],
    fallback_impedance: PerUnitImpedance,
    fallback_fault: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(short_circuit_current, dict):
        return [
            {
                "name": "equivalent_source",
                "section": sections[0] if sections else "common",
                "impedance": fallback_impedance,
                "source_type": "infinite",
                "source_capacity_mva": None,
                "curve_type": "infinite",
                "i_star_0s": None,
                "i_star_by_time": None,
            }
        ]

    sources = short_circuit_current.get("sources") or []
    if not sources:
        curve_type = str(fallback_fault.get("curve_type") or short_circuit_current.get("curve_type") or "infinite")
        source_type = "finite" if parse_float(fallback_fault.get("sn_total_mva")) else "infinite"
        return [
            {
                "name": "equivalent_source",
                "section": sections[0] if sections else "common",
                "impedance": fallback_impedance,
                "source_type": source_type,
                "source_capacity_mva": parse_float(fallback_fault.get("sn_total_mva")),
                "curve_type": curve_type,
                "i_star_0s": parse_float(short_circuit_current.get("i_star")),
                "i_star_by_time": short_circuit_current.get("i_star_by_time"),
            }
        ]

    definitions: list[dict[str, Any]] = []
    for index, raw_source in enumerate(sources):
        section = _normalize_source_section(
            raw_source.get("section") or raw_source.get("bus") or raw_source.get("connection_section"),
            sections,
        )
        if section == "common" and sections:
            target_sections = list(sections)
        elif section == "common":
            target_sections = ["common"]
        else:
            target_sections = [section]

        for target_section in target_sections:
            suffix = "" if len(target_sections) == 1 else f"_{target_section.lower()}"
            definitions.append(
                {
                    "name": f"{raw_source.get('name') or f'source_{index + 1}'}{suffix}",
                    "section": target_section,
                    "impedance": _parse_impedance_spec(
                        raw_source.get("impedance") or raw_source.get("equivalent_impedance") or raw_source.get("x_pu"),
                        default_x_pu=float(fallback_impedance.x_pu or 0.0),
                    ),
                    "source_type": str(raw_source.get("source_type") or raw_source.get("kind") or raw_source.get("curve_type") or "finite"),
                    "source_capacity_mva": parse_float(raw_source.get("source_capacity_mva") or raw_source.get("sn_mva")),
                    "curve_type": str(raw_source.get("curve_type") or raw_source.get("source_type") or "user_provided"),
                    "i_star_0s": parse_float(raw_source.get("i_star_0s") or raw_source.get("i_star")),
                    "i_star_by_time": raw_source.get("i_star_by_time") or raw_source.get("curve_samples"),
                }
            )
    return definitions


def _build_explicit_network_case(
    wiring_type: str,
    operating_mode: str,
    fault_section: str,
    source_definitions: list[dict[str, Any]],
    short_circuit_current: float | dict[str, Any],
) -> dict[str, Any]:
    sections = _section_labels(wiring_type)
    section_nodes = {
        section: "BUS" if section == "common" else f"BUS_{section}"
        for section in sections
    }
    passive_branches: list[NetworkBranch] = []
    if isinstance(short_circuit_current, dict):
        coupler_impedance = _parse_impedance_spec(short_circuit_current.get("coupler_impedance"), default_x_pu=1e-6)
        bridge_impedance = _parse_impedance_spec(short_circuit_current.get("bridge_impedance"), default_x_pu=1e-6)
        bypass_impedance = _parse_impedance_spec(short_circuit_current.get("bypass_impedance"), default_x_pu=1e-6)
    else:
        coupler_impedance = PerUnitImpedance(x_pu=1e-6)
        bridge_impedance = PerUnitImpedance(x_pu=1e-6)
        bypass_impedance = PerUnitImpedance(x_pu=1e-6)

    if wiring_type in {"single_bus_sectionalized", "double_bus"} and len(sections) == 2 and operating_mode != "split":
        passive_branches.append(
            NetworkBranch("bus_coupler", section_nodes[sections[0]], section_nodes[sections[1]], coupler_impedance)
        )
    elif wiring_type == "double_bus_bypass" and len(sections) == 2:
        if operating_mode != "split":
            passive_branches.append(
                NetworkBranch("bus_coupler", section_nodes[sections[0]], section_nodes[sections[1]], coupler_impedance)
            )
        if operating_mode == "bus_transfer_isolated":
            passive_branches.append(NetworkBranch("bypass_A", section_nodes[sections[0]], "BUS_BYPASS", bypass_impedance))
            passive_branches.append(NetworkBranch("bypass_B", section_nodes[sections[1]], "BUS_BYPASS", bypass_impedance))
    elif wiring_type in {"inner_bridge", "outer_bridge"} and len(sections) == 2 and operating_mode != "bridge_open":
        passive_branches.append(
            NetworkBranch("bridge_breaker", section_nodes[sections[0]], section_nodes[sections[1]], bridge_impedance)
        )

    sources = [
        FaultSource(
            name=definition["name"],
            connection_node=section_nodes.get(str(definition["section"]), section_nodes[sections[0]]),
            impedance=definition["impedance"],
            source_type=str(definition["source_type"]),
            source_capacity_mva=definition["source_capacity_mva"],
            curve_type=str(definition["curve_type"]),
            i_star_0s=definition["i_star_0s"],
            i_star_by_time=definition["i_star_by_time"],
        )
        for definition in source_definitions
    ]
    fault_node = section_nodes.get(fault_section, "BUS")
    if wiring_type == "double_bus_bypass" and operating_mode == "bus_transfer_isolated":
        fault_node = section_nodes.get(fault_section, "BUS")

    return {
        "fault_node": fault_node,
        "passive_branches": passive_branches,
        "sources": sources,
    }


def _comparison_modes(wiring_type: str, operating_mode: str) -> list[str]:
    modes: list[str] = []

    def add_mode(mode: str) -> None:
        if mode and mode not in modes:
            modes.append(mode)

    add_mode("normal")
    if wiring_type in {"single_bus_sectionalized", "double_bus", "double_bus_bypass"}:
        add_mode("split")
    if wiring_type == "double_bus_bypass":
        add_mode("bus_transfer_isolated")
    if wiring_type in {"inner_bridge", "outer_bridge"}:
        add_mode("bridge_open")
    add_mode(str(operating_mode or "normal").lower())
    return modes


def _max_fault_entry(entries: list[dict[str, Any]]) -> dict[str, Any]:
    valid_entries = [entry for entry in entries if entry]
    if not valid_entries:
        return {}
    worst = max(
        valid_entries,
        key=lambda entry: (
            float(entry["fault_basis"].get("symmetrical_current_ka") or 0.0),
            float(entry["fault_basis"].get("peak_current_ka") or 0.0),
            float(entry["fault_basis"].get("thermal_effect_a2s") or 0.0),
        ),
    )
    return {
        "operating_mode": worst["operating_mode"],
        "fault_section": worst["fault_section"],
        "fault_basis": dict(worst["fault_basis"]),
        "active_branches": list(worst["active_branches"]),
    }


def _build_fault_analysis(
    voltage_level: float,
    short_circuit_current: float | dict[str, Any],
    wiring: dict[str, Any],
    transformers: dict[str, Any],
) -> dict[str, Any]:
    wiring_type = str(wiring["wiring_type"])
    operating_mode = str(wiring.get("operating_mode") or "normal").lower()
    sections = _section_labels(wiring_type)
    circuits = int(wiring.get("circuits") or 0)
    transformer_count = int(wiring.get("transformer_count") or transformers.get("count") or 1)

    base_fault = _fault_basis_from_input(
        voltage_level=voltage_level,
        short_circuit_current=short_circuit_current,
    )
    shock_coefficient = parse_float(base_fault.get("shock_coefficient")) or DEFAULT_SHOCK_COEFFICIENT
    if isinstance(short_circuit_current, dict):
        curve_prompt = bool(short_circuit_current.get("prompt_for_curve"))
        curve_times = short_circuit_current.get("curve_times_s") or [0.0]
        clearing_time_s = float(short_circuit_current.get("clearing_time_s") or default_clearing_time(voltage_level))
    else:
        curve_prompt = False
        curve_times = [0.0]
        clearing_time_s = default_clearing_time(voltage_level)

    x_sigma_pu = parse_float(base_fault.get("x_sigma_pu"))
    if x_sigma_pu is not None and x_sigma_pu > 0:
        fallback_impedance = PerUnitImpedance(r_pu=0.0, x_pu=float(x_sigma_pu))
    else:
        impedance_data = base_fault.get("equivalent_impedance") or {}
        fallback_impedance = PerUnitImpedance(
            r_pu=float(parse_float(impedance_data.get("r_pu")) or 0.0),
            x_pu=float(parse_float(impedance_data.get("x_pu")) or 0.0),
        )

    if sections == ["common"]:
        section_weights = {"common": 1.0}
    else:
        line_distribution = _distribute_count(circuits, sections)
        transformer_distribution = _distribute_count(transformer_count, sections)
        raw_weights = {
            section: float(line_distribution.get(section, 0) + transformer_distribution.get(section, 0))
            for section in sections
        }
        if not any(raw_weights.values()):
            raw_weights = {section: 1.0 for section in sections}
        total_weight = sum(raw_weights.values()) or 1.0
        section_weights = {
            section: raw_weights[section] / total_weight
            for section in sections
        }

    calculator = ShortCircuitCalculator()
    source_definitions = _build_source_definitions(
        short_circuit_current=short_circuit_current,
        sections=sections,
        fallback_impedance=fallback_impedance,
        fallback_fault=base_fault,
    )
    scenarios: dict[str, dict[str, Any]] = {}
    for mode in _comparison_modes(wiring_type, operating_mode):
        section_results: dict[str, Any] = {}
        for section in sections:
            network_case = _build_explicit_network_case(
                wiring_type=wiring_type,
                operating_mode=mode,
                fault_section=section,
                source_definitions=source_definitions,
                short_circuit_current=short_circuit_current,
            )
            fault_result = calculator.calc_network_fault(
                voltage_kv=voltage_level,
                fault_node=network_case["fault_node"],
                passive_branches=network_case["passive_branches"],
                sources=network_case["sources"],
                clearing_time_s=clearing_time_s,
                shock_coefficient=float(shock_coefficient),
                prompt_for_curve=curve_prompt,
                requested_curve_times_s=curve_times,
            )
            section_results[section] = {
                "operating_mode": mode,
                "fault_section": section,
                "fault_basis": _normalize_fault_basis(fault_result),
                "active_branches": fault_result.get("network_branches") or [],
                "fault_node": network_case["fault_node"],
            }
        scenarios[mode] = section_results

    governing_by_section = {
        section: _max_fault_entry([scenario[section] for scenario in scenarios.values()])
        for section in sections
    }
    selected_mode = operating_mode if operating_mode in scenarios else "normal"
    selected_fault_basis = _max_fault_entry(list(scenarios[selected_mode].values()))
    design_fault_basis = _max_fault_entry(list(governing_by_section.values()))

    return {
        "calculation_method": "explicit_topology_operation_curve",
        "base_fault": base_fault,
        "selected_mode": selected_mode,
        "comparison_modes": list(scenarios.keys()),
        "section_weights": {section: round(weight, 4) for section, weight in section_weights.items()},
        "source_branches": [
            {
                **item,
                "impedance": item["impedance"].to_dict(),
            }
            for item in source_definitions
        ],
        "scenarios": scenarios,
        "governing_by_section": governing_by_section,
        "selected_fault_basis": selected_fault_basis["fault_basis"],
        "design_fault_basis": design_fault_basis["fault_basis"],
        "governing_mode_by_section": {
            section: entry["operating_mode"]
            for section, entry in governing_by_section.items()
        },
    }


def build_equipment_duties(
    wiring: dict[str, Any],
    transformers: dict[str, Any],
    fault_analysis: dict[str, Any],
    neutral_grounding_mode: str = "solid",
) -> list[dict[str, Any]]:
    wiring_type = str(wiring["wiring_type"])
    voltage_level = float(wiring["voltage_level"])
    circuits = int(wiring["circuits"])
    transformer_capacity = float(transformers.get("capacity", 0.0))
    transformer_count = int(transformers.get("count", 1) or 1)
    through_power = bool(wiring.get("through_power"))
    operating_mode = str(wiring.get("operating_mode") or "normal")
    sections = _section_labels(wiring_type)
    section_line_counts = _distribute_count(circuits, sections)
    section_transformer_counts = _distribute_count(transformer_count, sections)
    section_weights = {
        section: float(fault_analysis.get("section_weights", {}).get(section) or 0.0)
        for section in sections
    }

    total_capacity_mva = transformer_capacity * transformer_count
    line_current = _current_from_mva(total_capacity_mva / max(circuits, 1), voltage_level)
    transformer_current = _current_from_mva(transformer_capacity, voltage_level)
    bus_current = _current_from_mva(total_capacity_mva, voltage_level)
    section_currents = {
        section: _current_from_mva(total_capacity_mva * section_weights.get(section, 0.0), voltage_level)
        for section in sections
    }
    transfer_current = max(section_currents.values(), default=0.0)

    def fault_entry_for_section(section: str) -> dict[str, Any]:
        if section in fault_analysis.get("governing_by_section", {}):
            return dict(fault_analysis["governing_by_section"][section])
        return {
            "operating_mode": fault_analysis.get("selected_mode", operating_mode),
            "fault_section": section,
            "fault_basis": dict(fault_analysis.get("design_fault_basis") or {}),
            "active_branches": [],
        }

    def worst_fault_entry() -> dict[str, Any]:
        candidates = list(fault_analysis.get("governing_by_section", {}).values())
        if candidates:
            return _max_fault_entry(candidates)
        return {
            "operating_mode": fault_analysis.get("selected_mode", operating_mode),
            "fault_section": "common",
            "fault_basis": dict(fault_analysis.get("design_fault_basis") or {}),
            "active_branches": [],
        }

    def make_duty(
        role: str,
        quantity: int,
        imax_a: float,
        formula: str,
        section: str = "common",
        requires_pt: bool = True,
        requires_arrester: bool = True,
        installation_position: str = "busbar",
        conductor_type: str | None = None,
        require_grounding_switch: bool = False,
        ct_secondary_load_va: float = 15.0,
        pt_measure_burden_va: float = 60.0,
        pt_protection_burden_va: float = 80.0,
        require_residual_voltage: bool | None = None,
        fault_entry_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fault_entry = fault_entry_override or fault_entry_for_section(section)
        duty_fault_basis = fault_entry["fault_basis"]
        return {
            "role": role,
            "quantity": quantity,
            "section": section,
            "imax_a": round(imax_a, 2),
            "formula": formula,
            "voltage_level_kv": voltage_level,
            "fault_section": fault_entry["fault_section"],
            "fault_mode_used": fault_entry["operating_mode"],
            "active_branches": [branch["name"] for branch in fault_entry["active_branches"]],
            "symmetrical_fault_current_ka": duty_fault_basis.get("symmetrical_current_ka", 0.0),
            "breaking_current_ka": duty_fault_basis.get("breaking_current_ka", 0.0),
            "peak_current_ka": duty_fault_basis.get("peak_current_ka", 0.0),
            "full_current_ka": duty_fault_basis.get("full_current_ka", 0.0),
            "short_circuit_capacity_mva": duty_fault_basis.get("short_circuit_capacity_mva", 0.0),
            "thermal_effect_a2s": duty_fault_basis.get("thermal_effect_a2s", 0.0),
            "clearing_time_s": duty_fault_basis.get("clearing_time_s", 0.0),
            "installation_position": installation_position,
            "conductor_type": conductor_type or ("soft" if voltage_level >= 110.0 else "hard"),
            "require_grounding_switch": require_grounding_switch,
            "neutral_grounding_mode": neutral_grounding_mode,
            "ct_secondary_load_va": ct_secondary_load_va,
            "pt_measure_burden_va": pt_measure_burden_va,
            "pt_protection_burden_va": pt_protection_burden_va,
            "require_residual_voltage": require_residual_voltage,
            "requires_pt": requires_pt,
            "requires_arrester": requires_arrester,
            "operating_mode": operating_mode,
        }

    duties: list[dict[str, Any]] = []

    if wiring_type == "single_bus":
        duties.extend(
            [
                make_duty("main_bus", 1, bus_current, "I_bus = 1.05·ΣSn/(√3·Un)"),
                make_duty("line_bay", circuits, line_current, "I_line = 1.05·ΣSn/(√3·Un·Nline)", installation_position="outgoing_line", require_grounding_switch=True),
                make_duty("transformer_bay", transformer_count, transformer_current, "I_tr = 1.05·Sn/(√3·Un)", require_grounding_switch=True),
            ]
        )
    elif wiring_type == "single_bus_sectionalized":
        for section in sections:
            section_connections = section_line_counts.get(section, 0) + section_transformer_counts.get(section, 0)
            if section_connections > 0:
                duties.append(make_duty("bus_section", 1, section_currents.get(section, 0.0), "I_section = 1.05·ΣSn(section)/(√3·Un)", section=section))
            if section_line_counts.get(section, 0) > 0:
                duties.append(make_duty("line_bay", section_line_counts[section], line_current, "I_line = 1.05·ΣSn/(√3·Un·Nline)", section=section, installation_position="outgoing_line", require_grounding_switch=True))
            if section_transformer_counts.get(section, 0) > 0:
                duties.append(make_duty("transformer_bay", section_transformer_counts[section], transformer_current, "I_tr = 1.05·Sn/(√3·Un)", section=section, require_grounding_switch=True))
        duties.append(
            make_duty(
                "bus_coupler",
                1,
                transfer_current,
                "I_coupler = max(I_section-A, I_section-B) under transfer duty",
                section="common",
                requires_pt=False,
                requires_arrester=False,
                installation_position="busbar",
                conductor_type="hard" if voltage_level < 110.0 else "soft",
                fault_entry_override=worst_fault_entry(),
            )
        )
    elif wiring_type == "inner_bridge":
        bridge_current = max(line_current, transformer_current)
        for section in sections:
            if section_line_counts.get(section, 0) > 0:
                duties.append(make_duty("line_bay", section_line_counts[section], line_current, "I_line = 1.05·ΣSn/(√3·Un·Nline)", section=section, installation_position="incoming_line", require_grounding_switch=True))
            if section_transformer_counts.get(section, 0) > 0:
                duties.append(make_duty("transformer_bay", section_transformer_counts[section], transformer_current, "I_tr = 1.05·Sn/(√3·Un)", section=section, require_grounding_switch=True))
        duties.append(
            make_duty(
                "bridge_breaker",
                1,
                bridge_current,
                "I_bridge = max(I_line, I_tr) for transformer-side bridge transfer",
                section="common",
                requires_pt=False,
                requires_arrester=False,
                installation_position="bridge",
                fault_entry_override=worst_fault_entry(),
            )
        )
    elif wiring_type == "outer_bridge":
        bridge_current = max(transformer_current, line_current if through_power else line_current * 0.85)
        for section in sections:
            if section_line_counts.get(section, 0) > 0:
                duties.append(make_duty("line_bay", section_line_counts[section], line_current, "I_line = 1.05·ΣSn/(√3·Un·Nline)", section=section, installation_position="incoming_line", require_grounding_switch=True))
            if section_transformer_counts.get(section, 0) > 0:
                duties.append(make_duty("transformer_bay", section_transformer_counts[section], transformer_current, "I_tr = 1.05·Sn/(√3·Un)", section=section, require_grounding_switch=True))
        duties.append(
            make_duty(
                "bridge_breaker",
                1,
                bridge_current,
                "I_bridge = max(I_tr, through-power duty) for line-side bridge transfer",
                section="common",
                requires_pt=False,
                requires_arrester=False,
                installation_position="bridge",
                fault_entry_override=worst_fault_entry(),
            )
        )
    elif wiring_type == "double_bus":
        for section in sections:
            section_connections = section_line_counts.get(section, 0) + section_transformer_counts.get(section, 0)
            if section_connections > 0:
                duties.append(make_duty("bus_section", 1, section_currents.get(section, 0.0), "I_section = 1.05·ΣSn(bus)/√3·Un", section=section))
            if section_line_counts.get(section, 0) > 0:
                duties.append(make_duty("line_bay", section_line_counts[section], line_current, "I_line = 1.05·ΣSn/(√3·Un·Nline)", section=section, installation_position="incoming_line", require_grounding_switch=True))
            if section_transformer_counts.get(section, 0) > 0:
                duties.append(make_duty("transformer_bay", section_transformer_counts[section], transformer_current, "I_tr = 1.05·Sn/(√3·Un)", section=section, require_grounding_switch=True))
        duties.append(
            make_duty(
                "bus_coupler",
                1,
                transfer_current,
                "I_coupler = max(I_bus-I, I_bus-II) during bus transfer",
                section="common",
                requires_pt=False,
                requires_arrester=False,
                fault_entry_override=worst_fault_entry(),
            )
        )
    elif wiring_type == "double_bus_bypass":
        bypass_current = max(line_current, transformer_current)
        for section in sections:
            section_connections = section_line_counts.get(section, 0) + section_transformer_counts.get(section, 0)
            if section_connections > 0:
                duties.append(make_duty("bus_section", 1, section_currents.get(section, 0.0), "I_section = 1.05·ΣSn(bus)/√3·Un", section=section))
            if section_line_counts.get(section, 0) > 0:
                duties.append(make_duty("line_bay", section_line_counts[section], line_current, "I_line = 1.05·ΣSn/(√3·Un·Nline)", section=section, installation_position="incoming_line", require_grounding_switch=True))
            if section_transformer_counts.get(section, 0) > 0:
                duties.append(make_duty("transformer_bay", section_transformer_counts[section], transformer_current, "I_tr = 1.05·Sn/(√3·Un)", section=section, require_grounding_switch=True))
        duties.append(
            make_duty(
                "bus_coupler",
                1,
                transfer_current,
                "I_coupler = max(I_bus-I, I_bus-II) during bus transfer",
                section="common",
                requires_pt=False,
                requires_arrester=False,
                fault_entry_override=worst_fault_entry(),
            )
        )
        duties.append(
            make_duty(
                "bypass_breaker",
                1,
                bypass_current,
                "I_bypass = max(I_line, I_tr) during breaker maintenance transfer",
                section="common",
                requires_pt=False,
                requires_arrester=False,
                fault_entry_override=worst_fault_entry(),
            )
        )

    return duties


def generate_equipment_list(
    wiring: dict[str, Any],
    transformers: dict[str, Any],
    fault_analysis: dict[str, Any],
    selector: EquipmentSelector | None = None,
    neutral_grounding_mode: str = "solid",
) -> dict[str, Any]:
    selector = selector or EquipmentSelector()
    duties = build_equipment_duties(
        wiring=wiring,
        transformers=transformers,
        fault_analysis=fault_analysis,
        neutral_grounding_mode=neutral_grounding_mode,
    )
    evaluated_duties = [selector.select_bay_equipment(duty) for duty in duties]

    representative_roles: dict[str, Any] = {}
    for item in evaluated_duties:
        role = str(item["duty"]["role"])
        existing = representative_roles.get(role)
        if existing is None:
            representative_roles[role] = item
            continue
        current_duty = item["duty"]
        existing_duty = existing["duty"]
        current_key = (
            float(current_duty.get("symmetrical_fault_current_ka") or 0.0),
            float(current_duty.get("peak_current_ka") or 0.0),
            float(current_duty.get("imax_a") or 0.0),
        )
        existing_key = (
            float(existing_duty.get("symmetrical_fault_current_ka") or 0.0),
            float(existing_duty.get("peak_current_ka") or 0.0),
            float(existing_duty.get("imax_a") or 0.0),
        )
        if current_key > existing_key:
            representative_roles[role] = item

    return {
        "wiring_type": wiring["wiring_type"],
        "fault_basis": fault_analysis["design_fault_basis"],
        "fault_selected_mode": fault_analysis["selected_mode"],
        "fault_modes_evaluated": fault_analysis["comparison_modes"],
        "fault_governing_mode_by_section": fault_analysis["governing_mode_by_section"],
        "fault_scenarios": fault_analysis["scenarios"],
        "duties": evaluated_duties,
        "representative_roles": representative_roles,
    }


def generate_main_wiring(
    voltage_level: float,
    circuits: int,
    transformers: dict[str, Any],
    short_circuit_current: float | dict[str, Any],
    reliability: str,
    station_loads: list[dict[str, Any]] | None = None,
    through_power: bool = False,
    line_length: str = "medium",
    operating_mode: str = "normal",
    neutral_grounding_mode: str = "solid",
) -> dict[str, Any]:
    catalog = EquipmentDatabase()
    selector = EquipmentSelector(catalog)
    load_calculator = LoadCalculator(catalog)

    transformer_capacity = float(transformers.get("capacity", 0.0))
    transformer_count = int(transformers.get("count", 1) or 1)
    matched_transformer = _match_main_transformer(
        catalog,
        transformer_capacity,
        voltage_level if voltage_level >= 110.0 else 110.0,
    )

    wiring = select_wiring_type(
        voltage_level=voltage_level,
        circuits=circuits,
        reliability=reliability,
        transformer_count=transformer_count,
        through_power=through_power,
        line_length=line_length,
    )
    wiring["operating_mode"] = operating_mode

    fault_analysis = _build_fault_analysis(
        voltage_level=voltage_level,
        short_circuit_current=short_circuit_current,
        wiring=wiring,
        transformers=transformers,
    )

    equipment = generate_equipment_list(
        wiring=wiring,
        transformers=transformers,
        fault_analysis=fault_analysis,
        selector=selector,
        neutral_grounding_mode=neutral_grounding_mode,
    )

    if station_loads:
        station_service_load = load_calculator.calc_station_load(station_loads)
        station_transformer = load_calculator.select_station_transformer(station_service_load["s_station"])
    else:
        station_service_load = {
            "method": "missing_station_load_input",
            "required_input": "station_loads",
            "message": "Provide station_loads so the station-service transformer can be selected from the real station load instead of a heuristic estimate.",
            "s_station": None,
            "breakdown": [],
        }
        station_transformer = {}

    return {
        "input": {
            "voltage_level": voltage_level,
            "circuits": circuits,
            "transformers": {
                "capacity_mva": transformer_capacity,
                "count": transformer_count,
            },
            "short_circuit_current_ka": short_circuit_current,
            "reliability": _normalize_reliability(reliability),
            "station_loads": station_loads or [],
            "through_power": through_power,
            "line_length": line_length,
            "operating_mode": operating_mode,
            "neutral_grounding_mode": neutral_grounding_mode,
        },
        "wiring_scheme": wiring,
        "fault_basis": fault_analysis["selected_fault_basis"],
        "design_fault_basis": fault_analysis["design_fault_basis"],
        "fault_scenarios": fault_analysis["scenarios"],
        "fault_source_branches": fault_analysis["source_branches"],
        "fault_section_weights": fault_analysis["section_weights"],
        "fault_calculation_method": fault_analysis["calculation_method"],
        "fault_governing_mode_by_section": fault_analysis["governing_mode_by_section"],
        "matched_main_transformer": matched_transformer,
        "station_service_load": station_service_load,
        "station_service_transformer": station_transformer,
        "equipment_configuration": equipment,
        "database_path": str(catalog.db_path),
    }


if __name__ == "__main__":
    params = {
        "voltage_level": 110.0,
        "circuits": 2,
        "transformers": {"capacity": 50.0, "count": 2},
        "station_loads": [
            {"name": "main_control_room", "power": 12.0, "type": "frequent_continuous"},
            {"name": "battery_charger", "power": 6.5, "type": "continuous_infrequent"},
            {"name": "cooling_fan", "power": 9.0, "type": "frequent_intermittent"},
            {"name": "maintenance_socket", "power": 4.0, "type": "maintenance_test"},
        ],
        "short_circuit_current": {
            "method": "operation_curve",
            "prompt_for_curve": False,
            "shock_coefficient": 1.8,
            "clearing_time_s": 2.05,
            "curve_times_s": [0.0, 2.0, 4.0],
            "bridge_impedance": {"x_pu": 0.015},
            "sources": [
                {
                    "name": "system_A",
                    "section": "A",
                    "source_type": "infinite",
                    "curve_type": "infinite",
                    "impedance": {"x_pu": 0.30},
                },
                {
                    "name": "system_B",
                    "section": "B",
                    "source_type": "infinite",
                    "curve_type": "infinite",
                    "impedance": {"x_pu": 0.30},
                },
                {
                    "name": "hydro_A",
                    "section": "A",
                    "source_type": "finite",
                    "curve_type": "user_provided",
                    "source_capacity_mva": 20.0,
                    "impedance": {"x_pu": 0.242},
                    "i_star_by_time": {"0s": 3.727, "2s": 2.95, "4s": 2.35},
                },
                {
                    "name": "hydro_B",
                    "section": "B",
                    "source_type": "finite",
                    "curve_type": "user_provided",
                    "source_capacity_mva": 20.0,
                    "impedance": {"x_pu": 0.242},
                    "i_star_by_time": {"0s": 3.727, "2s": 2.95, "4s": 2.35},
                },
            ],
        },
        "reliability": "important",
        "through_power": True,
        "line_length": "short",
        "operating_mode": "normal",
        "neutral_grounding_mode": "solid",
    }
    print(json.dumps(generate_main_wiring(**params), ensure_ascii=False, indent=2))
