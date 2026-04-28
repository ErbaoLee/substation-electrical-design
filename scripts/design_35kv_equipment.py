#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""35kV substation equipment selection and main wiring design."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import json
import math
from equipment_db import EquipmentDatabase
from select_equipment import EquipmentSelector
from generate_main_wiring import select_wiring_type

def design_35kv_complete():
    """执行35kV变电站完整设计"""
    
    print("=" * 80)
    print("35kV变电站电气设计 - 主接线与设备选型")
    print("=" * 80)
    
    selector = EquipmentSelector()
    
    # ===== 设计参数 =====
    # 电压等级
    voltage_35kv = 35.0
    voltage_10kv = 10.5
    
    # 短路计算结果（来自前面的计算）
    sc_35kv_symmetrical = 0.4850  # kA
    sc_35kv_peak = 1.2330  # kA
    sc_10kv_symmetrical = 1.1660  # kA
    sc_10kv_peak = 2.9680  # kA
    
    # 负荷参数
    load_35kv_mw = 10
    load_10kv_mw = 13
    cos_phi = 0.8
    total_load_mva = (load_35kv_mw + load_10kv_mw) / cos_phi
    
    # 回路数
    circuits_35kv_in = 1  # 一期1回进线
    circuits_35kv_out = 4  # 终期4回出线
    circuits_10kv = 8  # 终期8回出线
    
    # ===== 一、主接线方案 =====
    print("\n【一、电气主接线设计】")
    
    # 35kV侧主接线
    wiring_35kv = select_wiring_type(
        voltage_level=voltage_35kv,
        circuits=circuits_35kv_out,
        reliability="important",  # I、II类负荷，重要
        transformer_count=2,
        through_power=False,
        line_length="medium",  # 7km属中短距离
    )
    print(f"\n35kV侧主接线：")
    print(f"  接线型式：{wiring_35kv['wiring_type']}")
    print(f"  说明：{wiring_35kv['description']}")
    
    # 10kV侧主接线
    wiring_10kv = select_wiring_type(
        voltage_level=voltage_10kv,
        circuits=circuits_10kv,
        reliability="important",
        transformer_count=2,
    )
    print(f"\n10kV侧主接线：")
    print(f"  接线型式：{wiring_10kv['wiring_type']}")
    print(f"  说明：{wiring_10kv['description']}")
    
    # ===== 二、35kV侧设备选型 =====
    print("\n【二、35kV侧设备选型】")
    
    # 计算35kV侧最大工作电流
    # 主变容量2×8MVA=16MVA
    imax_35kv = selector.calc_max_continuous_current(
        sn_kva=16000,  # 总容量16MVA
        un_kv=voltage_35kv,
        factor=1.05,
    )
    print(f"\n35kV侧最大工作电流：Imax = {imax_35kv:.2f}A")
    
    # 热效应计算（假设保护动作时间+断路器全开断时间=3.05s）
    qk_35kv = (sc_35kv_symmetrical * 1000) ** 2 * 3.05  # A²s
    print(f"35kV侧热效应：Qk = {qk_35kv/1e6:.2f}×10⁶ A²s")
    
    # 1. 35kV断路器选型
    print(f"\n1. 35kV断路器选型：")
    breaker_35kv = selector.select_circuit_breaker(
        uns=voltage_35kv,
        imax=imax_35kv,
        i_double_prime=sc_35kv_symmetrical,
        i_ch=sc_35kv_peak,
        qk=qk_35kv,
        voltage_level=voltage_35kv,
    )
    if breaker_35kv:
        print(f"  型号：{breaker_35kv['model']}")
        print(f"  额定电压：{breaker_35kv['un']}kV")
        print(f"  额定电流：{breaker_35kv['in']}A")
        print(f"  额定开断电流：{breaker_35kv['inbr']}kA")
        print(f"  动稳定电流：{breaker_35kv['ies']}kA")
        print(f"  热稳定：{breaker_35kv['it']}kA/{breaker_35kv['thermal_time_s']}s")
        print(f"  校验：{'✓ 全部通过' if breaker_35kv['all_passed'] else '✗ 部分未通过'}")
    
    # 2. 35kV隔离开关选型
    print(f"\n2. 35kV隔离开关选型：")
    ds_35kv = selector.select_disconnect_switch(
        uns=voltage_35kv,
        imax=imax_35kv,
        i_ch=sc_35kv_peak,
        qk=qk_35kv,
        voltage_level=voltage_35kv,
    )
    if ds_35kv:
        print(f"  型号：{ds_35kv['model']}")
        print(f"  额定电压：{ds_35kv['un']}kV")
        print(f"  额定电流：{ds_35kv['in']}A")
        print(f"  动稳定电流：{ds_35kv['ies']}kA")
        print(f"  热稳定：{ds_35kv['it']}kA/{ds_35kv['thermal_time_s']}s")
    
    # 3. 35kV电流互感器选型
    print(f"\n3. 35kV电流互感器选型：")
    ct_35kv = selector.select_current_transformer(
        uns=voltage_35kv,
        imax=imax_35kv,
        secondary_load_va=15.0,  # 二次负荷15VA
        voltage_level=voltage_35kv,
        i_double_prime=sc_35kv_symmetrical,
        i_ch=sc_35kv_peak,
        qk=qk_35kv,
    )
    if ct_35kv:
        print(f"  型号：{ct_35kv['model']}")
        print(f"  变比：{ct_35kv['ratio']}")
        print(f"  额定电压：{ct_35kv['un']}kV")
        print(f"  二次负荷：{ct_35kv['s2n_va']}VA")
    
    # 4. 35kV电压互感器选型
    print(f"\n4. 35kV电压互感器选型：")
    pt_35kv = selector.select_voltage_transformer(
        voltage_level=voltage_35kv,
        total_measure_burden_va=50.0,
        total_protection_burden_va=50.0,
    )
    if pt_35kv:
        print(f"  型号：{pt_35kv['model']}")
        print(f"  额定电压：{pt_35kv['primary_voltage_kv']}kV")
        print(f"  测量精度：{pt_35kv['accuracy_measure']}")
    
    # 5. 35kV避雷器选型
    print(f"\n5. 35kV避雷器选型：")
    arrester_35kv = selector.select_arrester(
        voltage_level=voltage_35kv,
        installation_position="busbar",
    )
    if arrester_35kv:
        print(f"  型号：{arrester_35kv['model']}")
        print(f"  额定电压：{arrester_35kv['rated_voltage_kv']}kV")
        print(f"  标称放电电流：{arrester_35kv['nominal_discharge_current_ka']}kA")
    
    # 6. 35kV导体选型（软导线）
    print(f"\n6. 35kV导体选型：")
    conductor_35kv = selector.select_conductor(
        imax=imax_35kv,
        voltage=voltage_35kv,
        conductor_type="soft",
        i_ch=sc_35kv_peak,
        qk=qk_35kv,
    )
    if conductor_35kv:
        print(f"  型号：{conductor_35kv['model']}")
        print(f"  截面积：{conductor_35kv['area_mm2']}mm²")
        print(f"  载流量：{conductor_35kv['current_a']}A")
    
    # ===== 三、10kV侧设备选型 =====
    print("\n【三、10kV侧设备选型】")
    
    # 计算10kV侧最大工作电流
    imax_10kv = selector.calc_max_continuous_current(
        sn_kva=16000,
        un_kv=voltage_10kv,
        factor=1.05,
    )
    print(f"\n10kV侧最大工作电流：Imax = {imax_10kv:.2f}A")
    
    qk_10kv = (sc_10kv_symmetrical * 1000) ** 2 * 4.05
    print(f"10kV侧热效应：Qk = {qk_10kv/1e6:.2f}×10⁶ A²s")
    
    # 1. 10kV断路器选型
    print(f"\n1. 10kV断路器选型：")
    breaker_10kv = selector.select_circuit_breaker(
        uns=voltage_10kv,
        imax=imax_10kv,
        i_double_prime=sc_10kv_symmetrical,
        i_ch=sc_10kv_peak,
        qk=qk_10kv,
        voltage_level=voltage_10kv,
    )
    if breaker_10kv:
        print(f"  型号：{breaker_10kv['model']}")
        print(f"  额定电压：{breaker_10kv['un']}kV")
        print(f"  额定电流：{breaker_10kv['in']}A")
        print(f"  额定开断电流：{breaker_10kv['inbr']}kA")
    
    # 2. 10kV隔离开关选型
    print(f"\n2. 10kV隔离开关选型：")
    ds_10kv = selector.select_disconnect_switch(
        uns=voltage_10kv,
        imax=imax_10kv,
        i_ch=sc_10kv_peak,
        qk=qk_10kv,
        voltage_level=voltage_10kv,
    )
    if ds_10kv:
        print(f"  型号：{ds_10kv['model']}")
        print(f"  额定电压：{ds_10kv['un']}kV")
        print(f"  额定电流：{ds_10kv['in']}A")
    
    # 3. 10kV电流互感器选型
    print(f"\n3. 10kV电流互感器选型：")
    ct_10kv = selector.select_current_transformer(
        uns=voltage_10kv,
        imax=imax_10kv,
        secondary_load_va=15.0,
        voltage_level=voltage_10kv,
        i_double_prime=sc_10kv_symmetrical,
        i_ch=sc_10kv_peak,
        qk=qk_10kv,
    )
    if ct_10kv:
        print(f"  型号：{ct_10kv['model']}")
        print(f"  变比：{ct_10kv['ratio']}")
    
    # 4. 10kV电压互感器选型
    print(f"\n4. 10kV电压互感器选型：")
    pt_10kv = selector.select_voltage_transformer(
        voltage_level=voltage_10kv,
        total_measure_burden_va=50.0,
        total_protection_burden_va=50.0,
    )
    if pt_10kv:
        print(f"  型号：{pt_10kv['model']}")
        print(f"  额定电压：{pt_10kv['primary_voltage_kv']}kV")
    
    # 5. 10kV避雷器选型
    print(f"\n5. 10kV避雷器选型：")
    arrester_10kv = selector.select_arrester(
        voltage_level=voltage_10kv,
        installation_position="busbar",
    )
    if arrester_10kv:
        print(f"  型号：{arrester_10kv['model']}")
        print(f"  额定电压：{arrester_10kv['rated_voltage_kv']}kV")
    
    # 6. 10kV导体选型
    print(f"\n6. 10kV导体选型：")
    conductor_10kv = selector.select_conductor(
        imax=imax_10kv,
        voltage=voltage_10kv,
        conductor_type="soft",
        i_ch=sc_10kv_peak,
        qk=qk_10kv,
    )
    if conductor_10kv:
        print(f"  型号：{conductor_10kv['model']}")
        print(f"  截面积：{conductor_10kv['area_mm2']}mm²")
    
    return {
        "wiring": {
            "35kv": wiring_35kv,
            "10kv": wiring_10kv,
        },
        "equipment": {
            "35kv": {
                "breaker": breaker_35kv,
                "disconnect_switch": ds_35kv,
                "current_transformer": ct_35kv,
                "voltage_transformer": pt_35kv,
                "arrester": arrester_35kv,
                "conductor": conductor_35kv,
            },
            "10kv": {
                "breaker": breaker_10kv,
                "disconnect_switch": ds_10kv,
                "current_transformer": ct_10kv,
                "voltage_transformer": pt_10kv,
                "arrester": arrester_10kv,
                "conductor": conductor_10kv,
            },
        },
        "parameters": {
            "imax_35kv": imax_35kv,
            "imax_10kv": imax_10kv,
            "sc_35kv_symmetrical": sc_35kv_symmetrical,
            "sc_10kv_symmetrical": sc_10kv_symmetrical,
        },
    }


if __name__ == "__main__":
    results = design_35kv_complete()
    print("\n" + "=" * 80)
    print("设备选型完成！")
    print("=" * 80)
