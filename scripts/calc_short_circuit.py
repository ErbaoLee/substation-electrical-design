#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Short-circuit calculation helpers aligned with the sample's operation-curve workflow."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Iterable, Sequence, Optional

import pandapower as pp
import pandapower.shortcircuit as sc
PANDAPOWER_AVAILABLE = True


DEFAULT_CLEARING_TIMES_S = {
    10.0: 4.05,
    35.0: 3.05,
    110.0: 2.05,
    220.0: 1.05,
}

DEFAULT_SHOCK_COEFFICIENT = 1.8

# Anchors extracted from the sample's curve-reading results (0 s values).
TURBINE_FINITE_SOURCE_CURVE_0S: tuple[tuple[float, float], ...] = (
    (0.30, 3.727),
    (0.40, 2.767),
    (0.61, 1.748),
    (0.65, 1.610),
    (0.67, 1.551),
)


def default_clearing_time(voltage_kv: float) -> float:
    for threshold, value in sorted(DEFAULT_CLEARING_TIMES_S.items()):
        if voltage_kv <= threshold:
            return value
    return 1.0


def _interpolate_curve(points: Sequence[tuple[float, float]], x_value: float) -> float:
    """Piecewise interpolation for operation-curve lookup."""

    if x_value <= 0:
        raise ValueError("Curve lookup requires x_js > 0.")
    ordered = sorted(points, key=lambda item: item[0])
    if not ordered:
        raise ValueError("Curve points cannot be empty.")

    first_x, first_y = ordered[0]
    if x_value <= first_x:
        return (first_x * first_y) / x_value

    last_x, last_y = ordered[-1]
    if x_value >= last_x:
        return (last_x * last_y) / x_value

    for left, right in zip(ordered[:-1], ordered[1:]):
        left_x, left_y = left
        right_x, right_y = right
        if left_x <= x_value <= right_x:
            span = right_x - left_x
            ratio = (x_value - left_x) / span if span else 0.0
            return left_y + ratio * (right_y - left_y)

    return last_y


@dataclass(frozen=True)
class PerUnitImpedance:
    """Per-unit impedance represented by explicit R and X components."""

    r_pu: float = 0.0
    x_pu: float = 0.0

    @property
    def complex_value(self) -> complex:
        return complex(self.r_pu, self.x_pu)

    @property
    def magnitude(self) -> float:
        return abs(self.complex_value)

    @property
    def x_over_r(self) -> float:
        if abs(self.r_pu) < 1e-9:
            return float("inf") if abs(self.x_pu) > 1e-9 else 0.0
        return abs(self.x_pu / self.r_pu)

    @classmethod
    def from_complex(cls, value: complex) -> "PerUnitImpedance":
        return cls(r_pu=value.real, x_pu=value.imag)

    @classmethod
    def from_magnitude(cls, magnitude_pu: float, x_over_r: float = 10.0) -> "PerUnitImpedance":
        if magnitude_pu <= 0:
            raise ValueError("Per-unit impedance magnitude must be positive.")
        if x_over_r <= 0:
            return cls(r_pu=magnitude_pu, x_pu=0.0)
        r_pu = magnitude_pu / math.sqrt(1.0 + x_over_r**2)
        return cls(r_pu=r_pu, x_pu=r_pu * x_over_r)

    def to_dict(self) -> dict[str, float | str]:
        x_over_r = self.x_over_r
        return {
            "r_pu": round(self.r_pu, 6),
            "x_pu": round(self.x_pu, 6),
            "magnitude_pu": round(self.magnitude, 6),
            "x_over_r": "inf" if math.isinf(x_over_r) else round(x_over_r, 3),
        }


@dataclass(frozen=True)
class BranchContribution:
    """A source or transfer branch that can feed a fault location."""

    name: str
    impedance: PerUnitImpedance
    section: str = "common"
    kind: str = "source"
    enabled: bool = True
    source_capacity_mva: float | None = None
    curve_type: str = "turbine_finite"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "section": self.section,
            "kind": self.kind,
            "enabled": self.enabled,
            "source_capacity_mva": None if self.source_capacity_mva is None else round(float(self.source_capacity_mva), 3),
            "curve_type": self.curve_type,
            "impedance": self.impedance.to_dict(),
        }


@dataclass(frozen=True)
class NetworkBranch:
    """Passive branch between two named nodes in an explicit fault network."""

    name: str
    node_a: str
    node_b: str
    impedance: PerUnitImpedance
    enabled: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "node_a": self.node_a,
            "node_b": self.node_b,
            "enabled": self.enabled,
            "impedance": self.impedance.to_dict(),
        }


@dataclass(frozen=True)
class FaultSource:
    """Source behind an internal impedance connected to an explicit network node."""

    name: str
    connection_node: str
    impedance: PerUnitImpedance
    source_type: str = "finite"
    source_capacity_mva: float | None = None
    curve_type: str = "user_provided"
    i_star_0s: float | None = None
    i_star_by_time: dict[str, float] | None = None
    enabled: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "connection_node": self.connection_node,
            "source_type": self.source_type,
            "source_capacity_mva": None if self.source_capacity_mva is None else round(float(self.source_capacity_mva), 3),
            "curve_type": self.curve_type,
            "i_star_0s": None if self.i_star_0s is None else round(float(self.i_star_0s), 6),
            "i_star_by_time": None if not self.i_star_by_time else {
                str(key): round(float(value), 6)
                for key, value in self.i_star_by_time.items()
            },
            "enabled": self.enabled,
            "impedance": self.impedance.to_dict(),
        }




def example_calculation() -> dict[str, object]:
    calc = get_calculator(base_power=100.0)

    sn_total_mva = 64.68
    x_hydro_source = 6.176
    x_thermal_source = 1.121
    x_system_parallel = 0.22
    x_t1 = 0.17
    x_t2 = 0.10

    x2_equivalent = calc.parallel_impedance(
        PerUnitImpedance(x_pu=x_hydro_source),
        PerUnitImpedance(x_pu=x_thermal_source),
    ).magnitude
    x_f1_sigma = x2_equivalent
    x_f2_sigma = x2_equivalent + calc.parallel_impedance(
        PerUnitImpedance(x_pu=0.5 * (x_t1 + x_t2)),
        PerUnitImpedance(x_pu=x_system_parallel),
    ).magnitude
    x_f3_sigma = x2_equivalent + calc.parallel_impedance(
        PerUnitImpedance(x_pu=0.5 * x_t1),
        PerUnitImpedance(x_pu=x_system_parallel),
    ).magnitude

    fault_f1 = calc.fault_from_xjs(
        x_sigma_pu=x_f1_sigma,
        sn_total_mva=sn_total_mva,
        voltage_kv=115.0,
        curve_type="turbine_finite",
        i_star=1.748,
        clearing_time_s=2.05,
    )
    fault_f2 = calc.fault_from_xjs(
        x_sigma_pu=x_f2_sigma,
        sn_total_mva=sn_total_mva,
        voltage_kv=37.0,
        curve_type="turbine_finite",
        i_star=1.551,
        clearing_time_s=3.05,
    )
    fault_f3 = calc.fault_from_xjs(
        x_sigma_pu=x_f3_sigma,
        sn_total_mva=sn_total_mva,
        voltage_kv=10.5,
        curve_type="turbine_finite",
        i_star=1.610,
        clearing_time_s=4.05,
    )

    sectioned_bus_branches = [
        BranchContribution(
            "source_a",
            PerUnitImpedance(x_pu=x_f1_sigma / 0.5),
            section="A",
            source_capacity_mva=sn_total_mva * 0.5,
            curve_type="turbine_finite",
        ),
        BranchContribution(
            "source_b",
            PerUnitImpedance(x_pu=x_f1_sigma / 0.5),
            section="B",
            source_capacity_mva=sn_total_mva * 0.5,
            curve_type="turbine_finite",
        ),
    ]
    sectioned_bus_closed = calc.calc_bus_fault(
        "single_bus_sectionalized",
        voltage_kv=110.0,
        branches=sectioned_bus_branches,
        fault_section="A",
        operating_mode="normal",
        clearing_time_s=2.05,
        use_operation_curve=True,
    )
    sectioned_bus_split = calc.calc_bus_fault(
        "single_bus_sectionalized",
        voltage_kv=110.0,
        branches=sectioned_bus_branches,
        fault_section="A",
        operating_mode="split",
        clearing_time_s=2.05,
        use_operation_curve=True,
    )

    return {
        "sample_formula_chain": {
            "sn_total_mva": sn_total_mva,
            "x_sigma": {
                "f1_110kv": round(x_f1_sigma, 3),
                "f2_35kv": round(x_f2_sigma, 3),
                "f3_10kv": round(x_f3_sigma, 3),
            },
            "fault_results": {
                "f1_110kv": fault_f1,
                "f2_35kv": fault_f2,
                "f3_10kv": fault_f3,
            },
        },
        "wiring_mode_comparison": {
            "single_bus_sectionalized_coupler_closed": sectioned_bus_closed,
            "single_bus_sectionalized_coupler_open": sectioned_bus_split,
        },
        "curve_points_used": {
            "turbine_finite_0s": [
                {"x_js": point[0], "i_star": point[1]}
                for point in TURBINE_FINITE_SOURCE_CURVE_0S
            ],
        },
    }


