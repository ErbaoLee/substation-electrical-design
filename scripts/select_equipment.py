#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Database-backed equipment selection helpers with explicit validation checks."""

from __future__ import annotations

import json
import math
from typing import Any

from equipment_db import EquipmentDatabase, parse_current_ratio_primary, parse_float


DEFAULT_PHASE_SPACING_M = {
    10.0: 0.40,
    35.0: 0.60,
    110.0: 1.60,
    220.0: 2.50,
}

DEFAULT_SPAN_M = {
    10.0: 1.20,
    35.0: 1.60,
    110.0: 3.00,
    220.0: 3.50,
}

THERMAL_MATERIAL_CONSTANTS = {
    "soft_conductor": 87.0,
    "rigid_busbar": 87.0,
}

ALUMINUM_ALLOWABLE_STRESS_PA = 70_000_000.0


class EquipmentSelector:
    """Select substation primary equipment from the curated SQLite catalog with auto-verification and upgrade capabilities."""

    def __init__(self, catalog: EquipmentDatabase | None = None):
        self.catalog = catalog or EquipmentDatabase()
        # 自动升级时的最大电压倍数，避免选到过于离谱的高电压等级设备
        self.max_upgrade_voltage_multiplier = 2.0

    def calc_max_continuous_current(
        self,
        sn_kva: float,
        un_kv: float,
        factor: float = 1.05,
        n_circuits: int = 1,
        load_ratio: float = 1.0,
    ) -> float:
        return factor * sn_kva * load_ratio / (math.sqrt(3.0) * un_kv * n_circuits)

    @staticmethod
    def calc_temperature_correction(theta_al: float = 70.0, theta: float = 37.0, theta0: float = 25.0) -> float:
        return math.sqrt((theta_al - theta) / (theta_al - theta0))

    @staticmethod
    def _passed_check_count(checks: dict[str, bool]) -> int:
        return sum(1 for passed in checks.values() if passed)

    @staticmethod
    def _greater_equal(actual: float, required: float, abs_tol: float = 0.0, rel_tol: float = 1e-9) -> bool:
        return actual >= required or math.isclose(actual, required, abs_tol=abs_tol, rel_tol=rel_tol)

    @staticmethod
    def _measure_accuracy_ok(candidate: str | None, required: str | None) -> bool:
        if not required:
            return True
        candidate_value = parse_float(candidate)
        required_value = parse_float(required)
        if candidate_value is None or required_value is None:
            return str(candidate or "").strip() == str(required).strip()
        return candidate_value <= required_value

    @staticmethod
    def _protection_accuracy_ok(candidate: str | None, required: str | None) -> bool:
        if not required:
            return True
        candidate_text = str(candidate or "").strip().upper()
        required_text = str(required).strip().upper()
        if not candidate_text:
            return False
        if candidate_text == required_text:
            return True
        if candidate_text.endswith("P") and required_text.endswith("P"):
            candidate_value = parse_float(candidate_text[:-1])
            required_value = parse_float(required_text[:-1])
            if candidate_value is None or required_value is None:
                return False
            return candidate_value <= required_value
        return False

    @staticmethod
    def _preferred_breaker_type(voltage_level: float) -> str:
        return "sf6" if voltage_level >= 110.0 else "vacuum"

    @staticmethod
    def _conductor_corona_threshold(voltage_level: float) -> float:
        if voltage_level >= 220.0:
            return 300.0
        if voltage_level >= 110.0:
            return 120.0
        return 0.0

    @staticmethod
    def _default_phase_spacing(voltage_level: float) -> float:
        for threshold, spacing in sorted(DEFAULT_PHASE_SPACING_M.items()):
            if voltage_level <= threshold:
                return spacing
        return 3.0

    @staticmethod
    def _default_span(voltage_level: float) -> float:
        for threshold, span in sorted(DEFAULT_SPAN_M.items()):
            if voltage_level <= threshold:
                return span
        return 3.5

    @staticmethod
    def _parse_primary_voltage(model: dict[str, Any]) -> float | None:
        raw = str(model.get("rated_voltage_primary_kv") or "")
        return parse_float(raw.split("/")[0])

    def _auto_upgrade_selection(
        self,
        select_method: callable,
        params: dict[str, Any],
        voltage_param_name: str = "uns",
        max_upgrades: int = 3,
    ) -> dict[str, Any]:
        """自动升级查找满足要求的最小设备型号，初选失败时自动上调参数查找"""
        # 先尝试原始参数
        result = select_method(params)
        if result.get("all_passed", False):
            result["upgrade_level"] = 0
            result["upgrade_note"] = "原生参数满足要求，无需升级"
            return result

        # 失败时逐步升级查找
        base_voltage = params.get(voltage_param_name, 0)
        for upgrade_level in range(1, max_upgrades + 1):
            # 每次升级电压范围放宽20%，如果是断路器等设备隐含参数也会随着电压等级自动提升
            params_copy = params.copy()
            params_copy["max_voltage_multiplier"] = 1.5 + (upgrade_level * 0.2)
            if params_copy["max_voltage_multiplier"] > self.max_upgrade_voltage_multiplier:
                params_copy["max_voltage_multiplier"] = self.max_upgrade_voltage_multiplier

            result = select_method(params_copy)
            if result.get("all_passed", False):
                result["upgrade_level"] = upgrade_level
                result["upgrade_note"] = f"自动升级{upgrade_level}级，电压范围放宽至{params_copy['max_voltage_multiplier']*100:.0f}%"
                return result

        # 最终仍找不到合格设备
        result["upgrade_level"] = -1
        result["upgrade_note"] = "多次升级后仍无满足要求的设备，请检查参数合理性或扩展设备库"
        return result

    def validate_equipment(self, equipment: dict[str, Any]) -> dict[str, Any]:
        """校验单个设备选型是否满足所有要求，返回校验报告"""
        if not equipment:
            return {"valid": False, "error": "无设备选型结果", "failed_checks": [], "suggestion": "检查输入参数"}

        all_passed = equipment.get("all_passed", False)
        checks = equipment.get("checks", {})
        failed_checks = [k for k, v in checks.items() if not v]

        suggestion = []
        if not all_passed:
            if "in_check" in failed_checks:
                suggestion.append("建议选择额定电流更大的型号")
            if "inbr_check" in failed_checks or "incl_check" in failed_checks:
                suggestion.append("建议选择开断/关合能力更强的断路器型号")
            if "thermal_check" in failed_checks or "dynamic_check" in failed_checks:
                suggestion.append("建议选择热稳定/动稳定电流更大的型号")
            if "burden_check" in failed_checks:
                suggestion.append("建议选择二次负荷容量更大的互感器型号")
            if not suggestion:
                suggestion.append("建议核查参数要求或扩展设备库")

        return {
            "valid": all_passed,
            "equipment_model": equipment.get("model"),
            "equipment_type": equipment.get("category_code", ""),
            "voltage_level_kv": equipment.get("voltage_level"),
            "passed_check_count": equipment.get("passed_check_count", 0),
            "total_check_count": len(checks),
            "failed_checks": failed_checks,
            "suggestion": "；".join(suggestion) if suggestion else "所有校验项通过",
            "upgrade_level": equipment.get("upgrade_level", 0),
            "upgrade_note": equipment.get("upgrade_note", ""),
        }

    def validate_bay_equipment(self, bay_selection: dict[str, Any]) -> dict[str, Any]:
        """校验整个间隔的所有设备选型，返回整体校验报告"""
        equipment_types = ["circuit_breaker", "disconnect_switch", "conductor", "current_transformer", "voltage_transformer", "arrester"]
        validation_results = {}
        all_valid = True
        total_failed = 0

        for eq_type in equipment_types:
            if eq_type in bay_selection:
                val_result = self.validate_equipment(bay_selection[eq_type])
                validation_results[eq_type] = val_result
                if not val_result["valid"]:
                    all_valid = False
                    total_failed += 1

        return {
            "bay_valid": all_valid,
            "total_equipment": len(validation_results),
            "failed_equipment_count": total_failed,
            "equipment_validations": validation_results,
            "summary_note": f"共校验{len(validation_results)}台设备，{len(validation_results)-total_failed}台合格，{total_failed}台不合格" if validation_results else "无设备可校验"
        }

    def generate_verification_report(self, validation_result: dict[str, Any], output_format: str = "text") -> str | dict[str, Any]:
        """生成标准化的设备校验报告，支持text/json格式"""
        if output_format == "json":
            return validation_result

        # 文本格式报告
        lines = ["=" * 80]
        lines.append(f"设备校验报告 - {validation_result.get('summary_note', '')}")
        lines.append("=" * 80)

        for eq_type, val in validation_result.get("equipment_validations", {}).items():
            status = "✅ 合格" if val["valid"] else "❌ 不合格"
            lines.append(f"\n【{eq_type.replace('_', ' ').title()}】{val['equipment_model']} - {status}")
            lines.append(f"  电压等级: {val['voltage_level_kv']}kV")
            lines.append(f"  校验项: 通过{val['passed_check_count']}项 / 共{val['total_check_count']}项")
            if not val["valid"]:
                lines.append(f"  不合格项: {', '.join(val['failed_checks'])}")
                lines.append(f"  建议: {val['suggestion']}")
            if val.get("upgrade_level", 0) > 0:
                lines.append(f"  升级说明: {val['upgrade_note']}")

        lines.append("\n" + "=" * 80)
        if validation_result.get('bay_valid', False):
            conclusion = "所有设备校验合格"
        else:
            failed_count = validation_result.get('failed_equipment_count', 0)
            conclusion = f"存在{failed_count}台设备不合格"
        lines.append(f"整体结论: {conclusion}")
        lines.append("=" * 80)
        return "\n".join(lines)

    @staticmethod
    def _secondary_burden_ohm(load_va: float, secondary_current_a: float) -> float:
        return load_va / (secondary_current_a**2)

    @staticmethod
    def _select_best_result(results: list[dict[str, Any]], sort_key) -> dict[str, Any]:
        if not results:
            return {}
        ordered = sorted(
            results,
            key=lambda item: (
                0 if item["all_passed"] else 1,
                -item["passed_check_count"],
                sort_key(item),
            ),
        )
        return ordered[0]

    def _voltage_candidates(
        self,
        category_code: str,
        requested_voltage: float,
        field: str = "rated_voltage_kv",
        max_voltage_multiplier: float | None = 1.5,
    ) -> list[dict[str, Any]]:
        models = list(self.catalog.get_models(category_code))
        suitable = [
            model
            for model in models
            if (parse_float(model.get(field)) or self._parse_primary_voltage(model) or 0.0) >= requested_voltage
        ]
        if suitable and max_voltage_multiplier is not None:
            bounded = [
                model
                for model in suitable
                if (parse_float(model.get(field)) or self._parse_primary_voltage(model) or 0.0)
                <= requested_voltage * max_voltage_multiplier
            ]
            if bounded:
                return bounded
        return suitable or models

    def select_conductor(
        self,
        imax: float,
        voltage: float,
        conductor_type: str = "soft",
        i_ch: float = 0.0,
        qk: float = 0.0,
        phase_spacing_m: float | None = None,
        span_m: float | None = None,
        allowable_stress_pa: float = ALUMINUM_ALLOWABLE_STRESS_PA,
        material_constant: float | None = None,
    ) -> dict[str, Any]:
        category_code = "soft_conductor" if conductor_type == "soft" else "rigid_busbar"
        current_field = "ampacity_70c_a" if category_code == "soft_conductor" else "ampacity_flat_25c_a"
        material_constant = material_constant or THERMAL_MATERIAL_CONSTANTS[category_code]
        phase_spacing_m = phase_spacing_m or self._default_phase_spacing(voltage)
        span_m = span_m or self._default_span(voltage)

        k_temp = self.calc_temperature_correction()
        required_current = imax / k_temp
        s_min = math.sqrt(qk) / material_constant if qk > 0 else 0.0
        results: list[dict[str, Any]] = []

        for item in self.catalog.get_models(category_code):
            current_value = parse_float(item.get(current_field)) or 0.0
            area = parse_float(item.get("cross_section_mm2")) or 0.0
            checks = {
                "ampacity_check": self._greater_equal(current_value, required_current, abs_tol=5.0),
                "thermal_check": self._greater_equal(area, s_min, abs_tol=1.0) if s_min > 0 else True,
            }
            result = {
                "model": item["model"],
                "category_code": category_code,
                "area_mm2": area,
                "current_a": current_value,
                "imax_required_a": round(required_current, 2),
                "s_min_mm2": round(s_min, 2),
                "phase_spacing_m": phase_spacing_m,
                "span_m": span_m,
                "voltage_level_kv": voltage,
                "checks": checks,
            }

            if category_code == "rigid_busbar":
                width_mm = parse_float(item.get("width_mm")) or 0.0
                thickness_mm = parse_float(item.get("thickness_mm")) or 0.0
                if width_mm and thickness_mm and i_ch > 0:
                    b_m = min(width_mm, thickness_mm) / 1000.0
                    h_m = max(width_mm, thickness_mm) / 1000.0
                    w_m3 = b_m * h_m**2 / 6.0
                    fph = 1.73e-7 * (span_m / phase_spacing_m) * (i_ch * 1000.0) ** 2
                    stress_pa = fph * span_m**2 / (10.0 * w_m3) if w_m3 else float("inf")
                    checks["dynamic_check"] = stress_pa <= allowable_stress_pa or math.isclose(
                        stress_pa,
                        allowable_stress_pa,
                        rel_tol=1e-6,
                        abs_tol=1.0,
                    )
                    result["dynamic_stress_pa"] = round(stress_pa, 3)
                    result["allowable_stress_pa"] = allowable_stress_pa
                else:
                    checks["dynamic_check"] = False
                    result["dynamic_stress_pa"] = None
                    result["allowable_stress_pa"] = allowable_stress_pa
            else:
                corona_threshold = self._conductor_corona_threshold(voltage)
                checks["corona_check"] = self._greater_equal(area, corona_threshold, abs_tol=1.0) if corona_threshold > 0 else True
                result["corona_threshold_mm2"] = corona_threshold

            result["passed_check_count"] = self._passed_check_count(checks)
            result["all_passed"] = all(checks.values())
            results.append(result)

        best = self._select_best_result(
            results,
            sort_key=lambda item: (
                item["current_a"],
                item["area_mm2"],
            ),
        )
        if not best:
            return {}
        best["dynamic_reference_ka"] = i_ch
        return best

    def select_circuit_breaker(
        self,
        uns: float,
        imax: float,
        i_double_prime: float,
        i_ch: float,
        qk: float,
        voltage_level: float,
        max_voltage_multiplier: float = 1.5,
        auto_upgrade: bool = True,
    ) -> dict[str, Any]:
        # 核心选型逻辑封装为内部方法，用于自动升级迭代
        def _select_with_params(params: dict[str, Any]) -> dict[str, Any]:
            preferred_type = self._preferred_breaker_type(params["voltage_level"])
            results: list[dict[str, Any]] = []
            for item in self._voltage_candidates(
                "circuit_breaker",
                params["uns"],
                "rated_voltage_kv",
                max_voltage_multiplier=params.get("max_voltage_multiplier", 1.5)
            ):
                breaker_type = str(item.get("breaker_type") or "").lower()
                thermal_time_s = parse_float(item.get("thermal_stable_time_s")) or 1.0
                thermal_current = parse_float(item.get("thermal_stable_current_ka")) or 0.0
                it2t = (thermal_current * 1000.0) ** 2 * thermal_time_s
                checks = {
                    "un_check": self._greater_equal(parse_float(item.get("rated_voltage_kv")) or 0.0, params["uns"], abs_tol=0.1),
                    "in_check": self._greater_equal(parse_float(item.get("rated_current_a")) or 0.0, params["imax"], abs_tol=5.0),
                    "inbr_check": self._greater_equal(parse_float(item.get("rated_breaking_current_ka")) or 0.0, params["i_double_prime"], abs_tol=0.5),
                    "incl_check": self._greater_equal(parse_float(item.get("rated_making_current_ka")) or 0.0, params["i_ch"], abs_tol=0.5),
                    "thermal_check": self._greater_equal(it2t, params["qk"], abs_tol=1.0, rel_tol=1e-6),
                    "dynamic_check": self._greater_equal(parse_float(item.get("dynamic_stable_current_peak_ka")) or 0.0, params["i_ch"], abs_tol=0.5),
                    "type_check": preferred_type in breaker_type if breaker_type else False,
                }
                results.append(
                    {
                        "model": item["model"],
                        "breaker_type": item.get("breaker_type"),
                        "un": parse_float(item.get("rated_voltage_kv")),
                        "in": parse_float(item.get("rated_current_a")),
                        "inbr": parse_float(item.get("rated_breaking_current_ka")),
                        "incl": parse_float(item.get("rated_making_current_ka")),
                        "ies": parse_float(item.get("dynamic_stable_current_peak_ka")),
                        "it": thermal_current,
                        "thermal_time_s": thermal_time_s,
                        "it2t": it2t,
                        "preferred_type": preferred_type,
                        "checks": checks,
                        "passed_check_count": self._passed_check_count(checks),
                        "all_passed": all(checks.values()),
                        "voltage_level": params["voltage_level"],
                    }
                )
            return self._select_best_result(
                results,
                sort_key=lambda item: (
                    abs((item["un"] or 0.0) - params["uns"]),
                    item["in"] or float("inf"),
                    item["inbr"] or float("inf"),
                ),
            )

        params = {k: v for k, v in locals().items() if k not in ('_select_with_params', 'auto_upgrade', 'self')}
        if auto_upgrade:
            return self._auto_upgrade_selection(_select_with_params, params)
        return _select_with_params(params)

    def select_disconnect_switch(
        self,
        uns: float,
        imax: float,
        i_ch: float,
        qk: float,
        voltage_level: float,
        require_grounding_switch: bool = False,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []

        for item in self._voltage_candidates("disconnect_switch", uns, "rated_voltage_kv", max_voltage_multiplier=1.5):
            thermal_time_s = parse_float(item.get("thermal_stable_time_s")) or 1.0
            thermal_current = parse_float(item.get("thermal_stable_current_ka")) or 0.0
            it2t = (thermal_current * 1000.0) ** 2 * thermal_time_s
            grounding_switch_flag = bool(item.get("grounding_switch_flag"))
            checks = {
                "un_check": self._greater_equal(parse_float(item.get("rated_voltage_kv")) or 0.0, uns, abs_tol=0.1),
                "in_check": self._greater_equal(parse_float(item.get("rated_current_a")) or 0.0, imax, abs_tol=5.0),
                "thermal_check": self._greater_equal(it2t, qk, abs_tol=1.0, rel_tol=1e-6),
                "dynamic_check": self._greater_equal(parse_float(item.get("dynamic_stable_current_ka")) or 0.0, i_ch, abs_tol=0.5),
                "grounding_switch_check": grounding_switch_flag if require_grounding_switch else True,
            }
            results.append(
                {
                    "model": item["model"],
                    "un": parse_float(item.get("rated_voltage_kv")),
                    "in": parse_float(item.get("rated_current_a")),
                    "ies": parse_float(item.get("dynamic_stable_current_ka")),
                    "it": thermal_current,
                    "thermal_time_s": thermal_time_s,
                    "it2t": it2t,
                    "grounding_switch_flag": grounding_switch_flag,
                    "checks": checks,
                    "passed_check_count": self._passed_check_count(checks),
                    "all_passed": all(checks.values()),
                    "voltage_level": voltage_level,
                }
            )

        return self._select_best_result(
            results,
            sort_key=lambda item: (
                abs((item["un"] or 0.0) - uns),
                item["in"] or float("inf"),
                0 if item["grounding_switch_flag"] else 1,
            ),
        )

    def select_current_transformer(
        self,
        uns: float,
        imax: float,
        secondary_load_va: float,
        voltage_level: float,
        i_double_prime: float = 0.0,
        i_ch: float = 0.0,
        qk: float = 0.0,
        required_accuracy_measure: str = "0.5",
        required_accuracy_protection: str = "5P",
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []

        for item in self._voltage_candidates("current_transformer", uns, "rated_voltage_kv", max_voltage_multiplier=1.5):
            secondary_current = parse_float(item.get("rated_secondary_current_a")) or 5.0
            z2l = self._secondary_burden_ohm(secondary_load_va, secondary_current)
            primary_current = parse_current_ratio_primary(item.get("current_ratio")) or 0.0
            burden_05_ohm = parse_float(item.get("burden_05_ohm")) or 0.0
            burden_va = burden_05_ohm * secondary_current**2
            thermal_current = parse_float(item.get("thermal_stable_current_ka")) or 0.0
            thermal_time_s = parse_float(item.get("short_time_duration_s")) or 1.0
            it2t = (thermal_current * 1000.0) ** 2 * thermal_time_s
            dynamic_current = parse_float(item.get("dynamic_stable_current_ka")) or 0.0
            checks = {
                "un_check": self._greater_equal(parse_float(item.get("rated_voltage_kv")) or 0.0, uns, abs_tol=0.1),
                "ratio_check": self._greater_equal(primary_current, imax, abs_tol=5.0),
                "burden_check": self._greater_equal(burden_va, secondary_load_va, abs_tol=0.5),
                "accuracy_measure_check": self._measure_accuracy_ok(
                    str(item.get("accuracy_measure") or ""),
                    required_accuracy_measure,
                ),
                "accuracy_protection_check": self._protection_accuracy_ok(
                    str(item.get("accuracy_protection") or ""),
                    required_accuracy_protection,
                ),
                "thermal_check": self._greater_equal(it2t, qk, abs_tol=1.0, rel_tol=1e-6) if qk > 0 else self._greater_equal(thermal_current, i_double_prime, abs_tol=0.5),
                "dynamic_check": self._greater_equal(dynamic_current, i_ch, abs_tol=0.5) if i_ch > 0 else True,
            }
            results.append(
                {
                    "model": item["model"],
                    "ratio": item.get("current_ratio"),
                    "un": parse_float(item.get("rated_voltage_kv")),
                    "in": primary_current,
                    "secondary_current_a": secondary_current,
                    "z2n_0.5": burden_05_ohm,
                    "s2n_va": round(burden_va, 3),
                    "z2l": round(z2l, 3),
                    "it": thermal_current,
                    "thermal_time_s": thermal_time_s,
                    "it2t": it2t,
                    "ies": dynamic_current,
                    "checks": checks,
                    "passed_check_count": self._passed_check_count(checks),
                    "all_passed": all(checks.values()),
                    "voltage_level": voltage_level,
                }
            )

        return self._select_best_result(
            results,
            sort_key=lambda item: (
                abs((item["in"] or 0.0) - imax),
                item["s2n_va"] or float("inf"),
            ),
        )

    def select_voltage_transformer(
        self,
        voltage_level: float,
        total_measure_burden_va: float = 0.0,
        total_protection_burden_va: float = 0.0,
        neutral_grounding_mode: str = "solid",
        require_residual_voltage: bool | None = None,
        required_accuracy_measure: str = "0.5",
        required_accuracy_protection: str = "3P",
    ) -> dict[str, Any]:
        require_residual_voltage = (
            require_residual_voltage
            if require_residual_voltage is not None
            else neutral_grounding_mode in {"ungrounded", "arc_suppression", "resistance"}
        )
        results: list[dict[str, Any]] = []

        for item in self.catalog.get_models("voltage_transformer"):
            primary_voltage = self._parse_primary_voltage(item) or 0.0
            burden_05 = parse_float(item.get("burden_05_va")) or 0.0
            burden_3p = parse_float(item.get("burden_3p_va")) or 0.0
            aux_secondary = str(item.get("rated_voltage_aux_secondary_v") or "").strip()
            connection_type = str(item.get("connection_type") or "").lower()
            if voltage_level >= 110.0:
                connection_ok = connection_type in {"cascade_em", "cvt", "electromagnetic", "capacitive"}
            elif require_residual_voltage:
                connection_ok = bool(aux_secondary)
            else:
                connection_ok = True
            checks = {
                "un_check": self._greater_equal(primary_voltage, voltage_level, abs_tol=0.1),
                "burden_measure_check": self._greater_equal(burden_05, total_measure_burden_va, abs_tol=1.0),
                "burden_protection_check": self._greater_equal(burden_3p, total_protection_burden_va, abs_tol=1.0),
                "accuracy_measure_check": self._measure_accuracy_ok(
                    str(item.get("accuracy_measure") or ""),
                    required_accuracy_measure,
                ),
                "accuracy_protection_check": self._protection_accuracy_ok(
                    str(item.get("accuracy_protection") or ""),
                    required_accuracy_protection,
                ),
                "connection_check": connection_ok,
                "residual_output_check": bool(aux_secondary) if require_residual_voltage else True,
            }
            results.append(
                {
                    "model": item["model"],
                    "primary_voltage_kv": primary_voltage,
                    "secondary_voltage": item.get("rated_voltage_secondary_v"),
                    "aux_secondary_voltage": item.get("rated_voltage_aux_secondary_v"),
                    "accuracy_measure": item.get("accuracy_measure"),
                    "accuracy_protection": item.get("accuracy_protection"),
                    "burden_05_va": burden_05,
                    "burden_3p_va": burden_3p,
                    "connection_type": item.get("connection_type"),
                    "checks": checks,
                    "passed_check_count": self._passed_check_count(checks),
                    "all_passed": all(checks.values()),
                    "voltage_level": voltage_level,
                }
            )

        return self._select_best_result(
            results,
            sort_key=lambda item: (
                abs((item["primary_voltage_kv"] or 0.0) - voltage_level),
                item["burden_05_va"] or float("inf"),
            ),
        )

    def select_arrester(
        self,
        voltage_level: float,
        installation_position: str = "busbar",
        nominal_discharge_current_ka: float | None = None,
    ) -> dict[str, Any]:
        required_rated_voltage = {
            10.0: 17.0,
            35.0: 51.0,
            110.0: 100.0,
            220.0: 200.0,
        }
        rated_target = next(
            (value for threshold, value in sorted(required_rated_voltage.items()) if voltage_level <= threshold),
            voltage_level,
        )
        nominal_discharge_current_ka = nominal_discharge_current_ka or (10.0 if voltage_level >= 110.0 else 5.0)
        results: list[dict[str, Any]] = []

        for item in self._voltage_candidates("arrester", rated_target, "rated_voltage_kv", max_voltage_multiplier=3.0):
            rated_voltage = parse_float(item.get("rated_voltage_kv")) or 0.0
            discharge_current = parse_float(item.get("nominal_discharge_current_ka")) or 0.0
            position = str(item.get("installation_position") or "").lower()
            checks = {
                "rated_voltage_check": self._greater_equal(rated_voltage, rated_target, abs_tol=0.1),
                "discharge_current_check": self._greater_equal(discharge_current, nominal_discharge_current_ka, abs_tol=0.1),
                "position_check": installation_position.lower() in position if position else True,
            }
            results.append(
                {
                    "model": item["model"],
                    "rated_voltage_kv": rated_voltage,
                    "mcov_kv": parse_float(item.get("mcov_kv")),
                    "nominal_discharge_current_ka": discharge_current,
                    "residual_voltage_5ka_kv": parse_float(item.get("residual_voltage_5ka_kv")),
                    "installation_position": item.get("installation_position"),
                    "required_rated_voltage_kv": rated_target,
                    "checks": checks,
                    "passed_check_count": self._passed_check_count(checks),
                    "all_passed": all(checks.values()),
                    "voltage_level": voltage_level,
                }
            )

        return self._select_best_result(
            results,
            sort_key=lambda item: (
                abs((item["rated_voltage_kv"] or 0.0) - rated_target),
                item["nominal_discharge_current_ka"] or float("inf"),
            ),
        )

    def select_bay_equipment(self, duty: dict[str, Any]) -> dict[str, Any]:
        voltage_level = float(duty["voltage_level_kv"])
        fault_current = float(duty.get("symmetrical_fault_current_ka") or duty.get("fault_current_ka") or 0.0)
        peak_current = float(duty.get("peak_current_ka") or duty.get("fault_peak_current_ka") or 0.0)
        clearing_time_s = float(duty.get("clearing_time_s") or 1.0)
        thermal_effect = float(
            duty.get("thermal_effect_a2s")
            or ((fault_current * 1000.0) ** 2 * clearing_time_s if fault_current > 0 else 0.0)
        )
        neutral_grounding_mode = str(duty.get("neutral_grounding_mode") or "solid")
        conductor_type = str(duty.get("conductor_type") or ("soft" if voltage_level >= 110.0 else "hard"))
        installation_position = str(duty.get("installation_position") or "busbar")

        selection = {
            "duty": duty,
            "circuit_breaker": self.select_circuit_breaker(
                uns=voltage_level,
                imax=float(duty["imax_a"]),
                i_double_prime=fault_current,
                i_ch=peak_current,
                qk=thermal_effect,
                voltage_level=voltage_level,
            ),
            "disconnect_switch": self.select_disconnect_switch(
                uns=voltage_level,
                imax=float(duty["imax_a"]),
                i_ch=peak_current,
                qk=thermal_effect,
                voltage_level=voltage_level,
                require_grounding_switch=bool(duty.get("require_grounding_switch")),
            ),
            "conductor": self.select_conductor(
                imax=float(duty["imax_a"]),
                voltage=voltage_level,
                conductor_type=conductor_type,
                i_ch=peak_current,
                qk=thermal_effect,
                phase_spacing_m=parse_float(duty.get("phase_spacing_m")),
                span_m=parse_float(duty.get("span_m")),
            ),
            "current_transformer": self.select_current_transformer(
                uns=voltage_level,
                imax=float(duty["imax_a"]),
                secondary_load_va=float(duty.get("ct_secondary_load_va") or 2.5),
                voltage_level=voltage_level,
                i_double_prime=fault_current,
                i_ch=peak_current,
                qk=thermal_effect,
            ),
        }

        if duty.get("requires_pt", True):
            selection["voltage_transformer"] = self.select_voltage_transformer(
                voltage_level=voltage_level,
                total_measure_burden_va=float(duty.get("pt_measure_burden_va") or 0.0),
                total_protection_burden_va=float(duty.get("pt_protection_burden_va") or 0.0),
                neutral_grounding_mode=neutral_grounding_mode,
                require_residual_voltage=duty.get("require_residual_voltage"),
            )

        if duty.get("requires_arrester", True):
            selection["arrester"] = self.select_arrester(
                voltage_level=voltage_level,
                installation_position=installation_position,
                nominal_discharge_current_ka=parse_float(duty.get("arrester_discharge_current_ka")),
            )

        return selection


def example_selection() -> dict[str, Any]:
    selector = EquipmentSelector()
    conductor_110 = selector.select_conductor(
        imax=174.0,
        voltage=110.0,
        conductor_type="soft",
        i_ch=35.0,
        qk=2.52e9,
    )
    conductor_10 = selector.select_conductor(
        imax=1146.0,
        voltage=10.0,
        conductor_type="hard",
        i_ch=52.0,
        qk=1.31e9,
    )
    breaker_110 = selector.select_circuit_breaker(110.0, 347.0, 31.5, 80.0, 1.98e9, 110.0)
    switch_35 = selector.select_disconnect_switch(35.0, 700.0, 63.0, 1.92e9, 35.0, require_grounding_switch=True)
    ct_110 = selector.select_current_transformer(110.0, 174.0, 15.0, 110.0, 31.5, 80.0, 1.98e9)
    vt_10 = selector.select_voltage_transformer(
        10.0,
        total_measure_burden_va=60.0,
        total_protection_burden_va=80.0,
        neutral_grounding_mode="arc_suppression",
        require_residual_voltage=True,
    )
    arrester_110 = selector.select_arrester(110.0, installation_position="busbar", nominal_discharge_current_ka=10.0)

    bay_package = selector.select_bay_equipment(
        {
            "role": "bus_coupler",
            "voltage_level_kv": 35.0,
            "imax_a": 519.6,
            "symmetrical_fault_current_ka": 25.0,
            "peak_current_ka": 63.2,
            "thermal_effect_a2s": 1.91e9,
            "clearing_time_s": 3.05,
            "conductor_type": "hard",
            "require_grounding_switch": True,
            "ct_secondary_load_va": 15.0,
            "requires_pt": False,
            "requires_arrester": False,
        }
    )

    return {
        "conductor_110kv": conductor_110,
        "conductor_10kv": conductor_10,
        "breaker_110kv": breaker_110,
        "switch_35kv": switch_35,
        "ct_110kv": ct_110,
        "vt_10kv": vt_10,
        "arrester_110kv": arrester_110,
        "bay_package_35kv": bay_package,
    }


if __name__ == "__main__":
    print(json.dumps(example_selection(), ensure_ascii=False, indent=2))
