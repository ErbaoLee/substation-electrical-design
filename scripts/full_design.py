#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""35kV变电站完整电气设计脚本"""

import json
import sys
import math
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from calc_load import LoadCalculator
from calc_short_circuit import ShortCircuitCalculator, PerUnitImpedance
from generate_main_wiring import generate_main_wiring, select_wiring_type
from select_equipment import EquipmentSelector
from equipment_db import EquipmentDatabase

def main():
    print("=" * 80)
    print("35kV变电站电气设计报告")
    print(f"设计时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # ========== 设计输入参数 ==========
    print("\n一、设计原始资料")
    print("-" * 80)
    
    design_input = {
        "voltage_level": "35/10kV",
        "main_transformer": "终期2×8MVA",
        "35kv_side": {
            "outgoing_lines_phase1": 1,
            "outgoing_lines_final": 4,
            "supply_distance_km": 7,
            "supply_load_mw": 10
        },
        "10kv_side": {
            "outgoing_lines_phase1": 3,
            "outgoing_lines_final": 8,
            "supply_distance_km": 4,
            "supply_load_mw": 13
        },
        "system_parameters": {
            "source_distance_km": 71,
            "system_capacity_mva": 100,
            "max_utilization_hours": 5200,
            "system_reactance": 1.33,
            "station_service_rate_percent": 0.18,
            "line_reactance_ohm_per_km": 0.4,
            "power_factor": 0.8
        },
        "environmental_conditions": {
            "max_temperature_c": 37,
            "min_temperature_c": -7,
            "hottest_month_avg_c": 27,
            "annual_lightning_days": 120,
            "soil_resistivity_ohm_m": 1100,
            "seismic_intensity": "7度以下",
            "altitude_m": "<1800",
            "site_condition": "不受限制"
        },
        "load_type": "Ⅰ、Ⅱ类"
    }
    
    print(json.dumps(design_input, ensure_ascii=False, indent=2))
    
    # ========== 负荷与容量计算 ==========
    print("\n\n二、负荷与容量计算")
    print("-" * 80)
    
    calc = LoadCalculator()
    
    # 负荷统计
    loads = [
        {'name': '35kV侧负荷', 'power': 10.0, 'class': 'I/II'},
        {'name': '10kV侧负荷', 'power': 13.0, 'class': 'I/II'}
    ]
    
    s_max = calc.calc_max_comprehensive_load(loads, cos_phi=0.8, kt=0.85, loss_percent=4)
    print(f"\n1. 最大综合负荷计算")
    print(f"   S_max = Kt × (ΣP / cosφ) × (1 + loss%)")
    print(f"   S_max = 0.85 × (23.0 / 0.8) × 1.04 = {s_max:.2f} MVA")
    
    # 主变容量校验
    print(f"\n2. 主变容量校验")
    print(f"   用户指定配置：2×8MVA = 16MVA")
    
    transformer_result = calc.calc_transformer_capacity(s_max, n=2, k_factor=0.6, class_i_ii_load=23.0)
    print(f"   按最大负荷计算单台容量需求：{transformer_result['sn_by_max']:.2f} MVA")
    print(f"   按Ⅰ、Ⅱ类负荷计算单台容量需求：{transformer_result['sn_by_class']:.2f} MVA")
    print(f"   综合需求：{transformer_result['sn_required']:.2f} MVA")
    print(f"   数据库推荐标准容量：{transformer_result['sn_standard']} MVA")
    print(f"   N-1校验：{'✓ 满足' if transformer_result['check_n1'] else '✗ 不满足'}")
    
    if transformer_result['sn_standard'] > 8:
        print(f"\n   ⚠ 警告：用户指定8MVA < 计算需求{transformer_result['sn_required']:.2f}MVA")
        print(f"   建议：采用数据库推荐的{transformer_result['sn_standard']}MVA主变")
        print(f"   但本报告仍按用户指定的2×8MVA进行后续设计")
    
    # 站用电计算
    print(f"\n3. 站用电负荷计算")
    station_loads = [
        {'name': '主变冷却风机', 'power': 8 * 0.0018 * 1000 * 0.5, 'type': 'frequent_continuous'},
        {'name': '直流充电装置', 'power': 5.0, 'type': 'frequent_continuous'},
        {'name': '照明通风', 'power': 8.0, 'type': 'continuous_infrequent'},
        {'name': '检修电源', 'power': 3.0, 'type': 'frequent_intermittent'},
    ]
    station_result = calc.calc_station_load(station_loads)
    print(f"   站用总计算功率：{station_result['total_power']:.2f} kW")
    print(f"   站用变容量：{station_result['s_station']:.2f} kVA")
    
    station_transformer = calc.select_station_transformer(station_result['s_station'])
    if station_transformer:
        print(f"   推荐站用变：{station_transformer['model']}，容量：{station_transformer['rated_capacity']}")
    
    # 无功补偿
    print(f"\n4. 无功补偿配置")
    reactive_result = calc.calc_reactive_power_compensation(8.0, 0.15, 2)
    if reactive_result:
        print(f"   按主变容量15%配置")
        print(f"   总补偿容量：{reactive_result['total_compensation_required']:.0f} kvar")
        print(f"   分组数：2组")
        print(f"   每组容量：{reactive_result['per_group_capacity']:.0f} kvar")
        print(f"   推荐型号：{reactive_result['selected_model']}")
        print(f"   实际补偿容量：{reactive_result['actual_total_compensation']:.0f} kvar")
        print(f"   实际补偿比例：{reactive_result['actual_compensation_ratio']:.2f}%")
    
    # ========== 短路电流计算 ==========
    print("\n\n三、短路电流计算")
    print("-" * 80)
    
    sc_calc = ShortCircuitCalculator(base_power=100.0)
    
    # 系统阻抗
    system_sc_capacity = 100.0 / 1.33
    system_impedance = sc_calc.calc_system_impedance(system_sc_capacity, x_over_r=10.0)
    print(f"\n1. 系统侧等效阻抗")
    print(f"   系统短路容量 = 100 / 1.33 = {system_sc_capacity:.2f} MVA")
    print(f"   系统阻抗（标幺值）：X* = {system_impedance.x_pu:.4f}")
    
    # 电源线路阻抗（71km，0.4Ω/km）
    # 35kV变电站的电源通常来自110kV或35kV系统
    # 这里假设电源侧为110kV
    source_voltage = 110.0
    line_impedance = sc_calc.calc_line_impedance(0.4, 71.0, source_voltage, r1_ohm_per_km=0.17)
    print(f"\n2. 电源线路阻抗（110kV，71km）")
    print(f"   R* = {line_impedance.r_pu:.4f}, X* = {line_impedance.x_pu:.4f}")
    
    # 主变阻抗
    transformer_uk = 7.5
    transformer_impedance = sc_calc.calc_transformer_impedance(transformer_uk, 8.0, x_over_r=20.0)
    print(f"\n3. 主变压器阻抗（8MVA，Uk%=7.5）")
    print(f"   Z* = {transformer_impedance.magnitude:.4f}")
    
    # 35kV侧短路
    source_side_impedance = sc_calc.series_impedance(system_impedance, line_impedance)
    fault_35kv = sc_calc.fault_from_impedance(source_side_impedance, 37.0, clearing_time_s=3.05)
    print(f"\n4. 35kV母线短路计算结果")
    print(f"   对称短路电流 I'' = {fault_35kv['symmetrical_current_ka']:.2f} kA")
    print(f"   峰值电流 ish = {fault_35kv['peak_current_ka']:.2f} kA")
    print(f"   全电流 I_full = {fault_35kv['full_current_ka']:.2f} kA")
    print(f"   热效应 Qk = {fault_35kv['thermal_effect_a2s']:.2e} A²s")
    
    # 10kV侧短路
    impedance_10kv = sc_calc.series_impedance(source_side_impedance, transformer_impedance)
    fault_10kv = sc_calc.fault_from_impedance(impedance_10kv, 10.5, clearing_time_s=4.05)
    print(f"\n5. 10kV母线短路计算结果")
    print(f"   对称短路电流 I'' = {fault_10kv['symmetrical_current_ka']:.2f} kA")
    print(f"   峰值电流 ish = {fault_10kv['peak_current_ka']:.2f} kA")
    print(f"   全电流 I_full = {fault_10kv['full_current_ka']:.2f} kA")
    print(f"   热效应 Qk = {fault_10kv['thermal_effect_a2s']:.2e} A²s")
    
    # ========== 主接线方案 ==========
    print("\n\n四、电气主接线设计")
    print("-" * 80)
    
    # 35kV侧
    print(f"\n1. 35kV侧主接线")
    wiring_35kv = select_wiring_type(
        voltage_level=35.0,
        circuits=4,  # 终期4回
        reliability="important",  # Ⅰ、Ⅱ类负荷
        transformer_count=2,
        line_length="medium"  # 7km属于中等距离
    )
    print(f"   推荐接线型式：{wiring_35kv['wiring_type']}")
    print(f"   说明：{wiring_35kv['description']}")
    print(f"   出线回路：终期{design_input['35kv_side']['outgoing_lines_final']}回")
    
    # 10kV侧
    print(f"\n2. 10kV侧主接线")
    wiring_10kv = select_wiring_type(
        voltage_level=10.0,
        circuits=8,  # 终期8回
        reliability="important",
        transformer_count=2,
        line_length="short"  # 4km属于短距离
    )
    print(f"   推荐接线型式：{wiring_10kv['wiring_type']}")
    print(f"   说明：{wiring_10kv['description']}")
    print(f"   出线回路：终期{design_input['10kv_side']['outgoing_lines_final']}回")
    
    # ========== 设备选型 ==========
    print("\n\n五、主要设备选型")
    print("-" * 80)
    
    selector = EquipmentSelector()
    
    # 35kV侧设备选型
    print(f"\n1. 35kV侧设备选型")
    print(f"   额定电压：35kV")
    print(f"   短路电流：{fault_35kv['symmetrical_current_ka']:.2f} kA")
    
    # 35kV断路器
    imax_35kv = 8000 / (math.sqrt(3) * 35) * 1.05  # 8MVA对应的额定电流
    cb_35kv = selector.select_circuit_breaker(
        uns=35.0,
        imax=imax_35kv,
        i_double_prime=fault_35kv['symmetrical_current_ka'],
        i_ch=fault_35kv['peak_current_ka'],
        qk=fault_35kv['thermal_effect_a2s'],
        voltage_level=35.0
    )
    if cb_35kv:
        print(f"\n   断路器：")
        print(f"   型号：{cb_35kv['model']}")
        print(f"   额定电压：{cb_35kv['un']} kV")
        print(f"   额定电流：{cb_35kv['in']} A")
        print(f"   额定开断电流：{cb_35kv['inbr']} kA")
        print(f"   校验结果：{'✓ 全部通过' if cb_35kv.get('all_passed') else '✗ 部分校验未通过'}")
    
    # 35kV隔离开关
    ds_35kv = selector.select_disconnect_switch(
        uns=35.0,
        imax=imax_35kv,
        i_ch=fault_35kv['peak_current_ka'],
        qk=fault_35kv['thermal_effect_a2s'],
        voltage_level=35.0,
        require_grounding_switch=True
    )
    if ds_35kv:
        print(f"\n   隔离开关：")
        print(f"   型号：{ds_35kv['model']}")
        print(f"   额定电压：{ds_35kv['un']} kV")
        print(f"   额定电流：{ds_35kv['in']} A")
    
    # 35kV电流互感器
    ct_35kv = selector.select_current_transformer(
        uns=35.0,
        imax=imax_35kv,
        secondary_load_va=15.0,
        voltage_level=35.0,
        i_double_prime=fault_35kv['symmetrical_current_ka'],
        i_ch=fault_35kv['peak_current_ka'],
        qk=fault_35kv['thermal_effect_a2s']
    )
    if ct_35kv:
        print(f"\n   电流互感器：")
        print(f"   型号：{ct_35kv['model']}")
        print(f"   变比：{ct_35kv['ratio']}")
    
    # 35kV导体
    cond_35kv = selector.select_conductor(
        imax=imax_35kv,
        voltage=35.0,
        conductor_type="soft",
        i_ch=fault_35kv['peak_current_ka'],
        qk=fault_35kv['thermal_effect_a2s']
    )
    if cond_35kv:
        print(f"\n   导体：")
        print(f"   型号：{cond_35kv['model']}")
        print(f"   截面积：{cond_35kv['area_mm2']:.2f} mm²")
        print(f"   载流量：{cond_35kv['current_a']:.2f} A")
    
    # 10kV侧设备选型
    print(f"\n2. 10kV侧设备选型")
    print(f"   额定电压：10kV")
    print(f"   短路电流：{fault_10kv['symmetrical_current_ka']:.2f} kA")
    
    imax_10kv = 8000 / (math.sqrt(3) * 10) * 1.05
    cb_10kv = selector.select_circuit_breaker(
        uns=10.0,
        imax=imax_10kv,
        i_double_prime=fault_10kv['symmetrical_current_ka'],
        i_ch=fault_10kv['peak_current_ka'],
        qk=fault_10kv['thermal_effect_a2s'],
        voltage_level=10.0
    )
    if cb_10kv:
        print(f"\n   断路器：")
        print(f"   型号：{cb_10kv['model']}")
        print(f"   额定电压：{cb_10kv['un']} kV")
        print(f"   额定电流：{cb_10kv['in']} A")
        print(f"   额定开断电流：{cb_10kv['inbr']} kA")
    
    ds_10kv = selector.select_disconnect_switch(
        uns=10.0,
        imax=imax_10kv,
        i_ch=fault_10kv['peak_current_ka'],
        qk=fault_10kv['thermal_effect_a2s'],
        voltage_level=10.0,
        require_grounding_switch=True
    )
    if ds_10kv:
        print(f"\n   隔离开关：")
        print(f"   型号：{ds_10kv['model']}")
        print(f"   额定电压：{ds_10kv['un']} kV")
        print(f"   额定电流：{ds_10kv['in']} A")
    
    ct_10kv = selector.select_current_transformer(
        uns=10.0,
        imax=imax_10kv,
        secondary_load_va=15.0,
        voltage_level=10.0,
        i_double_prime=fault_10kv['symmetrical_current_ka'],
        i_ch=fault_10kv['peak_current_ka'],
        qk=fault_10kv['thermal_effect_a2s']
    )
    if ct_10kv:
        print(f"\n   电流互感器：")
        print(f"   型号：{ct_10kv['model']}")
        print(f"   变比：{ct_10kv['ratio']}")
    
    cond_10kv = selector.select_conductor(
        imax=imax_10kv,
        voltage=10.0,
        conductor_type="hard",
        i_ch=fault_10kv['peak_current_ka'],
        qk=fault_10kv['thermal_effect_a2s']
    )
    if cond_10kv:
        print(f"\n   导体：")
        print(f"   型号：{cond_10kv['model']}")
        print(f"   截面积：{cond_10kv['area_mm2']:.2f} mm²")
        print(f"   载流量：{cond_10kv['current_a']:.2f} A")
    
    # ========== 防雷与接地 ==========
    print("\n\n六、防雷与接地设计")
    print("-" * 80)
    
    print(f"\n1. 防雷设计")
    print(f"   年平均雷电日：120日/年（多雷区）")
    print(f"   避雷器配置：")
    
    arrester_35kv = selector.select_arrester(35.0, installation_position="busbar")
    if arrester_35kv:
        print(f"   35kV侧：{arrester_35kv['model']}")
        print(f"   额定电压：{arrester_35kv['rated_voltage_kv']} kV")
    
    arrester_10kv = selector.select_arrester(10.0, installation_position="busbar")
    if arrester_10kv:
        print(f"   10kV侧：{arrester_10kv['model']}")
        print(f"   额定电压：{arrester_35kv['rated_voltage_kv']} kV")
    
    print(f"\n2. 接地设计")
    print(f"   土壤电阻率：1100 Ω·m")
    print(f"   接地方式：根据负荷性质（Ⅰ、Ⅱ类）采用直接接地")
    print(f"   接地电阻要求：R ≤ 0.5Ω")
    
    # ========== 结论 ==========
    print("\n\n七、设计结论与建议")
    print("-" * 80)
    
    print(f"\n1. 主变容量")
    print(f"   计算需求：{transformer_result['sn_required']:.2f} MVA")
    print(f"   用户指定：2×8MVA = 16MVA")
    if transformer_result['sn_standard'] > 8:
        print(f"   ⚠ 建议采用2×{transformer_result['sn_standard']}MVA以满足远期负荷需求")
    
    print(f"\n2. 主接线方案")
    print(f"   35kV侧：{wiring_35kv['wiring_type']}")
    print(f"   10kV侧：{wiring_10kv['wiring_type']}")
    
    print(f"\n3. 短路电流水平")
    print(f"   35kV侧：{fault_35kv['symmetrical_current_ka']:.2f} kA")
    print(f"   10kV侧：{fault_10kv['symmetrical_current_ka']:.2f} kA")
    
    print(f"\n4. 设备选型")
    print(f"   已按短路电流校验完成，详见设备选型表")
    
    print("\n" + "=" * 80)
    print("设计报告生成完成")
    print("=" * 80)
    
    # 返回完整结果用于生成Markdown报告
    return {
        "design_input": design_input,
        "load_calculation": {
            "s_max_mva": round(s_max, 2),
            "transformer_result": transformer_result,
            "station_service": station_result,
            "reactive_compensation": reactive_result
        },
        "short_circuit": {
            "35kv": fault_35kv,
            "10kv": fault_10kv
        },
        "wiring": {
            "35kv": wiring_35kv,
            "10kv": wiring_10kv
        },
        "equipment": {
            "35kv": {
                "circuit_breaker": cb_35kv,
                "disconnect_switch": ds_35kv,
                "current_transformer": ct_35kv,
                "conductor": cond_35kv
            },
            "10kv": {
                "circuit_breaker": cb_10kv,
                "disconnect_switch": ds_10kv,
                "current_transformer": ct_10kv,
                "conductor": cond_10kv
            }
        },
        "protection": {
            "arrester_35kv": arrester_35kv,
            "arrester_10kv": arrester_10kv
        }
    }

if __name__ == "__main__":
    result = main()
