#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""35kV变电站完整电气设计计算脚本"""

from __future__ import annotations
import json
import math
import sys
import os

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

from equipment_db import EquipmentDatabase
from calc_load import LoadCalculator
from calc_short_circuit import (
    ShortCircuitCalculator,
    PerUnitImpedance,
    BranchContribution,
    FaultSource,
    NetworkBranch,
    default_clearing_time,
    get_calculator,
)
from generate_main_wiring import generate_main_wiring, select_wiring_type
from select_equipment import EquipmentSelector

# ============================================================
# 一、设计输入参数
# ============================================================
design_input = {
    "substation_type": "35/10kV",
    "transformer": {
        "final_count": 2,
        "final_capacity_mva": 8.0,
    },
    "voltage_35kv": {
        "level_kv": 35.0,
        "phase1_circuits": 1,
        "final_circuits": 4,
        "supply_distance_km": 7.0,
        "load_mw": 10.0,
    },
    "voltage_10kv": {
        "level_kv": 10.0,
        "phase1_circuits": 3,
        "final_circuits": 8,
        "supply_distance_km": 4.0,
        "load_mw": 13.0,
    },
    "source": {
        "distance_km": 71.0,
        "system_capacity_mva": 100.0,
        "system_reactance_pu": 1.33,
        "max_utilization_hours": 5200,
        "line_reactance_per_km": 0.4,
    },
    "power_factor": 0.8,
    "load_class": "I_II",
    "station_service_rate": 0.0018,
    "conditions": {
        "max_temp_c": 37.0,
        "min_temp_c": -7.0,
        "avg_hot_month_temp_c": 27.0,
        "lightning_days_per_year": 120,
        "soil_resistivity_ohm_m": 1100.0,
        "seismic_intensity": "below 7",
        "altitude_m": 1800.0,
    },
}

# ============================================================
# 二、负荷与容量计算
# ============================================================
print("=" * 70)
print("二、负荷与容量计算")
print("=" * 70)

catalog = EquipmentDatabase()
load_calc = LoadCalculator(catalog)

# 总负荷
p_35kv = design_input["voltage_35kv"]["load_mw"]
p_10kv = design_input["voltage_10kv"]["load_mw"]
p_total = p_35kv + p_10kv  # 23 MW
cos_phi = design_input["power_factor"]

# 变压器仅负担10kV侧负荷
# 35kV侧负荷直接通过35kV母线送出，不经过变压器
p_transformer = p_10kv  # 13 MW

# 站用电负荷（按站用电率估算）
station_load_kw = p_transformer * 1000 * design_input["station_service_rate"]  # 23.4 kW

# 最大综合负荷（变压器侧）
loads_transformer = [{"name": "10kV_load", "power": p_transformer, "class": "I/II"}]
s_max = load_calc.calc_max_comprehensive_load(loads_transformer, cos_phi=cos_phi, kt=0.9, loss_percent=4)

print(f"\n1) 变压器侧负荷:")
print(f"   10kV侧有功负荷 P = {p_transformer} MW")
print(f"   功率因数 cosφ = {cos_phi}")
print(f"   同时系数 Kt = 0.9, 线损率 = 4%")
print(f"   最大综合负荷 S_max = 0.9 × ({p_transformer}/{cos_phi}) × 1.04 = {s_max:.2f} MVA")

# 主变容量校验
n_transformer = design_input["transformer"]["final_count"]
sn_each = design_input["transformer"]["final_capacity_mva"]

# N-1校验：一台变压器停运时，另一台应承担全部I、II类负荷
# I/II类负荷 = 100% 的10kV负荷
class_i_ii_mva = p_transformer / cos_phi  # 16.25 MVA
k_factor = 0.6

sn_by_max = k_factor * s_max / (n_transformer - 1)
sn_by_class = class_i_ii_mva / (n_transformer - 1)
sn_required = max(sn_by_max, sn_by_class)

print(f"\n2) 主变容量校验:")
print(f"   设计容量: {n_transformer}×{sn_each} MVA")
print(f"   N-1校验:")
print(f"     按最大负荷: Sn ≥ K×Smax/(N-1) = {k_factor}×{s_max:.2f}/1 = {sn_by_max:.2f} MVA")
print(f"     按I/II类负荷: Sn ≥ S_I-II/(N-1) = {class_i_ii_mva:.2f}/1 = {sn_by_class:.2f} MVA")
print(f"     要求最小容量: Sn ≥ {sn_required:.2f} MVA")