# 先在全局定义基础运行方式，避免类推导式作用域问题
_BASE_OPERATION_MODES = [
    "normal",
    "split",
    "section_outage",
    "bridge_open",
    "bus_transfer_isolated"
]
_SUPPORTED_OPERATION_MODES = [f"{t}_{m}" for t in ["max", "min"] for m in _BASE_OPERATION_MODES] + _BASE_OPERATION_MODES

class ShortCircuitCalculator:
    """Three-phase short-circuit calculations using pandapower power system simulation library."""

    # 支持的运行模式分类
    OPERATION_MODE_TYPE = {
        "max": "最大运行方式（所有电源投入、母联合上，短路电流最大，用于设备动热稳定校验）",
        "min": "最小运行方式（最少电源投入、母联断开，短路电流最小，用于保护灵敏度校验）",
        "custom": "自定义运行方式"
    }

    # 基础运行方式
    BASE_OPERATION_MODES = _BASE_OPERATION_MODES

    # 支持的所有运行方式 = 最大最小前缀 + 基础运行方式
    SUPPORTED_OPERATION_MODES = _SUPPORTED_OPERATION_MODES

    def __init__(
        self,
        base_power: float = 100.0,
        frequency_hz: float = 50.0,
        default_shock_coefficient: float = DEFAULT_SHOCK_COEFFICIENT,
    ):
        self.Sb = float(base_power)
        self.frequency_hz = float(frequency_hz)
        self.default_shock_coefficient = float(default_shock_coefficient)
        self._curve_prompt_cache: dict[tuple[str, str, float, str], float] = {}

    def calc_all_scenarios(  # type: ignore
        self,
        wiring_type: str,
        voltage_kv: float,
        branches: Iterable[BranchContribution],
        sources: Optional[Sequence[FaultSource]] = None,
        passive_branches: Optional[Sequence[NetworkBranch]] = None,
        fault_sections: Optional[list[str]] = None,
        operation_modes: Optional[list[str]] = None,
        calculate_line_short_circuits: bool = False,
        line_short_circuit_points: list[float] = [0.0, 0.5, 1.0],  # 首端、中点、末端
        clearing_time_s: Optional[float] = None,
        include_max_min_modes: bool = True,  # 是否包含最大最小运行方式
        output_statistics: bool = True,  # 是否输出统计信息
        **kwargs
    ) -> dict[str, Any]:
        """
        [Skill] 自动遍历所有运行方式和所有短路点，批量计算短路电流
        覆盖所有可能的运行场景，生成完整的短路电流计算报告

        Args:
            wiring_type: 接线类型
            voltage_kv: 电压等级(kV)
            branches: 支路列表（用于母线故障计算）
            sources: 电源列表（用于网络故障计算，和passive_branches搭配使用）
            passive_branches: 网络被动支路列表（用于网络故障/线路故障计算）
            fault_sections: 指定要计算的故障段，默认自动枚举所有段
            operation_modes: 指定要计算的运行方式，默认枚举所有支持的运行方式
            calculate_line_short_circuits: 是否计算线路短路，默认False只计算母线短路
            line_short_circuit_points: 线路短路采样点百分比(0~1)，默认[0, 0.5, 1]（首、中、末）
            clearing_time_s: 故障清除时间，默认使用自动配置
            **kwargs: 其他透传给calc_bus_fault/calc_network_fault的参数

        Returns:
            结构化的完整计算结果:
            {
                "summary": {
                    "total_scenarios": 总计算场景数,
                    "success_count": 成功计算数,
                    "fail_count": 失败数,
                    "max_short_circuit_current": 最大短路电流(kA),
                    "min_short_circuit_current": 最小短路电流(kA)
                },
                "results": [
                    {
                        "operation_mode": 运行方式,
                        "fault_section": 故障段,
                        "fault_location": 短路点位置/描述,
                        "fault_type": "bus" / "line",
                        "symmetrical_current_ka": 对称短路电流(kA),
                        "peak_current_ka": 峰值电流(kA),
                        "short_circuit_capacity_mva": 短路容量(MVA),
                        "full_result": 完整的短路计算结果字典
                    },
                    ...
                ],
                "failed_scenarios": [
                    {
                        "operation_mode": 运行方式,
                        "fault_location": 短路点,
                        "error": 错误信息
                    },
                    ...
                ]
            }
        """
        # 1. 准备要计算的运行方式列表
        if not operation_modes:
            # 根据接线类型过滤不支持的运行方式
            if wiring_type == "single_bus":
                base_modes = ["normal"]
            elif wiring_type in ["inner_bridge", "outer_bridge"]:
                base_modes = ["normal", "bridge_open"]
            else:  # 分段母线、双母线等
                base_modes = [m for m in self.BASE_OPERATION_MODES if m != "bridge_open"]

            # 根据参数决定是否包含最大最小运行方式
            target_operation_modes = base_modes.copy()
            if include_max_min_modes:
                for mode in base_modes:
                    target_operation_modes.append(f"max_{mode}")
                    target_operation_modes.append(f"min_{mode}")
            # 去重
            target_operation_modes = list(set(target_operation_modes))
        else:
            target_operation_modes = operation_modes

        # 2. 准备要计算的故障段列表
        if not fault_sections:
            # 自动提取所有支路的section作为故障段
            all_sections = set()
            for branch in branches:
                if hasattr(branch, 'section') and branch.section:
                    all_sections.add(branch.section)
            all_sections.add("common")
            target_fault_sections = list(all_sections)
        else:
            target_fault_sections = fault_sections

        # 3. 收集所有短路点
        fault_locations = []

        # 3.1 母线短路点（适用于所有计算场景）
        if passive_branches:
            # 从网络支路提取所有母线节点
            bus_nodes = set()
            for branch in passive_branches:
                if branch.enabled:
                    bus_nodes.add(branch.node_a)
                    bus_nodes.add(branch.node_b)
            if sources:
                for source in sources:
                    if source.enabled:
                        bus_nodes.add(source.connection_node)
            for node in bus_nodes:
                fault_locations.append({
                    "type": "bus",
                    "location": node,
                    "description": f"母线[{node}]短路"
                })
        else:
            # 简单母线故障场景，故障点对应故障段
            for section in target_fault_sections:
                fault_locations.append({
                    "type": "bus",
                    "location": section,
                    "description": f"{section}段母线短路"
                })

        # 3.2 线路短路点（可选）
        if calculate_line_short_circuits and passive_branches:
            for branch in passive_branches:
                if not branch.enabled:
                    continue
                for pct in line_short_circuit_points:
                    if pct == 0.0:
                        desc = f"线路[{branch.name}]首端短路"
                    elif pct == 1.0:
                        desc = f"线路[{branch.name}]末端短路"
                    else:
                        desc = f"线路[{branch.name}]{int(pct*100)}%位置短路"

                    fault_locations.append({
                        "type": "line",
                        "location": {"line": branch.name, "distance_pct": pct},
                        "description": desc
                    })

        # 4. 遍历所有场景计算
        results = []
        failed_scenarios = []
        all_currents = []

        total_scenarios = len(target_operation_modes) * len(target_fault_sections) * len(fault_locations)
        current_idx = 0

        for op_mode in target_operation_modes:
            for fault_section in target_fault_sections:
                for fault_loc in fault_locations:
                    current_idx += 1
                    try:
                        if fault_loc["type"] == "bus" and not passive_branches:
                            # 简单母线故障计算
                            sc_result = self.calc_bus_fault(
                                wiring_type=wiring_type,
                                voltage_kv=voltage_kv,
                                branches=branches,
                                fault_section=fault_section,
                                operating_mode=op_mode,
                                clearing_time_s=clearing_time_s,
                                **kwargs
                            )
                            from typing import cast
                            sc_dict = cast(dict[str, Any], sc_result)
                            fault_data = sc_dict.get("fault", {}) if "fault" in sc_dict else sc_dict
                            sym_current = float(fault_data.get("symmetrical_current_ka", 0.0))
                            peak_current = float(fault_data.get("peak_current_ka", 0.0))
                            sc_capacity = float(fault_data.get("short_circuit_capacity_mva", 0.0))

                        else:
                            # 网络/线路故障计算
                            if not sources or not passive_branches:
                                continue

                            sc_result = self.calc_network_fault(
                                voltage_kv=voltage_kv,
                                fault_location=fault_loc["location"],
                                passive_branches=passive_branches,
                                sources=sources,
                                clearing_time_s=clearing_time_s,
                                **kwargs
                            )
                            sym_current = sc_result["symmetrical_current_ka"]
                            peak_current = sc_result["peak_current_ka"]
                            sc_capacity = sc_result["short_circuit_capacity_mva"]

                        # 记录结果
                        results.append({
                            "operation_mode": op_mode,
                            "fault_section": fault_section,
                            "fault_location": fault_loc["description"],
                            "fault_type": fault_loc["type"],
                            "symmetrical_current_ka": round(float(sym_current), 3),
                            "peak_current_ka": round(float(peak_current), 3),
                            "short_circuit_capacity_mva": round(float(sc_capacity), 3),
                            "full_result": sc_result
                        })

                        if float(sym_current) > 0:
                            all_currents.append(float(sym_current))

                    except Exception as e:
                        failed_scenarios.append({
                            "operation_mode": op_mode,
                            "fault_section": fault_section,
                            "fault_location": fault_loc["description"],
                            "error": str(e)
                        })

        # 5. 生成汇总信息
        summary = {
            "total_scenarios": total_scenarios,
            "success_count": len(results),
            "fail_count": len(failed_scenarios),
            "max_short_circuit_current_ka": round(max(all_currents), 3) if all_currents else 0,
            "min_short_circuit_current_ka": round(min(all_currents), 3) if all_currents else 0,
            "calculated_operation_modes": target_operation_modes,
            "calculated_fault_sections": target_fault_sections,
            "total_fault_locations": len(fault_locations),
            "include_max_min_modes": include_max_min_modes,
            "voltage_level_kv": voltage_kv,
            "wiring_type": wiring_type
        }

        if output_statistics and results:
            # 按运行方式统计电流分布
            currents_by_mode = {}
            for res in results:
                mode = res["operation_mode"]
                curr = res["symmetrical_current_ka"]
                if mode not in currents_by_mode:
                    currents_by_mode[mode] = []
                currents_by_mode[mode].append(curr)

            summary["current_by_mode_statistics"] = {
                mode: {
                    "max_ka": round(max(vals), 3),
                    "min_ka": round(min(vals), 3),
                    "avg_ka": round(sum(vals)/len(vals), 3),
                    "sample_count": len(vals)
                } for mode, vals in currents_by_mode.items()
            }

            # 按故障类型统计
            currents_by_fault_type = {}
            for res in results:
                ft = res["fault_type"]
                curr = res["symmetrical_current_ka"]
                if ft not in currents_by_fault_type:
                    currents_by_fault_type[ft] = []
                currents_by_fault_type[ft].append(curr)

            summary["current_by_fault_type_statistics"] = {
                ftype: {
                    "max_ka": round(max(vals), 3),
                    "min_ka": round(min(vals), 3),
                    "avg_ka": round(sum(vals)/len(vals), 3),
                    "sample_count": len(vals)
                } for ftype, vals in currents_by_fault_type.items()
            }

        return {
            "summary": summary,
            "results": results,
            "failed_scenarios": failed_scenarios
        }

    # ------------------------------------------------------------------
    # Multi-voltage-level substation short circuit
    # ------------------------------------------------------------------

    def calc_substation_short_circuit(
        self,
        voltage_levels: dict[str, float],
        fault_points: list[dict],
    ) -> dict[str, object]:
        """
        [Skill] Multi-voltage-level substation short circuit calculation.

        Properly handles per-unit impedance accumulation and correct base
        current calculation for each voltage level.  Each fault point
        explicitly specifies its voltage level so that the base current
        Ib = Sb / (sqrt3 * Uav) is evaluated at the *correct* average
        voltage for that bus, avoiding the voltage-level confusion that
        arises when a single voltage_kv is used for all fault points.

        Args:
            voltage_levels: Voltage level name -> average voltage (kV).
                Example: {"35kV": 37.0, "10kV": 10.5}
            fault_points: List of dicts, each with:
                name (str): Identifier, e.g. "d1"
                voltage_level (str): Must match a key in voltage_levels
                label (str): Description, e.g. "35kV母线三相短路"
                impedance_chain (list): Ordered impedance components from
                    source to fault point, each:
                    {"name": str, "impedance": PerUnitImpedance,
                     "detail": str (optional)}
                clearing_time_s (float, optional): Override clearing time
                shock_coefficient (float, optional): Override (default 1.8)

        Returns:
            {"summary": {...}, "results": [{...}, ...]}.
            Each result contains "calculation_detail" with step-by-step
            formulas suitable for report generation.
        """
        results: list[dict] = []

        for fp_def in fault_points:
            fp_name = fp_def["name"]
            vl_name = fp_def["voltage_level"]

            if vl_name not in voltage_levels:
                raise ValueError(
                    f"Fault point '{fp_name}' references voltage level "
                    f"'{vl_name}' not found.  Available: "
                    f"{list(voltage_levels.keys())}"
                )

            u_av = voltage_levels[vl_name]
            clearing_time = fp_def.get("clearing_time_s") or default_clearing_time(u_av)
            k_ch = float(
                fp_def.get("shock_coefficient") or self.default_shock_coefficient
            )

            chain = fp_def["impedance_chain"]
            if not chain:
                raise ValueError(
                    f"Fault point '{fp_name}' has empty impedance_chain."
                )

            # --- accumulate impedance (series) ---
            z_eq = chain[0]["impedance"]
            for comp in chain[1:]:
                z_eq = self.series_impedance(z_eq, comp["impedance"])

            # --- base current for THIS voltage level ---
            ib = self.calc_base_current(u_av)

            # --- fault currents ---
            i_sym = ib / z_eq.magnitude
            i_peak = math.sqrt(2) * k_ch * i_sym
            i_full = math.sqrt(1 + 2 * (k_ch - 1) ** 2) * i_sym
            s_sc = math.sqrt(3) * u_av * i_sym
            q_k = (i_sym * 1000) ** 2 * clearing_time

            # --- build impedance chain detail ---
            chain_detail: list[dict] = []
            x_parts: list[float] = []
            for comp in chain:
                z = comp["impedance"]
                chain_detail.append({
                    "name": comp["name"],
                    "r_pu": round(z.r_pu, 6),
                    "x_pu": round(z.x_pu, 6),
                    "magnitude_pu": round(z.magnitude, 6),
                    "detail": comp.get("detail", ""),
                })
                x_parts.append(round(z.magnitude, 4))

            x_sigma_formula = " + ".join(f"{v:.4f}" for v in x_parts)

            calculation_detail = {
                "voltage_level": vl_name,
                "average_voltage_kv": u_av,
                "impedance_chain": chain_detail,
                "x_sigma_pu": round(z_eq.magnitude, 6),
                "x_sigma_r_pu": round(z_eq.r_pu, 6),
                "x_sigma_x_pu": round(z_eq.x_pu, 6),
                "x_sigma_formula": (
                    f"{x_sigma_formula} = {z_eq.magnitude:.4f}"
                ),
                "base_capacity_mva": self.Sb,
                "base_current_formula": (
                    f"Sb/(√3×Uav) = {self.Sb}/(1.732×{u_av}) "
                    f"= {ib:.4f} kA"
                ),
                "base_current_ka": round(ib, 4),
                "symmetrical_formula": (
                    f"Ib/XΣ = {ib:.4f}/{z_eq.magnitude:.4f} "
                    f"= {i_sym:.4f} kA"
                ),
                "symmetrical_current_ka": round(i_sym, 4),
                "shock_coefficient": k_ch,
                "peak_formula": (
                    f"√2×Kch×I\" = 1.414×{k_ch}×{i_sym:.4f} "
                    f"= {i_peak:.4f} kA"
                ),
                "peak_current_ka": round(i_peak, 4),
                "full_formula": (
                    f"√(1+2×(Kch-1)²)×I\" = "
                    f"√(1+2×{(k_ch - 1):.1f}²)×{i_sym:.4f} "
                    f"= {i_full:.4f} kA"
                ),
                "full_current_ka": round(i_full, 4),
                "capacity_formula": (
                    f"√3×Uav×I\" = 1.732×{u_av}×{i_sym:.4f} "
                    f"= {s_sc:.2f} MVA"
                ),
                "short_circuit_capacity_mva": round(s_sc, 2),
                "thermal_formula": (
                    f"(I\"×1000)²×tk = ({i_sym * 1000:.1f})²×{clearing_time} "
                    f"= {q_k:.0f} A²·s"
                ),
                "thermal_effect_a2s": round(q_k, 1),
                "clearing_time_s": clearing_time,
            }

            result: dict[str, object] = {
                "fault_point": fp_name,
                "voltage_level": vl_name,
                "label": fp_def.get("label", f"{vl_name}三相短路"),
                "calculation_detail": calculation_detail,
                "equivalent_impedance": z_eq.to_dict(),
                "symmetrical_current_ka": round(i_sym, 4),
                "peak_current_ka": round(i_peak, 4),
                "full_current_ka": round(i_full, 4),
                "short_circuit_capacity_mva": round(s_sc, 2),
                "thermal_effect_a2s": round(q_k, 1),
                "clearing_time_s": clearing_time,
                "base_current_ka": round(ib, 4),
            }
            results.append(result)

        # --- summary ---
        summary = {
            "base_power_mva": self.Sb,
            "voltage_levels": voltage_levels,
            "total_fault_points": len(results),
            "fault_point_summary": [
                {
                    "name": r["fault_point"],
                    "voltage_level": r["voltage_level"],
                    "label": r["label"],
                    "x_sigma_pu": r["calculation_detail"]["x_sigma_pu"],  # type: ignore[index]
                    "base_current_ka": r["base_current_ka"],
                    "symmetrical_current_ka": r["symmetrical_current_ka"],
                    "peak_current_ka": r["peak_current_ka"],
                    "full_current_ka": r["full_current_ka"],
                    "short_circuit_capacity_mva": r["short_circuit_capacity_mva"],
                    "thermal_effect_a2s": r["thermal_effect_a2s"],
                }
                for r in results
            ],
        }

        return {
            "summary": summary,
            "results": results,
        }

    @staticmethod
    def format_fault_calculation_detail(result: dict) -> str:
        """Format a single fault point result into detailed markdown."""
        detail = result["calculation_detail"]
        lines: list[str] = []

        lines.append(f"### {result['label']}\n")

        # Impedance chain
        lines.append(
            f"**阻抗归算（标幺值，Sb = {detail['base_capacity_mva']} MVA）：**"
        )
        for comp in detail["impedance_chain"]:
            d = f"（{comp['detail']}）" if comp["detail"] else ""
            if comp["r_pu"] > 1e-6:
                lines.append(
                    f"- {comp['name']}{d}: R* = {comp['r_pu']:.4f}, "
                    f"X* = {comp['x_pu']:.4f}, "
                    f"|Z*| = {comp['magnitude_pu']:.4f}"
                )
            else:
                lines.append(
                    f"- {comp['name']}{d}: X* = {comp['x_pu']:.4f}"
                )
        lines.append(
            f"- **等值阻抗:** |Z*Σ| = {detail['x_sigma_formula']}"
        )
        lines.append("")

        # Base values
        lines.append("**基准值：**")
        lines.append(f"- Sb = {detail['base_capacity_mva']} MVA")
        lines.append(f"- Uav = {detail['average_voltage_kv']} kV")
        lines.append(f"- Ib = {detail['base_current_formula']}")
        lines.append("")

        # Current calculation
        lines.append("**短路电流计算：**")
        lines.append(f"- 对称短路电流: I\" = {detail['symmetrical_formula']}")
        lines.append(f"- 冲击系数: Kch = {detail['shock_coefficient']}")
        lines.append(f"- 冲击电流: ich = {detail['peak_formula']}")
        lines.append(f"- 全电流: Ich = {detail['full_formula']}")
        lines.append(f"- 短路容量: Sd = {detail['capacity_formula']}")
        lines.append(
            f"- 热效应: Qk = {detail['thermal_formula']}"
            f"（tk = {detail['clearing_time_s']}s）"
        )

        return "\n".join(lines)

    @staticmethod
    def format_sc_summary_table(sc_results: dict) -> str:
        """Format all fault point results into a summary table."""
        lines: list[str] = []
        header = (
            "| 短路点 | 电压等级 | 等值阻抗(pu) | Ib(kA) | "
            "I\\\"(kA) | ich(kA) | Ich(kA) | Sd(MVA) | Qk(A²·s) | tk(s) |"
        )
        sep = (
            "|--------|---------|-------------|--------|"
            "---------|---------|---------|---------|---------|------|"
        )
        lines.append(header)
        lines.append(sep)

        for r in sc_results["results"]:
            d = r["calculation_detail"]
            lines.append(
                f"| {r['fault_point']} | {r['voltage_level']} "
                f"| {d['x_sigma_pu']:.4f} | {d['base_current_ka']:.4f} "
                f"| {r['symmetrical_current_ka']:.4f} | "
                f"{r['peak_current_ka']:.4f} "
                f"| {r['full_current_ka']:.4f} | "
                f"{r['short_circuit_capacity_mva']:.2f} "
                f"| {r['thermal_effect_a2s']:.0f} | "
                f"{d['clearing_time_s']} |"
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Single-voltage-level base methods
    # ------------------------------------------------------------------

    def calc_base_current(self, voltage_kv: float) -> float:
        return self.Sb / (math.sqrt(3.0) * voltage_kv)

    def calc_source_base_current(self, source_capacity_mva: float, voltage_kv: float) -> float:
        if source_capacity_mva <= 0:
            raise ValueError("Source capacity must be positive.")
        return source_capacity_mva / (math.sqrt(3.0) * voltage_kv)

    def calc_line_impedance(
        self,
        x1_ohm_per_km: float,
        length_km: float,
        voltage_kv: float,
        r1_ohm_per_km: float = 0.0,
    ) -> PerUnitImpedance:
        z_base = (voltage_kv**2) / self.Sb
        return PerUnitImpedance(
            r_pu=(r1_ohm_per_km * length_km) / z_base,
            x_pu=(x1_ohm_per_km * length_km) / z_base,
        )

    def calc_transformer_impedance(
        self,
        uk_percent: float,
        sn_mva: float,
        x_over_r: float = 20.0,
    ) -> PerUnitImpedance:
        magnitude = (uk_percent / 100.0) * self.Sb / sn_mva
        return PerUnitImpedance.from_magnitude(magnitude, x_over_r=x_over_r)

    def split_three_winding_transformer(
        self,
        uk_hm_percent: float,
        uk_hl_percent: float,
        uk_ml_percent: float,
        sn_mva: float,
        x_over_r: float = 20.0,
        min_component_percent: float = 0.1,
    ) -> dict[str, dict[str, object]]:
        raw_components = {
            "hv": 0.5 * (uk_hm_percent + uk_hl_percent - uk_ml_percent),
            "mv": 0.5 * (uk_hm_percent + uk_ml_percent - uk_hl_percent),
            "lv": 0.5 * (uk_ml_percent + uk_hl_percent - uk_hm_percent),
        }
        result: dict[str, dict[str, object]] = {}
        for side, raw_percent in raw_components.items():
            effective_percent = max(raw_percent, min_component_percent)
            result[side] = {
                "raw_percent": round(raw_percent, 3),
                "effective_percent": round(effective_percent, 3),
                "impedance": self.calc_transformer_impedance(
                    effective_percent,
                    sn_mva,
                    x_over_r=x_over_r,
                ),
            }
        return result

    def calc_generator_impedance(
        self,
        xd_double_prime: float,
        rated_power_mw: float,
        cos_phi: float = 0.85,
        x_over_r: float = 12.0,
    ) -> PerUnitImpedance:
        apparent_power_mva = rated_power_mw / cos_phi
        magnitude = xd_double_prime * self.Sb / apparent_power_mva
        return PerUnitImpedance.from_magnitude(magnitude, x_over_r=x_over_r)

    def calc_system_impedance(
        self,
        short_circuit_capacity_mva: float,
        x_over_r: float = 10.0,
    ) -> PerUnitImpedance:
        magnitude = self.Sb / short_circuit_capacity_mva
        return PerUnitImpedance.from_magnitude(magnitude, x_over_r=x_over_r)

    def series_impedance(self, *components: PerUnitImpedance) -> PerUnitImpedance:
        total = sum((item.complex_value for item in components), start=0j)
        return PerUnitImpedance.from_complex(total)

    def parallel_impedance(self, *components: PerUnitImpedance) -> PerUnitImpedance:
        active = [item for item in components if item.magnitude > 0]
        if not active:
            raise ValueError("At least one non-zero impedance is required for a parallel reduction.")
        inverse_total = sum(1.0 / item.complex_value for item in active)
        return PerUnitImpedance.from_complex(1.0 / inverse_total)

    def _build_pp_network(
        self,
        voltage_kv: float,
        passive_branches: Sequence[NetworkBranch],
        sources: Sequence[FaultSource],
        fault_node: str | None = None,
    ):
        """Build pandapower network from custom model structures."""
        net = pp.create_empty_network(f_hz=self.frequency_hz)

        # Collect all unique nodes
        nodes = set()
        for branch in passive_branches:
            if branch.enabled:
                nodes.add(branch.node_a)
                nodes.add(branch.node_b)
        for source in sources:
            if source.enabled:
                nodes.add(source.connection_node)
        if fault_node:
            nodes.add(fault_node)

        # Create buses for all nodes
        bus_index = {}
        for node in sorted(nodes):
            idx = pp.create_bus(net, vn_kv=voltage_kv, name=node)
            bus_index[node] = idx

        # Create external grid sources
        for source in sources:
            if not source.enabled:
                continue
            bus = bus_index[source.connection_node]
            # Calculate short circuit capacity from impedance
            z_magnitude = source.impedance.magnitude
            if z_magnitude <= 1e-12:
                s_sc_mva = float("inf")
            else:
                s_sc_mva = self.Sb / z_magnitude
            rx_ratio = source.impedance.x_over_r
            if math.isinf(rx_ratio):
                rx_max = 1000.0  # Very large value for purely reactive impedance
            elif rx_ratio <= 0:
                rx_max = 0.0
            else:
                rx_max = rx_ratio
            pp.create_ext_grid(
                net,
                bus=bus,
                s_sc_max_mva=s_sc_mva if not math.isinf(s_sc_mva) else 1e12,
                rx_max=rx_max,
                name=source.name,
            )

        # Create network branches as lines
        for branch in passive_branches:
            if not branch.enabled:
                continue
            from_bus = bus_index[branch.node_a]
            to_bus = bus_index[branch.node_b]
            z_base = (voltage_kv ** 2) / self.Sb
            r_ohm = branch.impedance.r_pu * z_base
            x_ohm = branch.impedance.x_pu * z_base
            # Use a very small length since we provide impedance directly
            pp.create_line_from_parameters(
                net,
                from_bus=from_bus,
                to_bus=to_bus,
                length_km=1.0,
                r_ohm_per_km=r_ohm,
                x_ohm_per_km=x_ohm,
                c_nf_per_km=0.0,
                max_i_ka=1e6,
                name=branch.name,
            )

        return net, bus_index

    def calc_network_fault(
        self,
        voltage_kv: float,
        fault_location: str | dict,
        passive_branches: Sequence[NetworkBranch],
        sources: Sequence[FaultSource],
        clearing_time_s: float | None = None,
        *,
        shock_coefficient: float | None = None,
        prompt_for_curve: bool = False,
        requested_curve_times_s: Sequence[float] | None = None,
    ) -> dict[str, object]:
        """Calculate short circuit at any location in the network using pandapower.

        Args:
            fault_location: Can be:
                - str: Existing bus/node name for bus short circuit
                - dict: Line short circuit specification:
                    {"line": "line_name", "distance_pct": 0.5} (0.0 = at from_bus, 1.0 = at to_bus)
        """
        active_sources = [source for source in sources if source.enabled]
        if not active_sources:
            # Return same empty result as parent class
            clearing_time_s = clearing_time_s or default_clearing_time(voltage_kv)
            return {
                "method": "no_active_source",
                "fault_node": str(fault_location) if 'fault_location' in dir() else "unknown",
                "network_branches": [branch.to_dict() for branch in passive_branches if branch.enabled],
                "source_contributions": [],
                "time_series": [],
                "equivalent_impedance": None,
                "voltage_kv": round(voltage_kv, 3),
                "base_current_ka": round(self.calc_base_current(voltage_kv), 3),
                "symmetrical_current_ka": 0.0,
                "breaking_current_ka": 0.0,
                "peak_current_ka": 0.0,
                "full_current_ka": 0.0,
                "short_circuit_capacity_mva": 0.0,
                "thermal_effect_a2s": 0.0,
                "clearing_time_s": round(clearing_time_s, 3),
                "kappa": 0.0,
                "shock_coefficient": 0.0,
            }

        clearing_time_s = clearing_time_s or default_clearing_time(voltage_kv)
        shock_coefficient = float(shock_coefficient or self.default_shock_coefficient)
        curve_times = tuple(requested_curve_times_s or (0.0,))

        # Process fault location
        fault_bus_idx = None
        line_split = None

        if isinstance(fault_location, str):
            # Bus short circuit
            fault_node = fault_location
            net, bus_index = self._build_pp_network(
                voltage_kv=voltage_kv,
                passive_branches=passive_branches,
                sources=sources,
                fault_node=fault_node,
            )
            if fault_node not in bus_index:
                raise ValueError(f"Fault node {fault_node} not found in network.")
            fault_bus_idx = bus_index[fault_node]

        elif isinstance(fault_location, dict):
            # Line short circuit at specified position
            line_name = fault_location.get("line")
            distance_pct = fault_location.get("distance_pct", 0.5)

            # First build base network without fault node
            net, bus_index = self._build_pp_network(
                voltage_kv=voltage_kv,
                passive_branches=passive_branches,
                sources=sources,
            )

            # Find the line to split
            line_idx = None
            for idx, row in net.line.iterrows():
                if row["name"] == line_name:
                    line_idx = idx
                    break
            if line_idx is None:
                raise ValueError(f"Line {line_name} not found in network.")

            # Get line parameters
            line = net.line.loc[line_idx]
            from_bus = line["from_bus"]
            to_bus = line["to_bus"]
            r_total = line["r_ohm_per_km"] * line["length_km"]
            x_total = line["x_ohm_per_km"] * line["length_km"]

            # Split line into two segments
            r1 = r_total * distance_pct
            x1 = x_total * distance_pct
            r2 = r_total * (1 - distance_pct)
            x2 = x_total * (1 - distance_pct)

            # Create new bus for fault point
            fault_bus_idx = pp.create_bus(net, vn_kv=voltage_kv, name=f"fault_point_{line_name}_{int(distance_pct*100)}pct")

            # Remove original line
            net.line.drop(line_idx, inplace=True)

            # Add two new line segments
            pp.create_line_from_parameters(
                net,
                from_bus=from_bus,
                to_bus=fault_bus_idx,
                length_km=1.0,
                r_ohm_per_km=r1,
                x_ohm_per_km=x1,
                c_nf_per_km=0.0,
                max_i_ka=1e6,
                name=f"{line_name}_segment1",
            )
            pp.create_line_from_parameters(
                net,
                from_bus=fault_bus_idx,
                to_bus=to_bus,
                length_km=1.0,
                r_ohm_per_km=r2,
                x_ohm_per_km=x2,
                c_nf_per_km=0.0,
                max_i_ka=1e6,
                name=f"{line_name}_segment2",
            )
            fault_node = f"Line {line_name} at {int(distance_pct*100)}%"

        else:
            raise ValueError("Invalid fault_location format. Must be str (bus name) or dict (line specification).")

        # Run 3-phase short circuit calculation
        sc.calc_sc(net, fault="3ph", case="max", lv_tol_percent=10)

        # Get results for fault bus
        ikss_ka = float(net.res_bus_sc.loc[fault_bus_idx, "ikss_ka"])

        # Calculate peak current from R/X ratio (IEC 60909 method)
        rk_ohm = float(net.res_bus_sc.loc[fault_bus_idx, "rk_ohm"]) if "rk_ohm" in net.res_bus_sc.columns else 0.0
        xk_ohm = float(net.res_bus_sc.loc[fault_bus_idx, "xk_ohm"]) if "xk_ohm" in net.res_bus_sc.columns else 1.0
        r_over_x = rk_ohm / xk_ohm if abs(xk_ohm) > 1e-12 else 0.0
        kappa = 1.02 + 0.98 * math.exp(-3.0 * r_over_x)
        ip_ka = math.sqrt(2) * kappa * ikss_ka

        # Calculate full current (as per IEC 60909)
        full_current_ka = math.sqrt(1 + 2 * (kappa - 1)**2) * ikss_ka

        # Calculate thermal effect and short circuit capacity
        thermal_effect = (ikss_ka * 1000) **2 * clearing_time_s
        short_circuit_capacity = math.sqrt(3) * voltage_kv * ikss_ka

        # Calculate equivalent impedance
        ib = self.calc_base_current(voltage_kv)
        z_magnitude = ib / ikss_ka if ikss_ka > 1e-12 else 0.0
        # Calculate equivalent R/X from source contributions
        total_r = 0.0
        total_x = 0.0
        for source in active_sources:
            if source.impedance.magnitude > 1e-12:
                # This is an approximation - for precise R/X we would need branch current contributions
                total_r += source.impedance.r_pu
                total_x += source.impedance.x_pu
        equivalent_impedance = PerUnitImpedance.from_magnitude(z_magnitude, x_over_r=total_x/total_r if total_r > 1e-12 else 10.0)

        # Build source contributions (simplified for now)
        source_contributions = []
        for source in active_sources:
            transfer = self.calc_source_transfer_impedance(
                fault_node=fault_node,
                passive_branches=passive_branches,
                sources=active_sources,
                source_name=source.name,
            )
            transfer_impedance = transfer["transfer_impedance"]
            x_sigma_pu = transfer_impedance.magnitude

            source_type = str(source.source_type or "finite").strip().lower()
            if source_type in {"infinite", "infinite_source", "system_infinite"}:
                source_base_current = self.calc_base_current(voltage_kv)
                x_js = None
            else:
                if source.source_capacity_mva is None or source.source_capacity_mva <= 0:
                    raise ValueError(f"Finite source {source.name} must provide source_capacity_mva > 0.")
                source_base_current = self.calc_source_base_current(float(source.source_capacity_mva), voltage_kv)
                x_js = x_sigma_pu * float(source.source_capacity_mva) / self.Sb

            initial_i_star = None
            if source_type in {"infinite", "infinite_source", "system_infinite"}:
                initial_i_star = 1.0 / x_sigma_pu
            else:
                initial_i_star = self._resolve_i_star(
                    source=source,
                    x_sigma_pu=x_sigma_pu,
                    time_point=0.0,
                    prompt_for_curve=prompt_for_curve,
                )
            initial_current_ka = initial_i_star * source_base_current

            # Build time series
            time_series = []
            for time_point in curve_times:
                if source_type in {"infinite", "infinite_source", "system_infinite"}:
                    i_star_value = 1.0 / x_sigma_pu
                else:
                    i_star_value = self._resolve_i_star(
                        source=source,
                        x_sigma_pu=x_sigma_pu,
                        time_point=time_point,
                        prompt_for_curve=prompt_for_curve,
                    )
                current_ka = i_star_value * source_base_current
                time_series.append(
                    {
                        "time_s": round(float(time_point), 3),
                        "i_star": round(i_star_value, 6),
                        "current_ka": round(current_ka, 6),
                    }
                )

            source_contributions.append(
                {
                    "name": source.name,
                    "connection_node": source.connection_node,
                    "source_type": source.source_type,
                    "source_capacity_mva": None if source.source_capacity_mva is None else round(float(source.source_capacity_mva), 3),
                    "curve_type": source.curve_type,
                    "source_base_current_ka": round(source_base_current, 6),
                    "transfer_impedance": transfer_impedance.to_dict(),
                    "x_sigma_pu": round(x_sigma_pu, 6),
                    "x_js": None if x_js is None else round(x_js, 6),
                    "i_star": round(initial_i_star, 6),
                    "symmetrical_current_ka": round(initial_current_ka, 6),
                    "time_series": time_series,
                }
            )

        # Build time series totals
        time_series_totals = []
        for time_point in curve_times:
            time_key = self._normalize_time_key(time_point)
            total_current = 0.0
            for contribution in source_contributions:
                matched = next(
                    (
                        point
                        for point in contribution["time_series"]
                        if self._normalize_time_key(point["time_s"]) == time_key
                    ),
                    None,
                )
                if matched:
                    total_current += float(matched["current_ka"])
            time_series_totals.append(
                {
                    "time_s": round(float(time_point), 3),
                    "symmetrical_current_ka": round(total_current, 6),
                }
            )

        # Build result using parent's _build_fault_result method to ensure format compatibility
        result = self._build_fault_result(
            voltage_kv=voltage_kv,
            equivalent_impedance=equivalent_impedance,
            symmetrical_current_ka=ikss_ka,
            clearing_time_s=clearing_time_s,
            peak_current_ka=ip_ka,
            full_current_ka=full_current_ka,
            short_circuit_capacity_mva=short_circuit_capacity,
            thermal_effect_a2s=thermal_effect,
            kappa=kappa,
            method="pandapower_3ph_short_circuit",
            shock_coefficient=shock_coefficient,
        )
        result["fault_node"] = fault_node
        result["network_branches"] = [branch.to_dict() for branch in passive_branches if branch.enabled]
        result["source_contributions"] = source_contributions
        result["time_series"] = time_series_totals
        result["requested_curve_times_s"] = [round(float(item), 3) for item in curve_times]
        return result

    def calc_bus_fault(
        self,
        wiring_type: str,
        voltage_kv: float,
        branches: Iterable[BranchContribution],
        fault_section: str = "common",
        operating_mode: str = "normal",
        clearing_time_s: float | None = None,
        *,
        use_operation_curve: bool = False,
        sn_total_mva: float | None = None,
        curve_type: str | None = None,
        shock_coefficient: float | None = None,
    ) -> dict[str, object]:
        """Calculate bus fault using pandapower short circuit module."""
        active_branches = self.active_branches_for_fault(
            wiring_type=wiring_type,
            branches=branches,
            fault_section=fault_section,
            operating_mode=operating_mode,
        )
        if not active_branches:
            clearing_time_s = clearing_time_s or default_clearing_time(voltage_kv)
            return {
                "wiring_type": wiring_type,
                "fault_section": fault_section,
                "operating_mode": operating_mode,
                "active_branches": [],
                "fault": {
                    "method": "no_active_source",
                    "equivalent_impedance": None,
                    "voltage_kv": round(voltage_kv, 3),
                    "base_current_ka": round(self.calc_base_current(voltage_kv), 3),
                    "symmetrical_current_ka": 0.0,
                    "breaking_current_ka": 0.0,
                    "peak_current_ka": 0.0,
                    "full_current_ka": 0.0,
                    "short_circuit_capacity_mva": 0.0,
                    "thermal_effect_a2s": 0.0,
                    "clearing_time_s": round(clearing_time_s, 3),
                    "kappa": 0.0,
                    "x_sigma_pu": 0.0,
                    "x_js": 0.0,
                    "i_star": 0.0,
                    "sn_total_mva": 0.0,
                },
            }

        # Convert BranchContribution to FaultSource and NetworkBranch for network calculation
        sources = []
        passive_branches = []
        for idx, branch in enumerate(active_branches):
            # Each branch contribution is a source connected directly to the fault bus
            sources.append(
                FaultSource(
                    name=branch.name,
                    connection_node="fault_bus",
                    impedance=branch.impedance,
                    source_type="finite" if branch.source_capacity_mva else "infinite",
                    source_capacity_mva=branch.source_capacity_mva,
                    curve_type=branch.curve_type,
                )
            )

        # Calculate fault using network fault method
        fault_result = self.calc_network_fault(
            voltage_kv=voltage_kv,
            fault_location="fault_bus",
            passive_branches=passive_branches,
            sources=sources,
            clearing_time_s=clearing_time_s,
            shock_coefficient=shock_coefficient,
        )

        # Adjust method name and add bus fault specific fields
        fault_result["method"] = "pandapower_bus_fault"

        return {
            "wiring_type": wiring_type,
            "fault_section": fault_section,
            "operating_mode": operating_mode,
            "active_branches": [branch.to_dict() for branch in active_branches],
            "fault": fault_result,
        }

    def active_branches_for_fault(
        self,
        wiring_type: str,
        branches: Iterable[BranchContribution],
        fault_section: str = "common",
        operating_mode: str = "normal",
    ) -> list[BranchContribution]:
        active = [branch for branch in branches if branch.enabled]
        if not active:
            return []

        # 解析运行方式前缀：max_xxx / min_xxx / xxx
        mode_prefix = None
        base_mode = operating_mode
        if operating_mode.startswith("max_") or operating_mode.startswith("min_"):
            mode_prefix, base_mode = operating_mode.split("_", 1)

        # 过滤基础运行方式下的可用支路
        if wiring_type == "single_bus":
            mode_filtered = active
        elif wiring_type in {"single_bus_sectionalized", "double_bus", "double_bus_bypass"}:
            sectionalized_modes = {"split", "section_outage", "bus_transfer_isolated"}
            if base_mode in sectionalized_modes and fault_section != "common":
                mode_filtered = [
                    branch
                    for branch in active
                    if branch.section in {fault_section, "common"}
                ]
            else:
                mode_filtered = active
        elif wiring_type in {"inner_bridge", "outer_bridge"}:
            if base_mode == "bridge_open" and fault_section != "common":
                mode_filtered = [
                    branch
                    for branch in active
                    if branch.section in {fault_section, "common"}
                ]
            else:
                mode_filtered = active
        else:
            mode_filtered = active

        # 应用最大/最小运行方式的电源策略
        if mode_prefix == "max":
            # 最大运行方式：投入所有可用电源，无额外过滤
            return mode_filtered
        elif mode_prefix == "min":
            # 最小运行方式：仅保留容量最大的一个电源，模拟最小运行场景
            source_branches = [b for b in mode_filtered if b.kind == "source" and b.source_capacity_mva is not None]
            non_source_branches = [b for b in mode_filtered if b.kind != "source"]
            if not source_branches:
                return mode_filtered
            # 按容量降序，保留最大的一个
            source_branches_sorted = sorted(source_branches, key=lambda x: (x.source_capacity_mva or 0.0), reverse=True)
            min_mode_branches = [source_branches_sorted[0]] + non_source_branches
            return min_mode_branches

        return mode_filtered

    def _normalize_time_key(self, time_point: float | str) -> str:
        if isinstance(time_point, str):
            text = time_point.strip().lower()
            return text if text.endswith("s") else f"{text}s"
        numeric = float(time_point)
        if abs(numeric - round(numeric)) < 1e-9:
            return f"{int(round(numeric))}s"
        return f"{numeric:g}s"

    def _resolve_i_star(
        self,
        source: FaultSource,
        x_sigma_pu: float,
        time_point: float | str = 0.0,
        *,
        prompt_for_curve: bool = False,
    ) -> float:
        source_type = str(source.source_type or "finite").strip().lower()
        curve_type = str(source.curve_type or "user_provided").strip().lower()
        time_key = self._normalize_time_key(time_point)

        if source.i_star_by_time and time_key in source.i_star_by_time:
            return float(source.i_star_by_time[time_key])
        if time_key == "0s" and source.i_star_0s is not None:
            return float(source.i_star_0s)

        if source_type in {"infinite", "infinite_source", "system_infinite"} or curve_type in {
            "infinite",
            "infinite_source",
            "infinite_power_source",
            "system_infinite",
        }:
            return 1.0 / x_sigma_pu

        if prompt_for_curve:
            x_js = x_sigma_pu * float(source.source_capacity_mva or 0.0) / self.Sb
            cache_key = (source.name, time_key, round(x_js, 6), curve_type)
            if cache_key in self._curve_prompt_cache:
                return self._curve_prompt_cache[cache_key]
            prompt = (
                f"Enter operation-curve i* for source '{source.name}' at {time_key} "
                f"(curve={source.curve_type}, x_js={x_js:.6f}): "
            )
            user_input = input(prompt).strip()
            if not user_input:
                raise ValueError(f"No operation-curve i* provided for source {source.name} at {time_key}.")
            self._curve_prompt_cache[cache_key] = float(user_input)
            return self._curve_prompt_cache[cache_key]

        raise ValueError(
            "Operation-curve i* is required from the user for finite source "
            f"{source.name} at {time_key}. Provide i_star_0s or i_star_by_time in the input."
        )

    def calc_source_transfer_impedance(
        self,
        fault_node: str,
        passive_branches: Sequence[NetworkBranch],
        sources: Sequence[FaultSource],
        source_name: str,
    ) -> dict[str, object]:
        active_sources = [source for source in sources if source.enabled]
        if not any(source.name == source_name for source in active_sources):
            raise ValueError(f"Source {source_name} is not present in the active network.")

        augmented_branches = [branch for branch in passive_branches if branch.enabled]
        fixed_voltages: dict[str, complex] = {fault_node: 0.0}
        for source in active_sources:
            emf_node = f"emf::{source.name}"
            fixed_voltages[emf_node] = 1.0 if source.name == source_name else 0.0
            augmented_branches.append(
                NetworkBranch(
                    name=f"source_branch::{source.name}",
                    node_a=source.connection_node,
                    node_b=emf_node,
                    impedance=source.impedance,
                )
            )

        voltages = self.solve_network_voltages(augmented_branches, fixed_voltages=fixed_voltages)
        source = next(item for item in active_sources if item.name == source_name)
        connection_voltage = voltages.get(source.connection_node, 0.0)
        source_current = (complex(fixed_voltages[f"emf::{source.name}"]) - connection_voltage) / source.impedance.complex_value
        transfer_impedance = PerUnitImpedance.from_complex(1.0 / source_current) if abs(source_current) > 1e-12 else PerUnitImpedance(r_pu=float("inf"), x_pu=0.0)

        return {
            "source": source,
            "source_current_pu": source_current,
            "transfer_impedance": transfer_impedance,
            "node_voltages": {
                node: complex(value)
                for node, value in voltages.items()
            },
        }

    def solve_network_voltages(
        self,
        branches: Sequence[NetworkBranch],
        fixed_voltages: dict[str, complex],
    ) -> dict[str, complex]:
        active_branches = [branch for branch in branches if branch.enabled]
        nodes = sorted(
            {
                branch.node_a
                for branch in active_branches
            }
            | {
                branch.node_b
                for branch in active_branches
            }
        )
        unknown_nodes = [node for node in nodes if node not in fixed_voltages]
        if not unknown_nodes:
            return {node: complex(value) for node, value in fixed_voltages.items()}

        index_by_node = {node: index for index, node in enumerate(unknown_nodes)}
        size = len(unknown_nodes)
        matrix = [[0j for _ in range(size)] for _ in range(size)]
        rhs = [0j for _ in range(size)]

        for branch in active_branches:
            impedance = branch.impedance.complex_value
            if abs(impedance) < 1e-12:
                raise ValueError(f"Network branch {branch.name} has zero impedance. Use a very small positive value instead.")
            admittance = 1.0 / impedance
            node_a_known = branch.node_a in fixed_voltages
            node_b_known = branch.node_b in fixed_voltages

            if not node_a_known:
                row_a = index_by_node[branch.node_a]
                matrix[row_a][row_a] += admittance
            if not node_b_known:
                row_b = index_by_node[branch.node_b]
                matrix[row_b][row_b] += admittance
            if not node_a_known and not node_b_known:
                row_a = index_by_node[branch.node_a]
                row_b = index_by_node[branch.node_b]
                matrix[row_a][row_b] -= admittance
                matrix[row_b][row_a] -= admittance
            elif not node_a_known and node_b_known:
                row_a = index_by_node[branch.node_a]
                rhs[row_a] += admittance * complex(fixed_voltages[branch.node_b])
            elif node_a_known and not node_b_known:
                row_b = index_by_node[branch.node_b]
                rhs[row_b] += admittance * complex(fixed_voltages[branch.node_a])

        solution = self._solve_linear_system(matrix, rhs)
        result = {node: complex(value) for node, value in fixed_voltages.items()}
        for node, value in zip(unknown_nodes, solution):
            result[node] = value
        return result

    def _solve_linear_system(self, matrix: list[list[complex]], rhs: list[complex]) -> list[complex]:
        size = len(matrix)
        if size == 0:
            return []

        augmented = [
            [complex(value) for value in row] + [complex(rhs[index])]
            for index, row in enumerate(matrix)
        ]

        for pivot_index in range(size):
            pivot_row = max(
                range(pivot_index, size),
                key=lambda row_index: abs(augmented[row_index][pivot_index]),
            )
            if abs(augmented[pivot_row][pivot_index]) < 1e-12:
                raise ValueError("Fault network matrix is singular. Check topology connectivity and impedances.")
            if pivot_row != pivot_index:
                augmented[pivot_index], augmented[pivot_row] = augmented[pivot_row], augmented[pivot_index]

            pivot = augmented[pivot_index][pivot_index]
            for column in range(pivot_index, size + 1):
                augmented[pivot_index][column] /= pivot

            for row_index in range(size):
                if row_index == pivot_index:
                    continue
                factor = augmented[row_index][pivot_index]
                if abs(factor) < 1e-12:
                    continue
                for column in range(pivot_index, size + 1):
                    augmented[row_index][column] -= factor * augmented[pivot_index][column]

        return [augmented[index][size] for index in range(size)]

    def lookup_operation_curve(self, x_js: float, curve_type: str = "turbine_finite") -> float:
        curve = str(curve_type or "turbine_finite").strip().lower()
        if x_js <= 0:
            raise ValueError("x_js must be positive for operation curve lookup.")

        if curve in {"infinite", "infinite_source", "infinite_power_source", "system_infinite"}:
            return 1.0 / x_js
        if curve in {"turbine_finite", "finite_source", "turbo_generator"}:
            return _interpolate_curve(TURBINE_FINITE_SOURCE_CURVE_0S, x_js)
        raise ValueError(f"Unsupported operation curve type: {curve_type}")

    def _build_fault_result(
        self,
        *,
        voltage_kv: float,
        equivalent_impedance: PerUnitImpedance,
        symmetrical_current_ka: float,
        clearing_time_s: float,
        peak_current_ka: float,
        full_current_ka: float,
        short_circuit_capacity_mva: float,
        thermal_effect_a2s: float,
        kappa: float,
        method: str,
        x_sigma_pu: float | None = None,
        x_js: float | None = None,
        i_star: float | None = None,
        sn_total_mva: float | None = None,
        source_base_current_ka: float | None = None,
        curve_type: str | None = None,
        shock_coefficient: float | None = None,
    ) -> dict[str, object]:
        return {
            "method": method,
            "equivalent_impedance": equivalent_impedance.to_dict(),
            "voltage_kv": round(voltage_kv, 3),
            "base_current_ka": round(self.calc_base_current(voltage_kv), 3),
            "source_base_current_ka": None if source_base_current_ka is None else round(source_base_current_ka, 3),
            "symmetrical_current_ka": round(symmetrical_current_ka, 3),
            "breaking_current_ka": round(symmetrical_current_ka, 3),
            "peak_current_ka": round(peak_current_ka, 3),
            "full_current_ka": round(full_current_ka, 3),
            "short_circuit_capacity_mva": round(short_circuit_capacity_mva, 3),
            "thermal_effect_a2s": round(thermal_effect_a2s, 3),
            "clearing_time_s": round(clearing_time_s, 3),
            "kappa": round(kappa, 3),
            "shock_coefficient": None if shock_coefficient is None else round(shock_coefficient, 3),
            "x_sigma_pu": None if x_sigma_pu is None else round(x_sigma_pu, 6),
            "x_js": None if x_js is None else round(x_js, 6),
            "i_star": None if i_star is None else round(i_star, 6),
            "sn_total_mva": None if sn_total_mva is None else round(sn_total_mva, 3),
            "curve_type": curve_type,
        }

    def fault_from_xjs(
        self,
        x_sigma_pu: float,
        sn_total_mva: float,
        voltage_kv: float,
        curve_type: str = "turbine_finite",
        i_star: float | None = None,
        clearing_time_s: float | None = None,
        shock_coefficient: float | None = None,
    ) -> dict[str, object]:
        """Sample-style workflow: x_sigma -> x_js -> operation curve i* -> named currents."""

        if x_sigma_pu <= 0:
            raise ValueError("x_sigma_pu must be positive.")
        if sn_total_mva <= 0:
            raise ValueError("sn_total_mva must be positive.")

        clearing_time_s = clearing_time_s or default_clearing_time(voltage_kv)
        shock_coefficient = float(shock_coefficient or self.default_shock_coefficient)

        x_js = x_sigma_pu * sn_total_mva / self.Sb
        i_star_value = float(i_star if i_star is not None else self.lookup_operation_curve(x_js, curve_type=curve_type))
        source_base_current = self.calc_source_base_current(sn_total_mva, voltage_kv)
        i_k = i_star_value * source_base_current
        i_peak = math.sqrt(2.0) * shock_coefficient * i_k
        i_full = math.sqrt(1.0 + 2.0 * (shock_coefficient - 1.0) ** 2) * i_k
        q_k = (i_k * 1000.0) ** 2 * clearing_time_s
        s_k = math.sqrt(3.0) * voltage_kv * i_k

        z_magnitude = self.calc_base_current(voltage_kv) / i_k if i_k > 0 else 0.0
        equivalent_impedance = PerUnitImpedance(r_pu=0.0, x_pu=z_magnitude)

        return self._build_fault_result(
            voltage_kv=voltage_kv,
            equivalent_impedance=equivalent_impedance,
            symmetrical_current_ka=i_k,
            clearing_time_s=clearing_time_s,
            peak_current_ka=i_peak,
            full_current_ka=i_full,
            short_circuit_capacity_mva=s_k,
            thermal_effect_a2s=q_k,
            kappa=shock_coefficient,
            method="operation_curve",
            x_sigma_pu=x_sigma_pu,
            x_js=x_js,
            i_star=i_star_value,
            sn_total_mva=sn_total_mva,
            source_base_current_ka=source_base_current,
            curve_type=curve_type,
            shock_coefficient=shock_coefficient,
        )

    def fault_from_impedance(
        self,
        equivalent_impedance: PerUnitImpedance,
        voltage_kv: float,
        clearing_time_s: float | None = None,
        *,
        use_operation_curve: bool = False,
        sn_total_mva: float | None = None,
        curve_type: str = "turbine_finite",
        i_star: float | None = None,
        shock_coefficient: float | None = None,
    ) -> dict[str, object]:
        clearing_time_s = clearing_time_s or default_clearing_time(voltage_kv)
        z_magnitude = equivalent_impedance.magnitude
        if z_magnitude <= 0:
            raise ValueError("Equivalent impedance magnitude must be positive.")

        if use_operation_curve:
            if not sn_total_mva or sn_total_mva <= 0:
                raise ValueError("sn_total_mva must be provided when use_operation_curve=True.")
            return self.fault_from_xjs(
                x_sigma_pu=z_magnitude,
                sn_total_mva=sn_total_mva,
                voltage_kv=voltage_kv,
                curve_type=curve_type,
                i_star=i_star,
                clearing_time_s=clearing_time_s,
                shock_coefficient=shock_coefficient,
            )

        ib = self.calc_base_current(voltage_kv)
        i_k = ib / z_magnitude
        x_over_r = equivalent_impedance.x_over_r
        r_over_x = 0.0 if math.isinf(x_over_r) else (1.0 / x_over_r if x_over_r else 0.0)
        kappa = 1.02 + 0.98 * math.exp(-3.0 * r_over_x)
        i_peak = math.sqrt(2.0) * kappa * i_k
        i_full = math.sqrt(1.0 + 2.0 * (kappa - 1.0) ** 2) * i_k
        q_k = (i_k * 1000.0) ** 2 * clearing_time_s
        s_k = math.sqrt(3.0) * voltage_kv * i_k

        return self._build_fault_result(
            voltage_kv=voltage_kv,
            equivalent_impedance=equivalent_impedance,
            symmetrical_current_ka=i_k,
            clearing_time_s=clearing_time_s,
            peak_current_ka=i_peak,
            full_current_ka=i_full,
            short_circuit_capacity_mva=s_k,
            thermal_effect_a2s=q_k,
            kappa=kappa,
            method="equivalent_impedance",
        )

    def fault_from_current_level(
        self,
        voltage_kv: float,
        short_circuit_current_ka: float,
        x_over_r: float = 10.0,
        clearing_time_s: float | None = None,
    ) -> dict[str, object]:
        base_current = self.calc_base_current(voltage_kv)
        magnitude = base_current / short_circuit_current_ka
        impedance = PerUnitImpedance.from_magnitude(magnitude, x_over_r=x_over_r)
        result = self.fault_from_impedance(
            impedance,
            voltage_kv=voltage_kv,
            clearing_time_s=clearing_time_s,
        )
        result["input_short_circuit_current_ka"] = round(short_circuit_current_ka, 3)
        return result

    def calc_short_circuit_current(
        self,
        x_js: float,
        sn_total: float,
        uav: float,
        x_over_r: float = 10.0,
        clearing_time_s: float | None = None,
        *,
        method: str = "operation_curve",
        curve_type: str = "turbine_finite",
        i_star: float | None = None,
        shock_coefficient: float | None = None,
    ) -> dict[str, object]:
        if method == "operation_curve":
            x_sigma = x_js * self.Sb / sn_total
            return self.fault_from_xjs(
                x_sigma_pu=x_sigma,
                sn_total_mva=sn_total,
                voltage_kv=uav,
                curve_type=curve_type,
                i_star=i_star,
                clearing_time_s=clearing_time_s,
                shock_coefficient=shock_coefficient,
            )

        base_current = sn_total / (math.sqrt(3.0) * uav)
        i_k = base_current / x_js
        magnitude = self.calc_base_current(uav) / i_k
        impedance = PerUnitImpedance.from_magnitude(magnitude, x_over_r=x_over_r)
        result = self.fault_from_impedance(
            impedance,
            voltage_kv=uav,
            clearing_time_s=clearing_time_s,
        )
        result["x_js"] = round(x_js, 6)
        result["sn_total_mva"] = round(sn_total, 3)
        return result

    def calc_transfer_reactance_pair(self, xs: float, xk: float, xt: float) -> dict[str, float]:
        """Transfer reactance pair from the sample's two-source equivalent formula."""

        if xs <= 0 or xk <= 0:
            raise ValueError("xs and xk must be positive for transfer reactance calculation.")
        numerator = xs * xk + xs * xt + xt * xk
        return {
            "x_s_prime": numerator / xk,
            "x_k_prime": numerator / xs,
        }

    def calc_thermal_effect(self, i_k: float, t_k: float) -> float:
        return (i_k**2) * t_k * 1e6

def get_calculator(*args, **kwargs) -> ShortCircuitCalculator:
    """Get short circuit calculator (now uses pandapower exclusively)."""
    return ShortCircuitCalculator(*args, **kwargs)

if __name__ == "__main__":
    print(json.dumps(example_calculation(), ensure_ascii=False, indent=2))
