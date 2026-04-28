#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""35kV substation design calculations based on user-provided parameters."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import json
import math
from calc_load import LoadCalculator

# 全局变量供后续函数使用
main_transformer_capacity = 8  # MVA

def design_35kv_substation():
    """执行35kV变电站设计计算"""
    
    print("=" * 80)
    print("35kV变电站电气设计计算书")
    print("=" * 80)
    
    # ==================== 设计原始资料 ====================
    print("\n【一、设计原始资料】")
    
    # 变压器参数
    main_transformer_count = 2  # 终期2台
    main_transformer_capacity = 8  # MVA (每台)
    total_capacity = main_transformer_count * main_transformer_capacity
    print(f"主变压器：{main_transformer_count}×{main_transformer_capacity}MVA，总容量{total_capacity}MVA")
    
    # 35kV侧参数
    phase1_35kv_lines = 1  # 一期1回
    final_35kv_lines = 4   # 终期4回
    load_35kv_mw = 10      # 供电负荷10MW
    distance_35kv_km = 7   # 供电距离7公里
    print(f"35kV侧：一期{phase1_35kv_lines}回，终期{final_35kv_lines}回出线")
    print(f"       供电负荷{load_35kv_mw}MW，供电距离{distance_35kv_km}km")
    
    # 10kV侧参数
    phase1_10kv_lines = 3  # 一期3回
    final_10kv_lines = 8   # 终期8回
    load_10kv_mw = 13      # 供电负荷13MW
    distance_10kv_km = 4   # 供电距离4公里
    print(f"10kV侧：一期{phase1_10kv_lines}回，终期{final_10kv_lines}回出线")
    print(f"       供电负荷{load_10kv_mw}MW，供电距离{distance_10kv_km}km")
    
    # 系统参数
    system_capacity_mva = 100  # 系统容量100MVA
    system_reactance = 1.33    # 系统电抗（标幺值）
    source_distance_km = 71    # 电源距离71公里
    line_reactance_per_km = 0.4  # 线路电抗Ω/km
    max_hours = 5200           # 最大利用小时
    station_load_rate = 0.18   # 所用电率0.18%
    cos_phi = 0.8              # 平均功率因数
    load_class = "I、II类"     # 负荷性质
    print(f"系统参数：系统容量{system_capacity_mva}MVA，系统电抗{system_reactance}(标幺值)")
    print(f"         电源距离{source_distance_km}km，线路电抗{line_reactance_per_km}Ω/km")
    print(f"         最大利用小时{max_hours}h，所用电率{station_load_rate}%")
    print(f"         功率因数cosφ={cos_phi}，负荷性质：{load_class}")
    
    # ==================== 负荷计算 ====================
    print("\n【二、负荷与容量计算】")
    
    calc = LoadCalculator()
    
    # 计算最大综合负荷
    # 35kV侧负荷
    loads_35kv = [
        {"name": "35kV负荷1", "power": load_35kv_mw / final_35kv_lines, "class": "I/II"},
        {"name": "35kV负荷2", "power": load_35kv_mw / final_35kv_lines, "class": "I/II"},
        {"name": "35kV负荷3", "power": load_35kv_mw / final_35kv_lines, "class": "I/II"},
        {"name": "35kV负荷4", "power": load_35kv_mw / final_35kv_lines, "class": "I/II"},
    ]
    
    # 10kV侧负荷
    loads_10kv = [
        {"name": "10kV负荷" + str(i+1), "power": load_10kv_mw / final_10kv_lines, "class": "I/II"}
        for i in range(final_10kv_lines)
    ]
    
    # 总负荷
    total_load_mw = load_35kv_mw + load_10kv_mw
    total_load_mva = total_load_mw / cos_phi
    print(f"\n35kV侧总负荷：{load_35kv_mw}MW ({load_35kv_mw/cos_phi:.2f}MVA)")
    print(f"10kV侧总负荷：{load_10kv_mw}MW ({load_10kv_mw/cos_phi:.2f}MVA)")
    print(f"全站总负荷：{total_load_mw}MW ({total_load_mva:.2f}MVA)")
    
    # 考虑同时系数和损耗
    kt = 0.9  # 同时系数
    loss_percent = 4  # 变压器损耗4%
    s_max = kt * (total_load_mva) * (1 + loss_percent / 100)
    print(f"最大综合负荷（含同时系数和损耗）：{s_max:.2f}MVA")
    
    # 校验主变容量
    if total_capacity >= s_max:
        print(f"✓ 主变总容量{total_capacity}MVA ≥ 最大综合负荷{s_max:.2f}MVA，满足要求")
    else:
        print(f"✗ 主变总容量{total_capacity}MVA < 最大综合负荷{s_max:.2f}MVA，需增大容量")
    
    # N-1校验
    n1_load = k_factor = 0.6  # 一台主变停运时，另一台承担60%负荷
    n1_required = n1_load * s_max
    if main_transformer_capacity >= n1_required:
        print(f"✓ 单台主变{main_transformer_capacity}MVA ≥ N-1负荷{n1_required:.2f}MVA，满足N-1校验")
    else:
        print(f"✗ 单台主变{main_transformer_capacity}MVA < N-1负荷{n1_required:.2f}MVA，需增大容量")
    
    # 所用电负荷计算
    station_load_kva = total_capacity * 1000 * station_load_rate / 100
    print(f"\n所用电负荷：{station_load_kva:.2f}kVA")
    
    # 选择站用变
    station_transformer = calc.select_station_transformer(station_load_kva)
    print(f"站用变选型：{station_transformer.get('model', '待确定')}")
    
    # 无功补偿计算
    compensation_ratio = 0.15  # 补偿容量为主变容量的15%
    reactive_comp = calc.calc_reactive_power_compensation(
        main_transformer_capacity, 
        compensation_ratio, 
        groups=2
    )
    print(f"\n无功补偿：")
    print(f"  补偿目标：{compensation_ratio*100}%主变容量")
    print(f"  总补偿容量：{reactive_comp.get('actual_total_compensation', 0):.2f}kvar")
    print(f"  分组数：{reactive_comp.get('groups', 2)}")
    print(f"  单组容量：{reactive_comp.get('selected_per_group', 0):.2f}kvar")
    
    return {
        "main_transformer": {
            "count": main_transformer_count,
            "capacity_per_unit": main_transformer_capacity,
            "total_capacity": total_capacity,
        },
        "loads": {
            "load_35kv_mw": load_35kv_mw,
            "load_10kv_mw": load_10kv_mw,
            "total_load_mw": total_load_mw,
            "total_load_mva": total_load_mva,
            "s_max": s_max,
        },
        "station_load": station_load_kva,
        "station_transformer": station_transformer,
        "reactive_compensation": reactive_comp,
    }