if sn_each >= sn_required:
    print(f"   [OK] {sn_each} MVA >= {sn_required:.2f} MVA, N-1 OK")
else:
    print(f"   [!!] {sn_each} MVA < {sn_required:.2f} MVA, N-1 NOT OK")
    print(f"     注: 实际设计中可在N-1时切除部分III类负荷，或允许短时过负荷（1.3倍×{sn_each}={sn_each*1.3:.1f} MVA）")

overload_check = sn_each * 1.3 >= sn_required
overload_str = ">=" if overload_check else "<"
overload_result = "OK" if overload_check else "NOT OK"
print(f"   1.3x overload: {sn_each*1.3:.1f} MVA {overload_str} {sn_required:.2f} MVA -> {overload_result}")

# 变压器总容量
total_transformer_capacity = n_transformer * sn_each
cap_str = ">=" if total_transformer_capacity >= s_max else "<"
print(f"   Total: {total_transformer_capacity} MVA {cap_str} S_max({s_max:.2f} MVA)")

# 数据库选型
transformer_result = load_calc.calc_transformer_capacity(
    s_max=s_max,
    n=n_transformer,
    k_factor=k_factor,
    class_i_ii_load=class_i_ii_mva,
)
print(f"\n3) 数据库推荐主变:")
print(f"   推荐型号: {transformer_result['selected_model']}")
print(f"   推荐容量: {transformer_result['sn_standard']} MVA")

# 站用变选型
station_loads = [
    {"name": "变压器风冷", "power": 3.0, "type": "经常连续"},
    {"name": "蓄电池充电", "power": 4.5, "type": "经常连续"},
    {"name": "照明及生活", "power": 8.0, "type": "经常连续"},
    {"name": "通风空调", "power": 5.0, "type": "经常连续"},
    {"name": "检修电源", "power": 10.0, "type": "不经常、短时"},
]
station_service = load_calc.calc_station_load(station_loads)
station_transformer = load_calc.select_station_transformer(station_service["s_station"])

print(f"\n4) 站用电负荷:")
print(f"   计入负荷功率: {station_service['counted_power_kw']} kW")
print(f"   换算系数法: S站 = K×ΣP = {station_service['s_station']} kVA")
print(f"   推荐站用变: {station_transformer.get('model', 'N/A')}")
print(f"   容量: {station_transformer.get('rated_capacity', 'N/A')}")

# 无功补偿
reactive_comp = load_calc.calc_reactive_power_compensation(sn_each, compensation_ratio=0.15, groups=2)
print(f"\n5) 无功补偿:")
if reactive_comp:
    print(f"   变压器容量: {sn_each} MVA")
    print(f"   补偿比例: {reactive_comp['compensation_ratio_target']}%")
    print(f"   总补偿容量: {reactive_comp['total_compensation_required']:.0f} kvar")
    print(f"   推荐型号: {reactive_comp['selected_model']}")
    print(f"   实际补偿: {reactive_comp['actual_total_compensation']:.0f} kvar")
else:
    print("   数据库中无匹配的电容器组")

# ============================================================
# 三、短路电流计算
# ============================================================
print("\n" + "=" * 70)
print("三、短路电流计算")
print("=" * 70)

sc_calc = get_calculator(base_power=100.0)

# 基准值
Sb = 100.0  # MVA
U_av_35 = 37.0  # kV (35kV平均电压)
U_av_10 = 10.5  # kV (10kV平均电压)

# 系统阻抗 (标幺值，基准100MVA)
x_system = design_input["source"]["system_reactance_pu"]
z_system = PerUnitImpedance(r_pu=0.0, x_pu=x_system)

# 电源线路阻抗 (71km, 0.4Ω/km)
x_line_per_km = design_input["source"]["line_reactance_per_km"]
source_distance = design_input["source"]["distance_km"]
z_source_line = sc_calc.calc_line_impedance(
    x1_ohm_per_km=x_line_per_km,
    length_km=source_distance,
    voltage_kv=U_av_35,
)

# 变压器阻抗 (8MVA, uk%约7%)
uk_percent = 7.0
z_transformer = sc_calc.calc_transformer_impedance(uk_percent=uk_percent, sn_mva=sn_each, x_over_r=20.0)

# 两台变并联阻抗
z_transformer_parallel = sc_calc.parallel_impedance(z_transformer, z_transformer)

