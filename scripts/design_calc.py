#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""35kV变电站设计计算脚本"""

import json
import sys
from pathlib import Path

# 确保可以导入模块
sys.path.insert(0, str(Path(__file__).parent))

from calc_load import LoadCalculator
from calc_short_circuit import get_calculator, PerUnitImpedance
from equipment_db import EquipmentDatabase

def main():
    print("=" * 80)
    print("35kV变电站电气设计计算")
    print("=" * 80)
    
    # ========== 第一部分：负荷与容量计算 ==========
    print("\n【第一部分】负荷与容量计算\n")
    
    calc = LoadCalculator()
    
    # 负荷统计
    # 根据设计输入：
    # - 35kV侧供电负荷10MW（供电能力）
    # - 10kV侧供电负荷13MW（供电能力）
    # - cosφ = 0.8
    # - 同时率取0.85（变电站各回路不会同时满载）
    
    loads = [
        {'name': '35kV侧负荷', 'power': 10.0, 'class': 'I/II'},
        {'name': '10kV侧负荷', 'power': 13.0, 'class': 'I/II'}
    ]
    
    # 计算最大综合负荷（考虑同时率0.85）
    s_max = calc.calc_max_comprehensive_load(loads, cos_phi=0.8, kt=0.85, loss_percent=4)
    print(f"最大综合负荷 S_max = {s_max:.2f} MVA")
    print(f"  计算过程：S_max = 0.85 × (23.0 / 0.8) × 1.04 = {s_max:.2f} MVA")
    
    # 考虑最大利用小时5200h，年负荷利用小时数较高，说明负荷稳定
    # 实际设计负荷可按供电负荷的80%考虑
    design_load_35kv = 10.0 * 0.8  # 8MW
    design_load_10kv = 13.0 * 0.8  # 10.4MW
    total_design_mw = design_load_35kv + design_load_10kv
    total_design_mva = total_design_mw / 0.8
    print(f"\n设计负荷（80%供电能力）：")
    print(f"  35kV侧：{design_load_35kv:.1f} MW")
    print(f"  10kV侧：{design_load_10kv:.1f} MW")
    print(f"  合计：{total_design_mw:.1f} MW = {total_design_mva:.2f} MVA")
    
    # 主变容量校验：2×8MVA
    print(f"\n主变配置：2×8MVA = 16MVA")
    transformer_result = calc.calc_transformer_capacity(s_max, n=2, k_factor=0.6, class_i_ii_load=23.0)
    print(f"主变容量校验：")
    print(f"  按最大负荷计算单台容量：{transformer_result['sn_by_max']:.2f} MVA")
    print(f"  推荐标准容量：{transformer_result['sn_standard']} MVA")
    print(f"  N-1校验：{'满足' if transformer_result['check_n1'] else '不满足'}")
    
    # 站用电计算
    # 所用电率0.18%
    station_loads = [
        {'name': '主变冷却', 'power': 8 * 0.0018 * 1000 * 0.5, 'type': 'frequent_continuous'},
        {'name': '直流充电', 'power': 5.0, 'type': 'frequent_continuous'},
        {'name': '照明通风', 'power': 8.0, 'type': 'continuous_infrequent'},
        {'name': '检修电源', 'power': 3.0, 'type': 'frequent_intermittent'},
    ]
    station_result = calc.calc_station_load(station_loads)
    print(f"\n站用电负荷：")
    print(f"  计算站用功率：{station_result['total_power']:.2f} kW")
    print(f"  站用变容量：{station_result['s_station']:.2f} kVA")
    
    # 选择站用变
    station_transformer = calc.select_station_transformer(station_result['s_station'])
    if station_transformer:
        print(f"  推荐站用变：{station_transformer['model']}，容量：{station_transformer['rated_capacity']}")
    
    # 无功补偿计算
    # 按主变容量15%配置
    total_transformer_capacity = 8  # 单台8MVA
    reactive_result = calc.calc_reactive_power_compensation(total_transformer_capacity, 0.15, 2)
    print(f"\n无功补偿配置：")
    if reactive_result:
        print(f"  目标补偿比例：{reactive_result['compensation_ratio_target']:.0f}%")
        print(f"  总补偿容量：{reactive_result['total_compensation_required']:.0f} kvar")
        print(f"  分组数：{reactive_result['groups']}")
        print(f"  推荐型号：{reactive_result['selected_model']}")
        print(f"  实际补偿容量：{reactive_result['actual_total_compensation']:.0f} kvar")
    
    # ========== 第二部分：短路电流计算 ==========
    print("\n\n【第二部分】短路电流计算\n")
    
    sc_calc = get_calculator(base_power=100.0)
    
    # 1. 系统侧阻抗（系统容量100MVA，系统电抗1.33）
    # 系统短路容量 = 100 / 1.33 = 75.19 MVA
    system_sc_capacity = 100.0 / 1.33
    print(f"系统参数：")
    print(f"  系统容量：100 MVA")
    print(f"  系统电抗：1.33")
    print(f"  系统等效短路容量：{system_sc_capacity:.2f} MVA")
    
    system_impedance = sc_calc.calc_system_impedance(system_sc_capacity, x_over_r=10.0)
    print(f"  系统阻抗（标幺值）：{system_impedance.to_dict()}")
    
    # 2. 电源线路阻抗（71km，0.4Ω/km）
    # 假设电源侧电压为110kV（典型输电电压）
    source_voltage = 110.0  # kV
    line_impedance = sc_calc.calc_line_impedance(0.4, 71.0, source_voltage, r1_ohm_per_km=0.17)
    print(f"\n电源线路（110kV，71km）：")
    print(f"  线路阻抗（标幺值）：{line_impedance.to_dict()}")
    
    # 3. 主变阻抗（8MVA，35/10kV）
    # 典型35kV变压器 Uk% = 7.5%
    transformer_uk = 7.5  # %
    transformer_impedance = sc_calc.calc_transformer_impedance(transformer_uk, 8.0, x_over_r=20.0)
    print(f"\n主变压器（8MVA，35/10kV，Uk%=7.5）：")
    print(f"  变压器阻抗（标幺值）：{transformer_impedance.to_dict()}")
    
    # 4. 35kV侧短路电流
    # 电源侧等效阻抗 = 系统阻抗 + 线路阻抗
    source_side_impedance = sc_calc.series_impedance(system_impedance, line_impedance)
    
    # 35kV母线短路（不经过主变）
    impedance_35kv = source_side_impedance
    fault_35kv = sc_calc.fault_from_impedance(impedance_35kv, 37.0, clearing_time_s=3.05)
    print(f"\n35kV母线短路：")
    print(f"  对称短路电流：{fault_35kv['symmetrical_current_ka']:.2f} kA")
    print(f"  峰值电流：{fault_35kv['peak_current_ka']:.2f} kA")
    print(f"  全电流：{fault_35kv['full_current_ka']:.2f} kA")
    print(f"  热效应：{fault_35kv['thermal_effect_a2s']:.2e} A²s")
    
    # 5. 10kV侧短路电流
    # 经过主变
    impedance_10kv = sc_calc.series_impedance(source_side_impedance, transformer_impedance)
    fault_10kv = sc_calc.fault_from_impedance(impedance_10kv, 10.5, clearing_time_s=4.05)
    print(f"\n10kV母线短路：")
    print(f"  对称短路电流：{fault_10kv['symmetrical_current_ka']:.2f} kA")
    print(f"  峰值电流：{fault_10kv['peak_current_ka']:.2f} kA")
    print(f"  全电流：{fault_10kv['full_current_ka']:.2f} kA")
    print(f"  热效应：{fault_10kv['thermal_effect_a2s']:.2e} A²s")
    
    # ========== 输出结果汇总 ==========
    print("\n\n【计算结果汇总】")
    print("=" * 80)
    
    results = {
        "load_calculation": {
            "s_max_mva": round(s_max, 2),
            "transformer_configuration": "2×8MVA",
            "transformer_check": transformer_result,
            "station_service_kva": round(station_result['s_station'], 2),
            "reactive_compensation_kvar": reactive_result.get('actual_total_compensation', 0) if reactive_result else 0
        },
        "short_circuit": {
            "35kv_bus": {
                "symmetrical_ka": round(fault_35kv['symmetrical_current_ka'], 2),
                "peak_ka": round(fault_35kv['peak_current_ka'], 2),
                "full_ka": round(fault_35kv['full_current_ka'], 2),
                "thermal_effect_a2s": round(fault_35kv['thermal_effect_a2s'], 2)
            },
            "10kv_bus": {
                "symmetrical_ka": round(fault_10kv['symmetrical_current_ka'], 2),
                "peak_ka": round(fault_10kv['peak_current_ka'], 2),
                "full_ka": round(fault_10kv['full_current_ka'], 2),
                "thermal_effect_a2s": round(fault_10kv['thermal_effect_a2s'], 2)
            }
        }
    }
    
    print(json.dumps(results, ensure_ascii=False, indent=2))
    
    return results

if __name__ == "__main__":
    main()