def calc_short_circuit():
    """短路电流计算"""
    from calc_short_circuit import ShortCircuitCalculator, PerUnitImpedance, NetworkBranch, FaultSource
    
    print("\n【三、短路电流计算】")
    
    sc_calc = ShortCircuitCalculator(base_power=100.0)
    
    # 系统参数
    system_capacity_mva = 100  # 系统容量
    system_reactance = 1.33    # 系统电抗（标幺值，归算到100MVA基准）
    source_distance_km = 71    # 电源距离
    line_reactance_per_km = 0.4  # 线路电抗Ω/km
    
    # 基准值
    Sj = 100  # 基准容量MVA
    Uj_35 = 37  # 35kV侧基准电压
    Uj_10 = 10.5  # 10kV侧基准电压
    
    # 计算基准电流
    Ij_35 = sc_calc.calc_base_current(Uj_35)
    Ij_10 = sc_calc.calc_base_current(Uj_10)
    print(f"\n基准值：")
    print(f"  基准容量Sj = {Sj}MVA")
    print(f"  35kV侧基准电压Uj = {Uj_35}kV，基准电流Ij = {Ij_35:.4f}kA")
    print(f"  10kV侧基准电压Uj = {Uj_10}kV，基准电流Ij = {Ij_10:.4f}kA")
    
    # 计算系统阻抗（系统电抗1.33已归算到系统容量100MVA）
    # 由于基准容量=系统容量=100MVA，所以X*sys = 1.33
    Xs_sys = system_reactance
    print(f"\n系统阻抗（标幺值，基准容量={Sj}MVA）：X* = {Xs_sys:.4f}")
    
    # 计算线路阻抗（71km线路）
    X_line_actual = line_reactance_per_km * source_distance_km
    # 归算到35kV侧标幺值
    X_line_35_pu = sc_calc.calc_line_impedance(x1_ohm_per_km=line_reactance_per_km, length_km=source_distance_km, voltage_kv=Uj_35)
    # 归算到10kV侧标幺值
    X_line_10_pu = sc_calc.calc_line_impedance(x1_ohm_per_km=line_reactance_per_km, length_km=source_distance_km, voltage_kv=Uj_10)
    
    print(f"线路阻抗（71km）：")
    print(f"  实际值：X = {X_line_actual:.2f}Ω")
    print(f"  归算到35kV侧标幺值：X* = {X_line_35_pu.x_pu:.4f}")
    print(f"  归算到10kV侧标幺值：X* = {X_line_10_pu.x_pu:.4f}")
    
    # 主变阻抗（8MVA，Uk%=10.5）
    uk_percent = 10.5
    Xt = sc_calc.calc_transformer_impedance(uk_percent=uk_percent, sn_mva=main_transformer_capacity)
    print(f"  主变阻抗（{main_transformer_capacity}MVA，Uk%={uk_percent}）：X*T = {Xt.x_pu:.4f}")
    
    # ===== 35kV母线短路计算 =====
    # 网络结构：系统电源 → 71km线路 → 35kV母线
    branches_35kv = [
        NetworkBranch(
            name="line_71km",
            node_a="system_bus",
            node_b="35kv_bus",
            impedance=X_line_35_pu,
        ),
    ]
    sources_35kv = [
        FaultSource(
            name="system_source",
            connection_node="system_bus",
            impedance=PerUnitImpedance(x_pu=Xs_sys),
            source_type="infinite",
            curve_type="infinite",
        ),
    ]
    
    result_35kv = sc_calc.calc_network_fault(
        voltage_kv=35.0,
        fault_node="35kv_bus",
        passive_branches=branches_35kv,
        sources=sources_35kv,
        clearing_time_s=3.05,
    )
    
    print(f"\n35kV母线三相短路：")
    print(f"  对称短路电流I'' = {result_35kv['symmetrical_current_ka']:.4f}kA")
    print(f"  冲击电流ich = {result_35kv['peak_current_ka']:.4f}kA")
    print(f"  全电流I_full = {result_35kv['full_current_ka']:.4f}kA")
    print(f"  短路容量S_sc = {result_35kv['short_circuit_capacity_mva']:.2f}MVA")
    
    # ===== 10kV母线短路计算 =====
    # 网络结构：系统电源 → 71km线路 → 主变 → 10kV母线
    branches_10kv = [
        NetworkBranch(
            name="line_71km",
            node_a="system_bus",
            node_b="35kv_bus",
            impedance=X_line_35_pu,
        ),
        NetworkBranch(
            name="main_transformer",
            node_a="35kv_bus",
            node_b="10kv_bus",
            impedance=Xt,
        ),
    ]
    sources_10kv = [
        FaultSource(
            name="system_source",
            connection_node="system_bus",
            impedance=PerUnitImpedance(x_pu=Xs_sys),
            source_type="infinite",
            curve_type="infinite",
        ),
    ]
    
    result_10kv = sc_calc.calc_network_fault(
        voltage_kv=10.5,
        fault_node="10kv_bus",
        passive_branches=branches_10kv,
        sources=sources_10kv,
        clearing_time_s=4.05,
    )
    
    print(f"\n10kV母线三相短路：")
    print(f"  对称短路电流I'' = {result_10kv['symmetrical_current_ka']:.4f}kA")
    print(f"  冲击电流ich = {result_10kv['peak_current_ka']:.4f}kA")
    print(f"  全电流I_full = {result_10kv['full_current_ka']:.4f}kA")
    print(f"  短路容量S_sc = {result_10kv['short_circuit_capacity_mva']:.2f}MVA")
    
    return {
        "base_values": {
            "Sj": Sj,
            "Uj_35": Uj_35,
            "Uj_10": Uj_10,
            "Ij_35": Ij_35,
            "Ij_10": Ij_10,
        },
        "impedance": {
            "Xs_sys": Xs_sys,
            "X_line_actual": X_line_actual,
            "X_line_35_pu": X_line_35_pu.x_pu,
            "X_line_10_pu": X_line_10_pu.x_pu,
            "Xt": Xt.x_pu,
        },
        "short_circuit_35kv": result_35kv,
        "short_circuit_10kv": result_10kv,
    }


if __name__ == "__main__":
    print("\n开始35kV变电站设计计算...\n")
    
    # 负荷计算
    load_results = design_35kv_substation()
    
    # 短路计算
    sc_results = calc_short_circuit()
    
    print("\n" + "=" * 80)
    print("计算完成！")
    print("=" * 80)