print(f"\n基准容量 Sb = {Sb} MVA")
print(f"基准电压: 35kV侧 Uav = {U_av_35} kV, 10kV侧 Uav = {U_av_10} kV")
print(f"\n系统阻抗 X*s = {x_system} pu (基准{Sb}MVA)")
print(f"电源线路阻抗 X*L = {z_source_line.x_pu:.4f} pu ({source_distance}km, {x_line_per_km}Ω/km)")
print(f"变压器阻抗 X*T = {z_transformer.x_pu:.4f} pu (uk={uk_percent}%, Sn={sn_each}MVA)")

# 使用多电压等级短路计算方法（自动处理各侧基准电流）
sc_result = sc_calc.calc_substation_short_circuit(
    voltage_levels={"35kV": U_av_35, "10kV": U_av_10},
    fault_points=[
        {
            "name": "d1",
            "voltage_level": "35kV",
            "label": "35kV母线三相短路",
            "impedance_chain": [
                {"name": "系统阻抗", "impedance": z_system, "detail": f"X*s={x_system}, 以{Sb}MVA为基准"},
                {"name": "电源线路阻抗", "impedance": z_source_line, "detail": f"{source_distance}km, {x_line_per_km}Ω/km"},
            ],
        },
        {
            "name": "d2",
            "voltage_level": "10kV",
            "label": "10kV母线三相短路（单台变）",
            "impedance_chain": [
                {"name": "系统阻抗", "impedance": z_system, "detail": f"X*s={x_system}"},
                {"name": "电源线路阻抗", "impedance": z_source_line, "detail": f"{source_distance}km"},
                {"name": "变压器阻抗", "impedance": z_transformer, "detail": f"uk={uk_percent}%, Sn={sn_each}MVA"},
            ],
        },
        {
            "name": "d2'",
            "voltage_level": "10kV",
            "label": "10kV母线三相短路（两台变并联）",
            "impedance_chain": [
                {"name": "系统阻抗", "impedance": z_system, "detail": f"X*s={x_system}"},
                {"name": "电源线路阻抗", "impedance": z_source_line, "detail": f"{source_distance}km"},
                {"name": "变压器阻抗(两台并联)", "impedance": z_transformer_parallel, "detail": f"uk={uk_percent}%, 两台{sn_each}MVA并联"},
            ],
        },
    ],
)

# 打印详细计算过程
for r in sc_result["results"]:
    detail = r["calculation_detail"]
    print(f"\n--- {r['label']} ---")
    print(f"  电压等级: {detail['voltage_level']} (Uav={detail['average_voltage_kv']}kV)")
    print(f"  等值阻抗: |Z*Σ| = {detail['x_sigma_formula']}")
    print(f"  基准电流: Ib = {detail['base_current_formula']}")
    print(f"  对称短路电流: I\" = {detail['symmetrical_formula']}")
    print(f"  冲击电流: ich = {detail['peak_formula']}")
    print(f"  全电流: Ich = {detail['full_formula']}")
    print(f"  短路容量: Sd = {detail['capacity_formula']}")
    print(f"  热效应: Qk = {detail['thermal_formula']}")

# 打印汇总表
print(f"\n--- 短路电流计算汇总 ---")
print(ShortCircuitCalculator.format_sc_summary_table(sc_result))

# 提取各侧短路电流用于设备选型
# 35kV侧: d1点
r_d1 = next(r for r in sc_result["results"] if r["fault_point"] == "d1")
I_sc_35 = r_d1["symmetrical_current_ka"]
I_peak_35 = r_d1["peak_current_ka"]
Q_35 = r_d1["thermal_effect_a2s"]

# 10kV侧: d2'点(两台变并联, 最大短路电流)
r_d2p = next(r for r in sc_result["results"] if r["fault_point"] == "d2'")
I_sc_10 = r_d2p["symmetrical_current_ka"]
I_peak_10 = r_d2p["peak_current_ka"]
Q_10 = r_d2p["thermal_effect_a2s"]

# ============================================================
# 四、主接线方案
# ============================================================
print("\n" + "=" * 70)
print("四、主接线方案")
print("=" * 70)

# 35kV侧主接线
wiring_35kv = select_wiring_type(
    voltage_level=35.0,
    circuits=4,
    reliability="important",
    transformer_count=2,
    through_power=True,
    line_length="medium",
)
print(f"\n1) 35kV侧主接线:")
print(f"   电压等级: 35kV, 出线回路数: 4回")
print(f"   接线方式: {wiring_35kv['wiring_type']}")
print(f"   说明: {wiring_35kv['description']}")

