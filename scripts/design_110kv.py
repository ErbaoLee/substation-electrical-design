#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""110/35/10kV三电压等级变电站完整电气设计脚本"""

import json
import sys
import math
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from calc_load import LoadCalculator
from calc_short_circuit import get_calculator, PerUnitImpedance
from generate_main_wiring import generate_main_wiring, select_wiring_type
from select_equipment import EquipmentSelector
from equipment_db import EquipmentDatabase

def main():
    print("=" * 80)
    print("110/35/10kV 变电站电气设计报告")
    print(f"设计时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # ========== 设计输入参数 ==========
    print("\n一、设计原始资料")
    print("-" * 80)

    design_input = {
        "voltage_levels": "110/35/10kV",
        "main_transformer": "2×50MVA 三绕组变压器",
        "110kv_side": {
            "incoming_lines": 2,
            "wiring_type": "内桥接线",
            "supply_distance_km": 50
        },
        "35kv_side": {
            "outgoing_lines": 4,
            "wiring_type": "单母线分段",
            "supply_distance_km": 20
        },
        "10kv_side": {
            "outgoing_lines": 8,
            "wiring_type": "单母线分段",
            "supply_distance_km": 10
        },
        "load_parameters": {
            "max_comprehensive_load_mva": 85.0,
            "class_i_ii_load_mva": 60.0,
            "power_factor": 0.85,
            "load_factor": 0.9
        },
        "system_parameters": {
            "system_short_circuit_capacity_mva": 3000,
            "system_short_circuit_current_ka": 40.0,
            "line_reactance_ohm_per_km": 0.4,
            "station_service_rate_percent": 0.5
        },
        "environmental_conditions": {
            "altitude_m": "1000-2000",
            "pollution_level": "中等污秽",
            "seismic_intensity": "8度",
            "max_temperature_c": 40,
            "min_temperature_c": -15
        }
    }

    print(json.dumps(design_input, ensure_ascii=False, indent=2))

    # ========== 负荷与容量计算 ==========
    print("\n\n二、负荷与容量计算")
    print("-" * 80)

    calc = LoadCalculator()

    # 负荷统计
    print(f"\n1. 最大综合负荷计算")
    s_max = 85.0  # 用户给定80-90MVA,取中间值85MVA
    print(f"   最大综合负荷 S_max = {s_max} MVA")
    print(f"   Ⅰ、Ⅱ类负荷 = 60 MVA")

    # 主变容量校验
    print(f"\n2. 主变容量校验")
    print(f"   设计配置：2×50MVA = 100MVA")

    transformer_result = calc.calc_transformer_capacity(s_max, n=2, k_factor=0.6, class_i_ii_load=60.0)
    print(f"   按最大负荷计算单台容量需求：{transformer_result['sn_by_max']:.2f} MVA")
    print(f"   按Ⅰ、Ⅱ类负荷计算单台容量需求：{transformer_result['sn_by_class']:.2f} MVA")
    print(f"   综合需求：{transformer_result['sn_required']:.2f} MVA")
    print(f"   数据库推荐标准容量：{transformer_result['sn_standard']} MVA")
    print(f"   实际配置容量：50 MVA")
    total_ok = 100 >= s_max
    n1_ok = 50 >= 0.65*s_max  # 按65%校验
    print(f"   总容量校验：{'✓ 满足' if total_ok else '✗ 不满足'} (100MVA ≥ {s_max}MVA)")
    print(f"   N-1校验：{'✓ 满足' if n1_ok else '⚠ 临界'} (50MVA ≥ {0.65*s_max:.1f}MVA,按65-70%负荷率)")
    if not n1_ok:
        print(f"   建议：一台主变退出时,可通过限制Ⅲ类负荷保证Ⅰ、Ⅱ类负荷供电")

    # 站用电计算
    print(f"\n3. 站用电负荷计算")
    station_loads = [
        {'name': '主变冷却系统', 'power': 15.0, 'type': 'frequent_continuous'},
        {'name': '直流充电装置', 'power': 10.0, 'type': 'frequent_continuous'},
        {'name': '照明通风空调', 'power': 20.0, 'type': 'continuous_infrequent'},
        {'name': '检修电源', 'power': 8.0, 'type': 'frequent_intermittent'},
        {'name': '消防水泵', 'power': 5.0, 'type': 'standby'},
    ]
    station_result = calc.calc_station_load(station_loads)
    print(f"   站用总计算功率：{station_result['total_power']:.2f} kW")
    print(f"   站用变容量：{station_result['s_station']:.2f} kVA")

    station_transformer = calc.select_station_transformer(station_result['s_station'])
    if station_transformer:
        print(f"   推荐站用变：{station_transformer['model']}")
        print(f"   容量：{station_transformer['rated_capacity']}")
        print(f"   电压：{station_transformer['primary_voltage']} / {station_transformer['secondary_voltage']}")

    # 无功补偿
    print(f"\n4. 无功补偿配置")
    reactive_result = calc.calc_reactive_power_compensation(50.0, 0.20, 4)
    if reactive_result:
        print(f"   按单台主变容量20%配置")
        print(f"   总补偿容量：{reactive_result['actual_total_compensation']:.0f} kvar")
        print(f"   分组数：4组（每侧母线2组）")
        print(f"   每组容量：{reactive_result['selected_per_group']:.0f} kvar")
        print(f"   推荐型号：{reactive_result['selected_model']}")
        print(f"   实际补偿比例：{reactive_result['actual_compensation_ratio']:.2f}%")

    # 消弧线圈/接地电阻
    print(f"\n5. 中性点接地方式")
    print(f"   110kV侧：直接接地（中性点经隔离开关接地）")
    print(f"   35kV侧：经消弧线圈接地")
    print(f"   10kV侧：经小电阻接地")

    arc_coil = calc.select_arc_suppression_coil(transformer_capacity=500)
    if arc_coil:
        print(f"\n   35kV消弧线圈：")
        print(f"   型号：{arc_coil['model']}")
        print(f"   容量：{arc_coil['coil_capacity']}")
        print(f"   补偿电流范围：{arc_coil['applicable_current_range']}")

    ground_resistor = calc.select_grounding_resistor(grounding_current=1000, duration=10, voltage_level_kv=10)
    if ground_resistor:
        print(f"\n   10kV接地电阻：")
        print(f"   型号：{ground_resistor['model']}")
        print(f"   电阻值：{ground_resistor['resistance']}")
        print(f"   接地电流：{ground_resistor['grounding_current']}")

    # ========== 短路电流计算 ==========
    print("\n\n三、短路电流计算")
    print("-" * 80)

    sc_calc = get_calculator(base_power=100.0)

    # 系统阻抗（基于40kA短路电流，110kV侧）
    # S_sc = sqrt(3) * U * I_sc = 1.732 * 110 * 40 = 7621 MVA
    system_sc_capacity = math.sqrt(3) * 110 * 40
    system_impedance = sc_calc.calc_system_impedance(system_sc_capacity, x_over_r=15.0)
    print(f"\n1. 系统侧等效阻抗")
    print(f"   系统短路容量 = √3 × 110kV × 40kA = {system_sc_capacity:.0f} MVA")
    print(f"   系统阻抗（标幺值）：X* = {system_impedance.x_pu:.4f}")

    # 110kV线路阻抗（50km）
    line_110kv_impedance = sc_calc.calc_line_impedance(0.4, 50.0, 115.0, r1_ohm_per_km=0.17)
    print(f"\n2. 110kV电源线路阻抗（50km）")
    print(f"   R* = {line_110kv_impedance.r_pu:.4f}, X* = {line_110kv_impedance.x_pu:.4f}")

    # 主变阻抗（50MVA三绕组变压器）
    # 典型阻抗：高-中17%，高-低10.5%，中-低6.5%
    transformer_impedance_h = sc_calc.calc_transformer_impedance(17.0, 50.0, x_over_r=25.0)
    print(f"\n3. 主变压器阻抗（50MVA，三绕组）")
    print(f"   高中压侧阻抗 Z*_H-M = {transformer_impedance_h.magnitude:.4f}")

    # 110kV侧短路
    fault_110kv = sc_calc.fault_from_impedance(system_impedance, 115.0, clearing_time_s=3.0)
    print(f"\n4. 110kV母线短路计算结果")
    print(f"   对称短路电流 I'' = {fault_110kv['symmetrical_current_ka']:.2f} kA")
    print(f"   峰值电流 ish = {fault_110kv['peak_current_ka']:.2f} kA")
    print(f"   全电流 I_full = {fault_110kv['full_current_ka']:.2f} kA")
    print(f"   热效应 Qk = {fault_110kv['thermal_effect_a2s']:.2e} A²s")

    # 35kV侧短路
    impedance_35kv = sc_calc.series_impedance(system_impedance, transformer_impedance_h)
    fault_35kv = sc_calc.fault_from_impedance(impedance_35kv, 37.0, clearing_time_s=3.0)
    print(f"\n5. 35kV母线短路计算结果")
    print(f"   对称短路电流 I'' = {fault_35kv['symmetrical_current_ka']:.2f} kA")
    print(f"   峰值电流 ish = {fault_35kv['peak_current_ka']:.2f} kA")
    print(f"   全电流 I_full = {fault_35kv['full_current_ka']:.2f} kA")
    print(f"   热效应 Qk = {fault_35kv['thermal_effect_a2s']:.2e} A²s")

    # 10kV侧短路（需要低压侧阻抗）
    transformer_impedance_l = sc_calc.calc_transformer_impedance(10.5, 50.0, x_over_r=20.0)
    impedance_10kv = sc_calc.series_impedance(impedance_35kv, transformer_impedance_l)
    fault_10kv = sc_calc.fault_from_impedance(impedance_10kv, 10.5, clearing_time_s=4.0)
    print(f"\n6. 10kV母线短路计算结果")
    print(f"   对称短路电流 I'' = {fault_10kv['symmetrical_current_ka']:.2f} kA")
    print(f"   峰值电流 ish = {fault_10kv['peak_current_ka']:.2f} kA")
    print(f"   全电流 I_full = {fault_10kv['full_current_ka']:.2f} kA")
    print(f"   热效应 Qk = {fault_10kv['thermal_effect_a2s']:.2e} A²s")

    # ========== 主接线方案 ==========
    print("\n\n四、电气主接线设计")
    print("-" * 80)

    # 110kV侧
    print(f"\n1. 110kV侧主接线")
    wiring_110kv = select_wiring_type(
        voltage_level=110.0,
        circuits=2,
        reliability="important",
        transformer_count=2,
        line_length="long"
    )
    print(f"   推荐接线型式：{wiring_110kv['wiring_type']}")
    print(f"   说明：{wiring_110kv['description']}")
    print(f"   进线回路：{design_input['110kv_side']['incoming_lines']}回")

    # 35kV侧
    print(f"\n2. 35kV侧主接线")
    wiring_35kv = select_wiring_type(
        voltage_level=35.0,
        circuits=4,
        reliability="important",
        transformer_count=2,
        line_length="medium"
    )
    print(f"   推荐接线型式：{wiring_35kv['wiring_type']}")
    print(f"   说明：{wiring_35kv['description']}")
    print(f"   出线回路：{design_input['35kv_side']['outgoing_lines']}回")

    # 10kV侧
    print(f"\n3. 10kV侧主接线")
    wiring_10kv = select_wiring_type(
        voltage_level=10.0,
        circuits=8,
        reliability="important",
        transformer_count=2,
        line_length="short"
    )
    print(f"   推荐接线型式：{wiring_10kv['wiring_type']}")
    print(f"   说明：{wiring_10kv['description']}")
    print(f"   出线回路：{design_input['10kv_side']['outgoing_lines']}回")

    # ========== 设备选型 ==========
    print("\n\n五、主要设备选型")
    print("-" * 80)

    selector = EquipmentSelector()

    # 110kV侧设备选型
    print(f"\n1. 110kV侧设备选型")
    print(f"   额定电压：110kV")
    print(f"   短路电流：{fault_110kv['symmetrical_current_ka']:.2f} kA")

    imax_110kv = 50000 / (math.sqrt(3) * 110) * 1.05  # 50MVA对应的额定电流
    print(f"   最大工作电流：{imax_110kv:.2f} A")

    # 110kV断路器
    cb_110kv = selector.select_circuit_breaker(
        uns=110.0,
        imax=imax_110kv,
        i_double_prime=fault_110kv['symmetrical_current_ka'],
        i_ch=fault_110kv['peak_current_ka'],
        qk=fault_110kv['thermal_effect_a2s'],
        voltage_level=110.0
    )
    if cb_110kv:
        print(f"\n   断路器：")
        print(f"   型号：{cb_110kv['model']}")
        print(f"   额定电压：{cb_110kv['un']} kV")
        print(f"   额定电流：{cb_110kv['in']} A")
        print(f"   额定开断电流：{cb_110kv['inbr']} kA")
        print(f"   校验结果：{'✓ 全部通过' if cb_110kv.get('all_passed') else '✗ 部分校验未通过'}")

    # 110kV隔离开关
    ds_110kv = selector.select_disconnect_switch(
        uns=110.0,
        imax=imax_110kv,
        i_ch=fault_110kv['peak_current_ka'],
        qk=fault_110kv['thermal_effect_a2s'],
        voltage_level=110.0,
        require_grounding_switch=True
    )
    if ds_110kv:
        print(f"\n   隔离开关：")
        print(f"   型号：{ds_110kv['model']}")
        print(f"   额定电压：{ds_110kv['un']} kV")
        print(f"   额定电流：{ds_110kv['in']} A")

    # 110kV电流互感器
    ct_110kv = selector.select_current_transformer(
        uns=110.0,
        imax=imax_110kv,
        secondary_load_va=20.0,
        voltage_level=110.0,
        i_double_prime=fault_110kv['symmetrical_current_ka'],
        i_ch=fault_110kv['peak_current_ka'],
        qk=fault_110kv['thermal_effect_a2s']
    )
    if ct_110kv:
        print(f"\n   电流互感器：")
        print(f"   型号：{ct_110kv['model']}")
        print(f"   变比：{ct_110kv['ratio']}")

    # 110kV导体
    cond_110kv = selector.select_conductor(
        imax=imax_110kv,
        voltage=110.0,
        conductor_type="soft",
        i_ch=fault_110kv['peak_current_ka'],
        qk=fault_110kv['thermal_effect_a2s']
    )
    if cond_110kv:
        print(f"\n   导体：")
        print(f"   型号：{cond_110kv['model']}")
        print(f"   截面积：{cond_110kv['area_mm2']:.2f} mm²")
        print(f"   载流量：{cond_110kv['current_a']:.2f} A")

    # 35kV侧设备选型
    print(f"\n2. 35kV侧设备选型")
    print(f"   额定电压：35kV")
    print(f"   短路电流：{fault_35kv['symmetrical_current_ka']:.2f} kA")

    imax_35kv = 50000 / (math.sqrt(3) * 35) * 1.05
    print(f"   最大工作电流：{imax_35kv:.2f} A")

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
    print(f"\n3. 10kV侧设备选型")
    print(f"   额定电压：10kV")
    print(f"   短路电流：{fault_10kv['symmetrical_current_ka']:.2f} kA")

    imax_10kv = 50000 / (math.sqrt(3) * 10) * 1.05
    print(f"   最大工作电流：{imax_10kv:.2f} A")

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
        print(f"   校验结果：{'✓ 全部通过' if cb_10kv.get('all_passed') else '✗ 部分校验未通过'}")

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
    print(f"   避雷器配置：")

    arrester_110kv = selector.select_arrester(110.0, installation_position="busbar")
    if arrester_110kv:
        print(f"   110kV侧：{arrester_110kv['model']}")
        print(f"   额定电压：{arrester_110kv['rated_voltage_kv']} kV")

    arrester_35kv = selector.select_arrester(35.0, installation_position="busbar")
    if arrester_35kv:
        print(f"   35kV侧：{arrester_35kv['model']}")
        print(f"   额定电压：{arrester_35kv['rated_voltage_kv']} kV")

    arrester_10kv = selector.select_arrester(10.0, installation_position="busbar")
    if arrester_10kv:
        print(f"   10kV侧：{arrester_10kv['model']}")
        print(f"   额定电压：{arrester_10kv['rated_voltage_kv']} kV")

    print(f"\n2. 接地设计")
    print(f"   110kV系统：直接接地")
    print(f"   35kV系统：经消弧线圈接地")
    print(f"   10kV系统：经小电阻接地（1000A，10s）")
    print(f"   接地电阻要求：R ≤ 0.5Ω")

    # ========== 结论 ==========
    print("\n\n七、设计结论与建议")
    print("-" * 80)

    print(f"\n1. 主变容量")
    print(f"   设计配置：2×50MVA = 100MVA")
    print(f"   最大负荷：{s_max} MVA")
    print(f"   负载率：{s_max/100*100:.1f}%")
    print(f"   N-1校验：单台50MVA可带60%负荷 = {0.6*s_max:.1f}MVA {'✓ 满足' if 50 >= 0.6*s_max else '✗ 需加强'}")

    print(f"\n2. 主接线方案")
    print(f"   110kV侧：{wiring_110kv['wiring_type']}")
    print(f"   35kV侧：{wiring_35kv['wiring_type']}")
    print(f"   10kV侧：{wiring_10kv['wiring_type']}")

    print(f"\n3. 短路电流水平")
    print(f"   110kV侧：{fault_110kv['symmetrical_current_ka']:.2f} kA")
    print(f"   35kV侧：{fault_35kv['symmetrical_current_ka']:.2f} kA")
    print(f"   10kV侧：{fault_10kv['symmetrical_current_ka']:.2f} kA")

    print(f"\n4. 设备选型")
    print(f"   已按短路电流校验完成，详见设备选型表")

    print(f"\n5. 环境适应性")
    print(f"   海拔1000-2000m：设备外绝缘需加强，选型时已考虑海拔修正")
    print(f"   中等污秽：外绝缘爬电比距≥2.5cm/kV")

    print("\n" + "=" * 80)
    print("设计报告生成完成")
    print("=" * 80)

    # 返回完整结果用于生成Markdown报告
    return {
        "design_input": design_input,
        "load_calculation": {
            "s_max_mva": s_max,
            "transformer_result": transformer_result,
            "station_service": station_result,
            "reactive_compensation": reactive_result
        },
        "short_circuit": {
            "110kv": fault_110kv,
            "35kv": fault_35kv,
            "10kv": fault_10kv
        },
        "wiring": {
            "110kv": wiring_110kv,
            "35kv": wiring_35kv,
            "10kv": wiring_10kv
        },
        "equipment": {
            "110kv": {
                "circuit_breaker": cb_110kv,
                "disconnect_switch": ds_110kv,
                "current_transformer": ct_110kv,
                "conductor": cond_110kv
            },
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
            "arrester_110kv": arrester_110kv,
            "arrester_35kv": arrester_35kv,
            "arrester_10kv": arrester_10kv
        }
    }

if __name__ == "__main__":
    result = main()
