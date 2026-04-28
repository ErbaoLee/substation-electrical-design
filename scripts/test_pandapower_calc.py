#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests to compare pandapower calculation results with original implementation"""

import math
from calc_short_circuit import ShortCircuitCalculator, PandapowerShortCircuitCalculator, PerUnitImpedance, BranchContribution

def test_simple_fault_from_impedance():
    """Test simple fault from impedance calculation"""
    calc_original = ShortCircuitCalculator()
    calc_pandapower = PandapowerShortCircuitCalculator()

    # Test impedance
    z = PerUnitImpedance(r_pu=0.01, x_pu=0.1)
    voltage_kv = 10.0

    result_original = calc_original.fault_from_impedance(z, voltage_kv)
    result_pandapower = calc_pandapower.fault_from_impedance(z, voltage_kv)

    # Compare results, allow 1% difference
    assert math.isclose(result_original['symmetrical_current_ka'], result_pandapower['symmetrical_current_ka'], rel_tol=0.01)
    assert math.isclose(result_original['peak_current_ka'], result_pandapower['peak_current_ka'], rel_tol=0.01)
    assert math.isclose(result_original['full_current_ka'], result_pandapower['full_current_ka'], rel_tol=0.01)
    assert math.isclose(result_original['short_circuit_capacity_mva'], result_pandapower['short_circuit_capacity_mva'], rel_tol=0.01)

    print("[OK] Simple fault from impedance test passed")
    print(f"  Original: I''={result_original['symmetrical_current_ka']:.2f}kA, ish={result_original['peak_current_ka']:.2f}kA")
    print(f"  Pandapower: I''={result_pandapower['symmetrical_current_ka']:.2f}kA, ish={result_pandapower['peak_current_ka']:.2f}kA")

def test_bus_fault_simple():
    """Test simple bus fault calculation"""
    calc_original = ShortCircuitCalculator()
    calc_pandapower = PandapowerShortCircuitCalculator()

    branches = [
        BranchContribution(
            name="source1",
            impedance=PerUnitImpedance(x_pu=0.1),
            section="I",
            source_capacity_mva=100.0,
            curve_type="infinite"
        ),
        BranchContribution(
            name="source2",
            impedance=PerUnitImpedance(x_pu=0.1),
            section="II",
            source_capacity_mva=100.0,
            curve_type="infinite"
        )
    ]

    # Normal mode (both sections connected)
    result_original = calc_original.calc_bus_fault(
        wiring_type="single_bus_sectionalized",
        voltage_kv=10.0,
        branches=branches,
        fault_section="I",
        operating_mode="normal"
    )

    result_pandapower = calc_pandapower.calc_bus_fault(
        wiring_type="single_bus_sectionalized",
        voltage_kv=10.0,
        branches=branches,
        fault_section="I",
        operating_mode="normal"
    )

    assert math.isclose(
        result_original['fault']['symmetrical_current_ka'],
        result_pandapower['fault']['symmetrical_current_ka'],
        rel_tol=0.01
    )

    # Split mode (only section I active)
    result_original_split = calc_original.calc_bus_fault(
        wiring_type="single_bus_sectionalized",
        voltage_kv=10.0,
        branches=branches,
        fault_section="I",
        operating_mode="split"
    )

    result_pandapower_split = calc_pandapower.calc_bus_fault(
        wiring_type="single_bus_sectionalized",
        voltage_kv=10.0,
        branches=branches,
        fault_section="I",
        operating_mode="split"
    )

    assert math.isclose(
        result_original_split['fault']['symmetrical_current_ka'],
        result_pandapower_split['fault']['symmetrical_current_ka'],
        rel_tol=0.01
    )

    print("\n[OK] Bus fault test passed")
    print(f"  Normal mode - Original: {result_original['fault']['symmetrical_current_ka']:.2f}kA, Pandapower: {result_pandapower['fault']['symmetrical_current_ka']:.2f}kA")
    print(f"  Split mode - Original: {result_original_split['fault']['symmetrical_current_ka']:.2f}kA, Pandapower: {result_pandapower_split['fault']['symmetrical_current_ka']:.2f}kA")

def test_system_impedance_calc():
    """Test system impedance calculation"""
    calc_original = ShortCircuitCalculator()
    calc_pandapower = PandapowerShortCircuitCalculator()

    sc_capacity = 5000.0  # MVA
    x_over_r = 15.0

    z_original = calc_original.calc_system_impedance(sc_capacity, x_over_r)
    z_pandapower = calc_pandapower.calc_system_impedance(sc_capacity, x_over_r)

    assert math.isclose(z_original.r_pu, z_pandapower.r_pu, rel_tol=0.001)
    assert math.isclose(z_original.x_pu, z_pandapower.x_pu, rel_tol=0.001)

    print("\n[OK] System impedance calculation test passed")

def test_line_impedance_calc():
    """Test line impedance calculation"""
    calc_original = ShortCircuitCalculator()
    calc_pandapower = PandapowerShortCircuitCalculator()

    x1_ohm_per_km = 0.4
    length_km = 10.0
    voltage_kv = 10.0
    r1_ohm_per_km = 0.17

    z_original = calc_original.calc_line_impedance(x1_ohm_per_km, length_km, voltage_kv, r1_ohm_per_km)
    z_pandapower = calc_pandapower.calc_line_impedance(x1_ohm_per_km, length_km, voltage_kv, r1_ohm_per_km)

    assert math.isclose(z_original.r_pu, z_pandapower.r_pu, rel_tol=0.001)
    assert math.isclose(z_original.x_pu, z_pandapower.x_pu, rel_tol=0.001)

    print("\n[OK] Line impedance calculation test passed")

def test_transformer_impedance_calc():
    """Test transformer impedance calculation"""
    calc_original = ShortCircuitCalculator()
    calc_pandapower = PandapowerShortCircuitCalculator()

    uk_percent = 7.5
    sn_mva = 8.0
    x_over_r = 20.0

    z_original = calc_original.calc_transformer_impedance(uk_percent, sn_mva, x_over_r)
    z_pandapower = calc_pandapower.calc_transformer_impedance(uk_percent, sn_mva, x_over_r)

    assert math.isclose(z_original.r_pu, z_pandapower.r_pu, rel_tol=0.001)
    assert math.isclose(z_original.x_pu, z_pandapower.x_pu, rel_tol=0.001)

    print("\n[OK] Transformer impedance calculation test passed")

if __name__ == "__main__":
    print("Running pandapower calculation comparison tests...\n")

    test_simple_fault_from_impedance()
    test_bus_fault_simple()
    test_system_impedance_calc()
    test_line_impedance_calc()
    test_transformer_impedance_calc()

    print("\n✅ All tests passed! Pandapower implementation matches original results within 1% tolerance.")