# 10kV侧主接线
wiring_10kv = select_wiring_type(
    voltage_level=10.0,
    circuits=8,
    reliability="important",
    transformer_count=2,
    through_power=False,
    line_length="medium",
)
print(f"\n2) 10kV侧主接线:")
print(f"   电压等级: 10kV, 出线回路数: 8回")
print(f"   接线方式: {wiring_10kv['wiring_type']}")
print(f"   说明: {wiring_10kv['description']}")

# ============================================================
# 五、设备选型
# ============================================================
print("\n" + "=" * 70)
print("五、设备选型")
print("=" * 70)

selector = EquipmentSelector(catalog)

# 各侧最大工作电流
print(f"\n--- 各侧最大工作电流计算 ---")

# 35kV侧
I_35kv_total = 1.05 * total_transformer_capacity * 1000 / (math.sqrt(3) * 35.0)  # 变压器回路
I_35kv_line = 1.05 * p_35kv / cos_phi * 1000 / (math.sqrt(3) * 35.0 * 4)  # 出线回路
I_35kv_bus = 1.05 * (p_total / cos_phi) * 1000 / (math.sqrt(3) * 35.0)  # 母线

print(f"  35kV侧:")
print(f"    变压器回路电流: {I_35kv_total:.1f} A")
print(f"    出线回路电流(单回): {I_35kv_line:.1f} A")
print(f"    母线电流: {I_35kv_bus:.1f} A")

# 10kV侧
I_10kv_total = 1.05 * sn_each * 1000 / (math.sqrt(3) * 10.0)
I_10kv_line = 1.05 * p_10kv / cos_phi * 1000 / (math.sqrt(3) * 10.0 * 8)
I_10kv_bus = 1.05 * p_10kv / cos_phi * 1000 / (math.sqrt(3) * 10.0)

print(f"  10kV侧:")
print(f"    变压器回路电流: {I_10kv_total:.1f} A")
print(f"    出线回路电流(单回): {I_10kv_line:.1f} A")
print(f"    母线电流: {I_10kv_bus:.1f} A")

# --- 35kV侧设备选型 ---
print(f"\n--- 35kV侧设备选型 ---")

# 断路器（变压器回路）
breaker_35_tr = selector.select_circuit_breaker(
    uns=35.0,
    imax=I_35kv_total,
    i_double_prime=I_sc_35,
    i_ch=I_peak_35,
    qk=Q_35,
    voltage_level=35.0,
)
print(f"\n  35kV变压器回路断路器:")
print(f"    型号: {breaker_35_tr.get('model', 'N/A')}")
print(f"    类型: {breaker_35_tr.get('breaker_type', 'N/A')}")
print(f"    额定电压: {breaker_35_tr.get('un', 'N/A')} kV")
print(f"    额定电流: {breaker_35_tr.get('in', 'N/A')} A")
print(f"    额定开断电流: {breaker_35_tr.get('inbr', 'N/A')} kA")
print(f"    校验: {'全部通过' if breaker_35_tr.get('all_passed') else '部分未通过'}")

# 断路器（出线回路）
breaker_35_line = selector.select_circuit_breaker(
    uns=35.0,
    imax=I_35kv_line,
    i_double_prime=I_sc_35,
    i_ch=I_peak_35,
    qk=Q_35,
    voltage_level=35.0,
)
print(f"\n  35kV出线回路断路器:")
print(f"    型号: {breaker_35_line.get('model', 'N/A')}")
print(f"    类型: {breaker_35_line.get('breaker_type', 'N/A')}")
print(f"    额定电压: {breaker_35_line.get('un', 'N/A')} kV")
print(f"    额定电流: {breaker_35_line.get('in', 'N/A')} A")
print(f"    额定开断电流: {breaker_35_line.get('inbr', 'N/A')} kA")
print(f"    校验: {'全部通过' if breaker_35_line.get('all_passed') else '部分未通过'}")

# 隔离开关
switch_35_tr = selector.select_disconnect_switch(
    uns=35.0,
    imax=I_35kv_total,
    i_ch=I_peak_35,
    qk=Q_35,
    voltage_level=35.0,
    require_grounding_switch=True,
)
print(f"\n  35kV变压器回路隔离开关:")
print(f"    型号: {switch_35_tr.get('model', 'N/A')}")
print(f"    额定电压: {switch_35_tr.get('un', 'N/A')} kV")
print(f"    额定电流: {switch_35_tr.get('in', 'N/A')} A")
print(f"    接地刀闸: {'有' if switch_35_tr.get('grounding_switch_flag') else '无'}")
print(f"    校验: {'全部通过' if switch_35_tr.get('all_passed') else '部分未通过'}")

switch_35_line = selector.select_disconnect_switch(
    uns=35.0,
    imax=I_35kv_line,
    i_ch=I_peak_35,
    qk=Q_35,
    voltage_level=35.0,
    require_grounding_switch=True,
)
print(f"\n  35kV出线回路隔离开关:")
print(f"    型号: {switch_35_line.get('model', 'N/A')}")
print(f"    额定电流: {switch_35_line.get('in', 'N/A')} A")

# 导体
conductor_35 = selector.select_conductor(
    imax=I_35kv_bus,
    voltage=35.0,
    conductor_type="soft",
    i_ch=I_peak_35,
    qk=Q_35,
)
print(f"\n  35kV母线导体:")
print(f"    型号: {conductor_35.get('model', 'N/A')}")
print(f"    截面: {conductor_35.get('area_mm2', 'N/A')} mm²")
print(f"    载流量: {conductor_35.get('current_a', 'N/A')} A")
print(f"    校验: {'全部通过' if conductor_35.get('all_passed') else '部分未通过'}")

# 电流互感器
ct_35_tr = selector.select_current_transformer(
    uns=35.0,
    imax=I_35kv_total,
    secondary_load_va=15.0,
    voltage_level=35.0,
    i_double_prime=I_sc_35,
    i_ch=I_peak_35,
    qk=Q_35,
)
print(f"\n  35kV变压器回路电流互感器:")
print(f"    型号: {ct_35_tr.get('model', 'N/A')}")
print(f"    变比: {ct_35_tr.get('ratio', 'N/A')}")
print(f"    校验: {'全部通过' if ct_35_tr.get('all_passed') else '部分未通过'}")

# 避雷器
arrester_35 = selector.select_arrester(35.0, installation_position="busbar")
print(f"\n  35kV避雷器:")
print(f"    型号: {arrester_35.get('model', 'N/A')}")
print(f"    额定电压: {arrester_35.get('rated_voltage_kv', 'N/A')} kV")
print(f"    标称放电电流: {arrester_35.get('nominal_discharge_current_ka', 'N/A')} kA")

# --- 10kV侧设备选型 ---
print(f"\n--- 10kV侧设备选型 ---")

# 断路器（变压器回路）
breaker_10_tr = selector.select_circuit_breaker(
    uns=10.0,
    imax=I_10kv_total,
    i_double_prime=I_sc_10,
    i_ch=I_peak_10,
    qk=Q_10,
    voltage_level=10.0,
)
print(f"\n  10kV变压器回路断路器:")
print(f"    型号: {breaker_10_tr.get('model', 'N/A')}")
print(f"    类型: {breaker_10_tr.get('breaker_type', 'N/A')}")
print(f"    额定电压: {breaker_10_tr.get('un', 'N/A')} kV")
print(f"    额定电流: {breaker_10_tr.get('in', 'N/A')} A")
print(f"    额定开断电流: {breaker_10_tr.get('inbr', 'N/A')} kA")
print(f"    校验: {'全部通过' if breaker_10_tr.get('all_passed') else '部分未通过'}")

# 断路器（出线回路）
breaker_10_line = selector.select_circuit_breaker(
    uns=10.0,
    imax=I_10kv_line,
    i_double_prime=I_sc_10,
    i_ch=I_peak_10,
    qk=Q_10,
    voltage_level=10.0,
)
print(f"\n  10kV出线回路断路器:")
print(f"    型号: {breaker_10_line.get('model', 'N/A')}")
print(f"    类型: {breaker_10_line.get('breaker_type', 'N/A')}")
print(f"    额定电流: {breaker_10_line.get('in', 'N/A')} A")
print(f"    额定开断电流: {breaker_10_line.get('inbr', 'N/A')} kA")
print(f"    校验: {'全部通过' if breaker_10_line.get('all_passed') else '部分未通过'}")

# 隔离开关
switch_10_tr = selector.select_disconnect_switch(
    uns=10.0,
    imax=I_10kv_total,
    i_ch=I_peak_10,
    qk=Q_10,
    voltage_level=10.0,
    require_grounding_switch=True,
)
print(f"\n  10kV变压器回路隔离开关:")
print(f"    型号: {switch_10_tr.get('model', 'N/A')}")
print(f"    额定电流: {switch_10_tr.get('in', 'N/A')} A")

# 导体
conductor_10 = selector.select_conductor(
    imax=I_10kv_bus,
    voltage=10.0,
    conductor_type="hard",
    i_ch=I_peak_10,
    qk=Q_10,
)
print(f"\n  10kV母线导体:")
print(f"    型号: {conductor_10.get('model', 'N/A')}")
print(f"    截面: {conductor_10.get('area_mm2', 'N/A')} mm²")
print(f"    载流量: {conductor_10.get('current_a', 'N/A')} A")
print(f"    校验: {'全部通过' if conductor_10.get('all_passed') else '部分未通过'}")

# 电流互感器
ct_10_line = selector.select_current_transformer(
    uns=10.0,
    imax=I_10kv_line,
    secondary_load_va=10.0,
    voltage_level=10.0,
    i_double_prime=I_sc_10,
    i_ch=I_peak_10,
    qk=Q_10,
)
print(f"\n  10kV出线回路电流互感器:")
print(f"    型号: {ct_10_line.get('model', 'N/A')}")
print(f"    变比: {ct_10_line.get('ratio', 'N/A')}")

# 避雷器
arrester_10 = selector.select_arrester(10.0, installation_position="busbar")
print(f"\n  10kV避雷器:")
print(f"    型号: {arrester_10.get('model', 'N/A')}")
print(f"    额定电压: {arrester_10.get('rated_voltage_kv', 'N/A')} kV")

# 电压互感器
vt_10 = selector.select_voltage_transformer(
    voltage_level=10.0,
    total_measure_burden_va=30.0,
    total_protection_burden_va=50.0,
    neutral_grounding_mode="arc_suppression",
    require_residual_voltage=True,
)
print(f"\n  10kV电压互感器:")
print(f"    型号: {vt_10.get('model', 'N/A')}")
print(f"    一次电压: {vt_10.get('primary_voltage_kv', 'N/A')} kV")

# 消弧线圈
print(f"\n--- 消弧线圈/接地方式 ---")
arc_suppression = load_calc.select_arc_suppression_coil(transformer_capacity=315)
if arc_suppression:
    print(f"  推荐型号: {arc_suppression.get('model', 'N/A')}")
    print(f"  变容量: {arc_suppression.get('transformer_capacity', 'N/A')}")
    print(f"  线圈容量: {arc_suppression.get('coil_capacity', 'N/A')}")

# ============================================================
# 六、汇总表
# ============================================================
print("\n" + "=" * 70)
print("六、主要设备汇总表")
print("=" * 70)
print(f"""
┌──────────────────────────┬────────────────────────────────────────────────┐
│ 设备                     │ 35kV侧                                         │
├──────────────────────────┼────────────────────────────────────────────────┤
│ 主变压器                 │ {transformer_result['selected_model']:<44s} │
│ 接线方式                 │ {wiring_35kv['wiring_type']:<44s} │
│ 变压器回路断路器         │ {breaker_35_tr.get('model','N/A'):<44s} │
│ 出线回路断路器           │ {breaker_35_line.get('model','N/A'):<44s} │
│ 变压器回路隔离开关       │ {switch_35_tr.get('model','N/A'):<44s} │
│ 母线导体                 │ {conductor_35.get('model','N/A'):<44s} │
│ 电流互感器               │ {ct_35_tr.get('model','N/A'):<44s} │
│ 避雷器                   │ {arrester_35.get('model','N/A'):<44s} │
└──────────────────────────┴────────────────────────────────────────────────┘

┌──────────────────────────┬────────────────────────────────────────────────┐
│ 设备                     │ 10kV侧                                         │
├──────────────────────────┼────────────────────────────────────────────────┤
│ 接线方式                 │ {wiring_10kv['wiring_type']:<44s} │
│ 变压器回路断路器         │ {breaker_10_tr.get('model','N/A'):<44s} │
│ 出线回路断路器           │ {breaker_10_line.get('model','N/A'):<44s} │
│ 母线导体                 │ {conductor_10.get('model','N/A'):<44s} │
│ 出线电流互感器           │ {ct_10_line.get('model','N/A'):<44s} │
│ 电压互感器               │ {vt_10.get('model','N/A'):<44s} │
│ 避雷器                   │ {arrester_10.get('model','N/A'):<44s} │
└──────────────────────────┴────────────────────────────────────────────────┘
""")

print("=" * 70)
print("计算完成")
print("=" * 70)
