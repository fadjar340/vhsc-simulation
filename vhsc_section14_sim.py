#!/usr/bin/env python3
"""
vhsc_section14_sim.py

First-order simulation package for VHS-C Section 14:
1. Roofline / memory-wall simulation
2. Vertical-bus RC / signal-integrity estimate
3. 3D thermal-resistance estimate
4. Basic NoC fault-injection simulation

This script is intentionally conservative and parametric.
It is not proof of VHS-C feasibility. It is a starting simulation scaffold
for converting the roadmap into measurable models.

Author: Fadjar Tandabawana / VHS-C research roadmap support
"""

from __future__ import annotations

import csv
import math
import random
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import matplotlib.pyplot as plt


# =============================================================================
# Output directory
# =============================================================================

OUTDIR = Path("vhsc_sim_outputs")
OUTDIR.mkdir(exist_ok=True)


# =============================================================================
# Utility functions
# =============================================================================

def write_csv(path: Path, rows: List[Dict[str, float | int | str]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def human_si(x: float, unit: str = "") -> str:
    """Small helper for readable scientific values."""
    prefixes = [
        (1e18, "E"),
        (1e15, "P"),
        (1e12, "T"),
        (1e9, "G"),
        (1e6, "M"),
        (1e3, "k"),
        (1.0, ""),
        (1e-3, "m"),
        (1e-6, "u"),
        (1e-9, "n"),
        (1e-12, "p"),
        (1e-15, "f"),
    ]
    ax = abs(x)
    for scale, prefix in prefixes:
        if ax >= scale:
            return f"{x / scale:.3g} {prefix}{unit}"
    return f"{x:.3g} {unit}"


# =============================================================================
# Model 1: Roofline / Memory-Wall Simulation with Data-Movement Energy
# =============================================================================

@dataclass
class RooflineSystem:
    name: str

    # Throughput model
    peak_ops_s: float
    bandwidth_B_s: float

    # Data-movement model
    long_range_energy_pJ_B: float

    # Fraction of total workload bytes that must move through long-range path.
    # This is the key VHS-C locality assumption.
    # Planar baseline = high long-range byte fraction.
    # VHS-C = lower long-range byte fraction because more data is local.
    long_range_byte_fraction: float

    # Documentation field for traceability.
    derivation_note: str


def roofline_performance(
    system: RooflineSystem,
    operational_intensity_ops_B: np.ndarray,
) -> np.ndarray:
    """
    Roofline:
        achievable_ops_s = min(peak_ops_s, bandwidth_B_s * operational_intensity)
    """
    return np.minimum(system.peak_ops_s, system.bandwidth_B_s * operational_intensity_ops_B)


def workload_energy_model(
    system: RooflineSystem,
    workload_ops: float,
    operational_intensity_ops_B: np.ndarray,
) -> Dict[str, np.ndarray]:
    """
    Workload movement model.

    operational_intensity = ops / byte

    total_bytes_touched = workload_ops / operational_intensity

    long_range_bytes = total_bytes_touched * long_range_byte_fraction

    movement_energy_J = long_range_bytes * long_range_energy_pJ_B * 1e-12

    This does not include compute energy. It isolates the data-movement term so that
    the VHS-C memory-wall claim can be tested independently.
    """
    total_bytes = workload_ops / operational_intensity_ops_B
    long_range_bytes = total_bytes * system.long_range_byte_fraction
    movement_energy_J = long_range_bytes * system.long_range_energy_pJ_B * 1e-12

    return {
        "total_bytes": total_bytes,
        "long_range_bytes": long_range_bytes,
        "movement_energy_J": movement_energy_J,
    }


def run_roofline_model() -> List[Dict[str, float | str]]:
    """
    Compare:
    - Planar baseline
    - VHS-C single layer
    - VHS-C multi-layer stack

    Important:
    The numbers below are placeholder assumptions. They must be replaced by
    area-derived, cell-derived, or measured parameters before being treated as evidence.

    The VHS-C single-layer 250 TOPS value is intentionally documented as a placeholder.
    A later version should derive it from:
        tile_area_mm2
        usable_compute_fraction
        cell_density_or_MAC_density
        clock_frequency
        operations_per_cycle_per_unit
        active_utilization
    """
    systems = [
        RooflineSystem(
            name="Planar baseline",
            peak_ops_s=100e12,
            bandwidth_B_s=1e12,
            long_range_energy_pJ_B=20.0,
            long_range_byte_fraction=1.00,
            derivation_note=(
                "Placeholder baseline: 100 TOPS and 1 TB/s represent a conventional "
                "separated compute-memory system for comparison only."
            ),
        ),
        RooflineSystem(
            name="VHS-C single layer",
            peak_ops_s=250e12,
            bandwidth_B_s=4e12,
            long_range_energy_pJ_B=6.0,
            long_range_byte_fraction=0.35,
            derivation_note=(
                "Placeholder VHS-C single-layer estimate. Must later be derived from "
                "50 mm x 50 mm tile area, usable compute fraction, standard-cell or "
                "MAC density, clock frequency, utilization, and thermal limit."
            ),
        ),
        RooflineSystem(
            name="VHS-C multi-layer stack",
            peak_ops_s=1e15,
            bandwidth_B_s=20e12,
            long_range_energy_pJ_B=2.0,
            long_range_byte_fraction=0.10,
            derivation_note=(
                "Placeholder VHS-C stacked estimate. Represents increased local bandwidth "
                "and reduced long-range movement from repeated compute-memory layers. "
                "Not a demonstrated device result."
            ),
        ),
    ]

    # Operational intensity sweep: 0.01 to 10,000 ops/byte
    oi = np.logspace(-2, 4, 400)

    # Example workload: 1e15 operations.
    # This can represent one bounded benchmark phase.
    workload_ops = 1e15

    # -------------------------------------------------------------------------
    # Roofline throughput plot
    # -------------------------------------------------------------------------
    plt.figure(figsize=(9, 6))
    summary_rows: List[Dict[str, float | str]] = []

    for s in systems:
        perf = roofline_performance(s, oi)
        ridge_oi = s.peak_ops_s / s.bandwidth_B_s

        plt.loglog(oi, perf / 1e12, label=s.name)

        summary_rows.append({
            "system": s.name,
            "peak_TOPS": s.peak_ops_s / 1e12,
            "bandwidth_TB_s": s.bandwidth_B_s / 1e12,
            "ridge_point_ops_per_byte": ridge_oi,
            "long_range_energy_pJ_per_byte": s.long_range_energy_pJ_B,
            "long_range_byte_fraction": s.long_range_byte_fraction,
            "derivation_note": s.derivation_note,
        })

    plt.xlabel("Operational intensity [ops/byte]")
    plt.ylabel("Achievable throughput [TOPS]")
    plt.title("VHS-C Roofline / Memory-Wall First-Order Model")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "roofline_plot.png", dpi=200)
    plt.close()

    write_csv(OUTDIR / "roofline_summary.csv", summary_rows)

    # -------------------------------------------------------------------------
    # Data movement and energy model
    # -------------------------------------------------------------------------
    energy_rows: List[Dict[str, float | str]] = []

    baseline = systems[0]
    baseline_energy = workload_energy_model(baseline, workload_ops, oi)

    plt.figure(figsize=(9, 6))

    for s in systems:
        em = workload_energy_model(s, workload_ops, oi)
        perf = roofline_performance(s, oi)

        # Runtime estimate from roofline throughput.
        runtime_s = workload_ops / perf

        # Ratio against planar baseline.
        r_movement = baseline_energy["long_range_bytes"] / em["long_range_bytes"]
        r_energy = baseline_energy["movement_energy_J"] / em["movement_energy_J"]

        plt.loglog(
            oi,
            em["movement_energy_J"],
            label=f"{s.name}"
        )

        # Store selected operating points for easier reading.
        for selected_oi in [0.1, 1.0, 10.0, 100.0, 1000.0]:
            idx = int(np.argmin(np.abs(oi - selected_oi)))

            energy_rows.append({
                "system": s.name,
                "workload_ops": workload_ops,
                "operational_intensity_ops_per_byte": float(oi[idx]),
                "achievable_TOPS": float(perf[idx] / 1e12),
                "runtime_s": float(runtime_s[idx]),
                "total_bytes_TB": float(em["total_bytes"][idx] / 1e12),
                "long_range_bytes_TB": float(em["long_range_bytes"][idx] / 1e12),
                "movement_energy_J": float(em["movement_energy_J"][idx]),
                "Rmovement_vs_planar": float(r_movement[idx]),
                "Renergy_vs_planar": float(r_energy[idx]),
                "long_range_byte_fraction": s.long_range_byte_fraction,
                "long_range_energy_pJ_per_byte": s.long_range_energy_pJ_B,
            })

    plt.xlabel("Operational intensity [ops/byte]")
    plt.ylabel("Long-range data-movement energy [J]")
    plt.title(f"Data-Movement Energy for {workload_ops:.1e} Operations")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "roofline_energy_plot.png", dpi=200)
    plt.close()

    write_csv(OUTDIR / "roofline_energy_summary.csv", energy_rows)

    # -------------------------------------------------------------------------
    # Movement-ratio plot
    # -------------------------------------------------------------------------
    plt.figure(figsize=(9, 6))

    for s in systems[1:]:
        em = workload_energy_model(s, workload_ops, oi)
        r_movement = baseline_energy["long_range_bytes"] / em["long_range_bytes"]
        r_energy = baseline_energy["movement_energy_J"] / em["movement_energy_J"]

        plt.semilogx(oi, r_movement, label=f"{s.name}: Rmovement")
        plt.semilogx(oi, r_energy, linestyle="--", label=f"{s.name}: Renergy")

    plt.xlabel("Operational intensity [ops/byte]")
    plt.ylabel("Reduction ratio vs planar baseline [x]")
    plt.title("VHS-C Long-Range Movement and Energy Reduction Ratios")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "roofline_movement_reduction.png", dpi=200)
    plt.close()

    return summary_rows


# =============================================================================
# Model 2: Vertical-Bus RC / Signal-Integrity Estimate
# =============================================================================

@dataclass
class ViaMaterial:
    name: str
    resistivity_ohm_m: float


@dataclass
class VerticalBusConfig:
    """
    First-order VHS-C vertical bus geometry.

    IMPORTANT:
    This model is order-of-magnitude only.

    The capacitance estimate uses a simplified coaxial / nearest-return approximation.
    It does not model:
        - true return-path geometry,
        - adjacent-via arrays,
        - redistribution layers,
        - dielectric-layer stackup,
        - ground shielding,
        - skin/proximity effects,
        - package discontinuities,
        - driver/receiver equalization.

    Real extraction requires FastCap/FastHenry, COMSOL, Ansys HFSS/Q3D, Cadence/Synopsys
    extraction, or an equivalent field solver.
    """
    via_diameter_m: float = 1.0e-6
    via_length_m: float = 10.0e-6
    via_pitch_m: float = 5.0e-6
    eps_r: float = 3.5
    voltage_v: float = 0.7

    # Coupling factor is a placeholder multiplier to represent nearby conductors.
    # 1.0 = optimistic simplified single-return approximation.
    # 2.0-5.0 = more pessimistic rough array/coupling assumption.
    coupling_factor: float = 2.0

    # Architecture-level assumptions
    allowed_rc_fraction_of_ui: float = 0.20  # RC tau must be <= 20% of bit UI
    max_practical_data_rate_Gbps_cap: float = 224.0  # external cap for sanity
    vertical_lanes_per_bus_column: int = 1024


MATERIALS = [
    ViaMaterial("Gold", 2.44e-8),
    ViaMaterial("Copper", 1.68e-8),
    ViaMaterial("Tungsten", 5.60e-8),
]


def estimate_via_params(material: ViaMaterial, cfg: VerticalBusConfig) -> Dict[str, float | str]:
    """
    First-order vertical via model.

    Resistance:
        R = rho * L / A

    Capacitance:
        Simplified coaxial-like approximation:
        C ≈ k * 2πeps0epsrL / ln(pitch/radius)

    Inductance:
        Approximate partial self-inductance of a short cylindrical conductor.

    Data-rate estimate:
        tau = R*C

        If tau must be <= allowed_fraction * UI,
        then UI >= tau / allowed_fraction

        data_rate_RC ≈ allowed_fraction / tau

    This is not a real SerDes channel model. It only tells whether the extracted
    RC is obviously impossible or plausibly small enough to continue modeling.
    """
    eps0 = 8.854e-12
    mu0 = 4.0 * math.pi * 1e-7

    radius = cfg.via_diameter_m / 2.0
    area = math.pi * radius * radius

    r_ohm = material.resistivity_ohm_m * cfg.via_length_m / area

    # Order-of-magnitude coupling capacitance.
    log_arg = max(cfg.via_pitch_m / radius, 1.000001)
    c_f = (
        cfg.coupling_factor
        * 2.0
        * math.pi
        * eps0
        * cfg.eps_r
        * cfg.via_length_m
        / math.log(log_arg)
    )

    # Approximate partial inductance.
    if cfg.via_length_m > radius:
        l_h = (
            mu0
            * cfg.via_length_m
            / (2.0 * math.pi)
            * (math.log(2.0 * cfg.via_length_m / radius) - 0.75)
        )
    else:
        l_h = 1e-15

    tau_s = r_ohm * c_f
    f_3db_hz = 1.0 / (2.0 * math.pi * tau_s) if tau_s > 0 else float("inf")
    e_toggle_j = 0.5 * c_f * cfg.voltage_v * cfg.voltage_v

    # Architecture-useful data-rate estimate.
    # If tau <= 0.2 UI, then data_rate <= 0.2 / tau.
    rc_limited_data_rate_bps = (
        cfg.allowed_rc_fraction_of_ui / tau_s
        if tau_s > 0
        else float("inf")
    )

    # Clamp to a practical cap because this RC-only model can produce unrealistically
    # high data rates when C is tiny. Real data rate is limited by driver, receiver,
    # clocking, jitter, crosstalk, equalization, and package.
    practical_data_rate_Gbps = min(
        rc_limited_data_rate_bps / 1e9,
        cfg.max_practical_data_rate_Gbps_cap,
    )

    aggregate_bandwidth_TB_s = (
        practical_data_rate_Gbps
        * 1e9
        * cfg.vertical_lanes_per_bus_column
        / 8.0
        / 1e12
    )

    # Dynamic power at the estimated practical lane data rate.
    # Worst-case toggle model assumes one effective toggle per bit.
    lane_dynamic_power_W = e_toggle_j * practical_data_rate_Gbps * 1e9
    aggregate_dynamic_power_W = lane_dynamic_power_W * cfg.vertical_lanes_per_bus_column

    # Very crude crosstalk proxy:
    # Higher C and tighter pitch increase concern. This is only a ranking aid.
    crosstalk_proxy = (c_f / 1e-15) / (cfg.via_pitch_m / 1e-6)

    return {
        "material": material.name,
        "model_validity": "order-of-magnitude only; field-solver extraction required",
        "via_diameter_um": cfg.via_diameter_m / 1e-6,
        "via_length_um": cfg.via_length_m / 1e-6,
        "via_pitch_um": cfg.via_pitch_m / 1e-6,
        "eps_r": cfg.eps_r,
        "coupling_factor": cfg.coupling_factor,
        "R_ohm": r_ohm,
        "C_fF": c_f / 1e-15,
        "L_pH": l_h / 1e-12,
        "RC_tau_ps": tau_s / 1e-12,
        "RC_f3dB_GHz": f_3db_hz / 1e9,
        "RC_limited_data_rate_Gbps": rc_limited_data_rate_bps / 1e9,
        "practical_data_rate_Gbps_capped": practical_data_rate_Gbps,
        "vertical_lanes_per_bus_column": cfg.vertical_lanes_per_bus_column,
        "aggregate_bandwidth_TB_s": aggregate_bandwidth_TB_s,
        "toggle_energy_fJ_per_lane": e_toggle_j / 1e-15,
        "lane_dynamic_power_mW": lane_dynamic_power_W * 1e3,
        "aggregate_dynamic_power_W": aggregate_dynamic_power_W,
        "crosstalk_proxy_relative": crosstalk_proxy,
    }


def run_vertical_bus_model() -> List[Dict[str, float | str]]:
    cfg = VerticalBusConfig()
    rows = [estimate_via_params(m, cfg) for m in MATERIALS]
    write_csv(OUTDIR / "vertical_bus_summary.csv", rows)

    # -------------------------------------------------------------------------
    # Impedance plot for a gold via as example.
    # This is a diagnostic, not a full channel model.
    # -------------------------------------------------------------------------
    gold_params = estimate_via_params(MATERIALS[0], cfg)
    r = float(gold_params["R_ohm"])
    c = float(gold_params["C_fF"]) * 1e-15
    l = float(gold_params["L_pH"]) * 1e-12

    freqs = np.logspace(6, 11, 500)  # 1 MHz to 100 GHz
    omega = 2 * np.pi * freqs

    z_series = r + 1j * omega * l
    z_cap = 1 / (1j * omega * c)
    z_total = z_series + z_cap

    plt.figure(figsize=(9, 6))
    plt.loglog(freqs / 1e9, np.abs(z_total), label="|R + jωL + 1/(jωC)|")
    plt.loglog(freqs / 1e9, np.abs(z_series), label="|R + jωL|")
    plt.xlabel("Frequency [GHz]")
    plt.ylabel("Impedance magnitude [ohm]")
    plt.title("Vertical Bus First-Order Impedance Diagnostic\n(order-of-magnitude only)")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "vertical_bus_impedance.png", dpi=200)
    plt.close()

    # -------------------------------------------------------------------------
    # Architecture-useful data-rate and aggregate bandwidth plot.
    # -------------------------------------------------------------------------
    materials = [r["material"] for r in rows]
    data_rate = [float(r["practical_data_rate_Gbps_capped"]) for r in rows]
    agg_bw = [float(r["aggregate_bandwidth_TB_s"]) for r in rows]

    plt.figure(figsize=(9, 6))
    x = np.arange(len(materials))
    width = 0.35

    plt.bar(x - width / 2, data_rate, width, label="Per-lane data rate [Gbps, capped]")
    plt.bar(x + width / 2, agg_bw, width, label="Aggregate bus bandwidth [TB/s]")
    plt.xticks(x, materials)
    plt.ylabel("Gbps per lane / TB/s aggregate")
    plt.title("Vertical Bus Architecture-Level Bandwidth Estimate")
    plt.grid(True, axis="y", linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "vertical_bus_bandwidth.png", dpi=200)
    plt.close()

    # -------------------------------------------------------------------------
    # Sweep via pitch to show sensitivity.
    # -------------------------------------------------------------------------
    pitch_rows: List[Dict[str, float | str]] = []
    pitch_um_values = np.array([2, 3, 5, 8, 10, 15, 20], dtype=float)

    for pitch_um in pitch_um_values:
        sweep_cfg = VerticalBusConfig(
            via_diameter_m=cfg.via_diameter_m,
            via_length_m=cfg.via_length_m,
            via_pitch_m=pitch_um * 1e-6,
            eps_r=cfg.eps_r,
            voltage_v=cfg.voltage_v,
            coupling_factor=cfg.coupling_factor,
            allowed_rc_fraction_of_ui=cfg.allowed_rc_fraction_of_ui,
            max_practical_data_rate_Gbps_cap=cfg.max_practical_data_rate_Gbps_cap,
            vertical_lanes_per_bus_column=cfg.vertical_lanes_per_bus_column,
        )

        for m in MATERIALS:
            p = estimate_via_params(m, sweep_cfg)
            pitch_rows.append({
                "material": m.name,
                "pitch_um": pitch_um,
                "C_fF": p["C_fF"],
                "RC_tau_ps": p["RC_tau_ps"],
                "practical_data_rate_Gbps_capped": p["practical_data_rate_Gbps_capped"],
                "aggregate_bandwidth_TB_s": p["aggregate_bandwidth_TB_s"],
                "crosstalk_proxy_relative": p["crosstalk_proxy_relative"],
            })

    write_csv(OUTDIR / "vertical_bus_pitch_sweep.csv", pitch_rows)

    plt.figure(figsize=(9, 6))
    
    # Crosstalk proxy is geometry/dielectric dependent, not metal-resistivity dependent.
    # Therefore only one curve is plotted.
    xs = []
    ys = []
    
    for pitch_um in pitch_um_values:
        sweep_cfg = VerticalBusConfig(
            via_diameter_m=cfg.via_diameter_m,
            via_length_m=cfg.via_length_m,
            via_pitch_m=pitch_um * 1e-6,
            eps_r=cfg.eps_r,
            voltage_v=cfg.voltage_v,
            coupling_factor=cfg.coupling_factor,
            allowed_rc_fraction_of_ui=cfg.allowed_rc_fraction_of_ui,
            max_practical_data_rate_Gbps_cap=cfg.max_practical_data_rate_Gbps_cap,
            vertical_lanes_per_bus_column=cfg.vertical_lanes_per_bus_column,
        )
    
        # Use Gold only as a representative geometry case.
        # The capacitance/crosstalk proxy is identical for Gold, Copper, and Tungsten
        # under this simplified model.
        p = estimate_via_params(MATERIALS[0], sweep_cfg)
        xs.append(pitch_um)
        ys.append(p["crosstalk_proxy_relative"])
    
    plt.plot(xs, ys, marker="o", label="Geometry-only coupling proxy")
    
    plt.xlabel("Via pitch [µm]")
    plt.ylabel("Relative crosstalk proxy [C_fF / pitch_µm]")
    plt.title("Vertical Bus Coupling Sensitivity Proxy\n(geometry-only; not a field solver)")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "vertical_bus_pitch_crosstalk_proxy.png", dpi=200)
    plt.close()

    plt.figure(figsize=(9, 6))
    
    for m in MATERIALS:
        xs = [r["pitch_um"] for r in pitch_rows if r["material"] == m.name]
        ys = [r["RC_tau_ps"] for r in pitch_rows if r["material"] == m.name]
        plt.plot(xs, ys, marker="o", label=m.name)
    
    plt.xlabel("Via pitch [µm]")
    plt.ylabel("RC time constant [ps]")
    plt.title("Vertical Bus RC Delay Sensitivity by Via Material")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "vertical_bus_pitch_rc_tau.png", dpi=200)
    plt.close()

    return rows


# =============================================================================
# Model 3: 3D Thermal-Resistance Estimate with Hotspot Factor
# =============================================================================

@dataclass
class ThermalConfig:
    ambient_C: float = 25.0
    max_junction_C: float = 85.0
    active_area_cm2: float = 25.0

    # First-order Rtheta assumptions.
    # These are placeholders and must be replaced with coupon-measured data.
    rtheta_package_K_W: float = 0.08
    rtheta_sink_K_W: float = 0.10
    rtheta_per_active_layer_K_W: float = 0.010
    rtheta_interface_per_layer_K_W: float = 0.006
    rtheta_shield_per_support_K_W: float = 0.015

    support_layer_interval: int = 3

    # Non-uniform activity / buried hotspot multiplier.
    # 1.0 = uniform average heat assumption.
    # 2.0-3.0 = conservative local hotspot estimate.
    hotspot_factors: Tuple[float, ...] = (1.0, 2.0, 3.0)


def estimate_rtheta_total(num_layers: int, cfg: ThermalConfig) -> float:
    support_layers = max(0, math.ceil(num_layers / cfg.support_layer_interval) - 1)
    return (
        cfg.rtheta_package_K_W
        + cfg.rtheta_sink_K_W
        + num_layers * (cfg.rtheta_per_active_layer_K_W + cfg.rtheta_interface_per_layer_K_W)
        + support_layers * cfg.rtheta_shield_per_support_K_W
    )


def max_safe_activity_fraction(
    power_W: float,
    rtheta_K_W: float,
    hotspot_factor: float,
    cfg: ThermalConfig,
) -> float:
    """
    Estimate the maximum sustained activity fraction before hotspot junction exceeds limit.

    T_hotspot = ambient + power * activity_fraction * Rtheta * hotspot_factor

    activity_fraction <= (Tmax - Tambient) / (power * Rtheta * hotspot_factor)
    """
    allowed_delta_C = cfg.max_junction_C - cfg.ambient_C
    denom = power_W * rtheta_K_W * hotspot_factor

    if denom <= 0:
        return 1.0

    return max(0.0, min(1.0, allowed_delta_C / denom))


def run_thermal_model() -> List[Dict[str, float | int | str]]:
    cfg = ThermalConfig()

    # From VHS-C target-class projection in the document.
    peak_ops_s = 1.67e18

    # Directly maps to the document's Eop sensitivity table.
    eop_fJ_list = [0.2, 1.0, 10.0, 100.0]

    # Directly maps to the Section 14.4 layer-count comparison.
    layer_counts = [1, 3, 10, 50]

    rows: List[Dict[str, float | int | str]] = []

    for n in layer_counts:
        rtheta = estimate_rtheta_total(n, cfg)

        for eop_fJ in eop_fJ_list:
            power_W = peak_ops_s * eop_fJ * 1e-15
            avg_deltaT_C = power_W * rtheta
            avg_junction_C = cfg.ambient_C + avg_deltaT_C
            heat_flux_W_cm2 = power_W / cfg.active_area_cm2

            for hotspot_factor in cfg.hotspot_factors:
                hotspot_deltaT_C = avg_deltaT_C * hotspot_factor
                hotspot_junction_C = cfg.ambient_C + hotspot_deltaT_C

                safe_hotspot = "YES" if hotspot_junction_C <= cfg.max_junction_C else "NO"

                activity_safe = max_safe_activity_fraction(
                    power_W=power_W,
                    rtheta_K_W=rtheta,
                    hotspot_factor=hotspot_factor,
                    cfg=cfg,
                )

                rows.append({
                    "layers": n,
                    "Eop_fJ": eop_fJ,
                    "power_W": power_W,
                    "Rtheta_K_W": rtheta,
                    "heat_flux_W_cm2": heat_flux_W_cm2,
                    "hotspot_factor": hotspot_factor,
                    "avg_deltaT_C": avg_deltaT_C,
                    "avg_junction_C": avg_junction_C,
                    "hotspot_deltaT_C": hotspot_deltaT_C,
                    "hotspot_junction_C": hotspot_junction_C,
                    "below_85C_hotspot": safe_hotspot,
                    "max_safe_activity_fraction": activity_safe,
                    "max_safe_activity_percent": activity_safe * 100.0,
                })

    write_csv(OUTDIR / "thermal_summary.csv", rows)

    # -------------------------------------------------------------------------
    # Plot 1: Average ΔT vs layer count, same as previous model.
    # -------------------------------------------------------------------------
    plt.figure(figsize=(9, 6))
    for eop_fJ in eop_fJ_list:
        xs = []
        ys = []
        for n in layer_counts:
            rtheta = estimate_rtheta_total(n, cfg)
            power_W = peak_ops_s * eop_fJ * 1e-15
            xs.append(n)
            ys.append(power_W * rtheta)

        plt.plot(xs, ys, marker="o", label=f"Eop = {eop_fJ} fJ/op")

    plt.axhline(
        cfg.max_junction_C - cfg.ambient_C,
        linestyle="--",
        label="Allowed average ΔT to 85°C",
    )
    plt.xlabel("Active layer count")
    plt.ylabel("Average temperature rise ΔT [°C]")
    plt.title("VHS-C First-Order Average Thermal Resistance Estimate")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "thermal_deltaT_plot.png", dpi=200)
    plt.close()

    # -------------------------------------------------------------------------
    # Plot 2: Hotspot junction temperature for selected Eop values.
    # -------------------------------------------------------------------------
    plt.figure(figsize=(9, 6))

    for hotspot_factor in cfg.hotspot_factors:
        for eop_fJ in [0.2, 1.0]:
            xs = []
            ys = []
            for n in layer_counts:
                rtheta = estimate_rtheta_total(n, cfg)
                power_W = peak_ops_s * eop_fJ * 1e-15
                avg_deltaT_C = power_W * rtheta
                hotspot_junction_C = cfg.ambient_C + avg_deltaT_C * hotspot_factor

                xs.append(n)
                ys.append(hotspot_junction_C)

            plt.plot(
                xs,
                ys,
                marker="o",
                label=f"Eop={eop_fJ} fJ/op, hotspot={hotspot_factor}×",
            )

    plt.axhline(cfg.max_junction_C, linestyle="--", label="85°C limit")
    plt.xlabel("Active layer count")
    plt.ylabel("Hotspot junction temperature [°C]")
    plt.title("VHS-C Hotspot-Aware Thermal Estimate")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "thermal_hotspot_plot.png", dpi=200)
    plt.close()

    # -------------------------------------------------------------------------
    # Plot 3: Maximum safe activity fraction.
    # -------------------------------------------------------------------------
    plt.figure(figsize=(9, 6))

    for hotspot_factor in cfg.hotspot_factors:
        for eop_fJ in [0.2, 1.0, 10.0]:
            xs = []
            ys = []
            for n in layer_counts:
                rtheta = estimate_rtheta_total(n, cfg)
                power_W = peak_ops_s * eop_fJ * 1e-15
                activity_safe = max_safe_activity_fraction(
                    power_W=power_W,
                    rtheta_K_W=rtheta,
                    hotspot_factor=hotspot_factor,
                    cfg=cfg,
                )
                xs.append(n)
                ys.append(activity_safe * 100.0)

            plt.plot(
                xs,
                ys,
                marker="o",
                label=f"Eop={eop_fJ} fJ/op, hotspot={hotspot_factor}×",
            )

    plt.xlabel("Active layer count")
    plt.ylabel("Maximum safe sustained activity [%]")
    plt.title("VHS-C Safe Activity Envelope Under Hotspot Constraint")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "thermal_safe_activity_plot.png", dpi=200)
    plt.close()

    return rows


# =============================================================================
# Model 4: 3D NoC fault-injection simulation with spare-node remapping
# =============================================================================

Coord = Tuple[int, int, int]


@dataclass
class NoCConfig:
    # More representative VHS-C mesh.
    # 8x8x10 = 640 nodes. For aspirational layer depth, try z=50.
    x: int = 8
    y: int = 8
    z: int = 10

    trials: int = 100
    sample_pairs_per_trial: int = 300

    # Fraction of physical nodes reserved as spare/remap targets.
    # Example: 0.15 means 85% active logical nodes, 15% spare nodes.
    spare_fraction: float = 0.15

    seed: int = 42


def all_nodes(cfg: NoCConfig) -> List[Coord]:
    return [(x, y, z) for x in range(cfg.x) for y in range(cfg.y) for z in range(cfg.z)]


def neighbors(node: Coord, cfg: NoCConfig) -> Iterable[Coord]:
    x, y, z = node
    candidates = [
        (x + 1, y, z), (x - 1, y, z),
        (x, y + 1, z), (x, y - 1, z),
        (x, y, z + 1), (x, y, z - 1),
    ]
    for nx, ny, nz in candidates:
        if 0 <= nx < cfg.x and 0 <= ny < cfg.y and 0 <= nz < cfg.z:
            yield (nx, ny, nz)


def all_edges(cfg: NoCConfig) -> List[Tuple[Coord, Coord]]:
    edges = set()
    for n in all_nodes(cfg):
        for m in neighbors(n, cfg):
            a, b = sorted([n, m])
            edges.add((a, b))
    return list(edges)


def manhattan(a: Coord, b: Coord) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def bfs_component(
    start: Coord,
    alive_nodes: set[Coord],
    alive_edges: set[Tuple[Coord, Coord]],
    cfg: NoCConfig,
) -> set[Coord]:
    q = deque([start])
    visited = {start}

    while q:
        n = q.popleft()
        for m in neighbors(n, cfg):
            if m not in alive_nodes or m in visited:
                continue
            a, b = sorted([n, m])
            if (a, b) not in alive_edges:
                continue
            visited.add(m)
            q.append(m)

    return visited


def build_components(
    alive_nodes: set[Coord],
    alive_edges: set[Tuple[Coord, Coord]],
    cfg: NoCConfig,
) -> Tuple[List[set[Coord]], Dict[Coord, int]]:
    unvisited = set(alive_nodes)
    components: List[set[Coord]] = []
    node_to_component: Dict[Coord, int] = {}

    while unvisited:
        start = next(iter(unvisited))
        comp = bfs_component(start, alive_nodes, alive_edges, cfg)
        comp_id = len(components)
        components.append(comp)

        for n in comp:
            node_to_component[n] = comp_id

        unvisited -= comp

    return components, node_to_component


def shortest_path_length(
    src: Coord,
    dst: Coord,
    alive_nodes: set[Coord],
    alive_edges: set[Tuple[Coord, Coord]],
    cfg: NoCConfig,
) -> int | None:
    if src == dst:
        return 0

    q = deque([(src, 0)])
    visited = {src}

    while q:
        n, d = q.popleft()
        for m in neighbors(n, cfg):
            if m not in alive_nodes or m in visited:
                continue
            a, b = sorted([n, m])
            if (a, b) not in alive_edges:
                continue
            if m == dst:
                return d + 1
            visited.add(m)
            q.append((m, d + 1))

    return None


def choose_active_and_spare_nodes(
    cfg: NoCConfig,
    rng: random.Random,
) -> Tuple[set[Coord], set[Coord]]:
    """
    Split the physical mesh into active nodes and spare nodes.

    Active nodes represent compute/memory/router resources normally exposed to workloads.
    Spare nodes represent redundant VHS-C regions available for degraded-mode remapping.
    """
    nodes = all_nodes(cfg)
    rng.shuffle(nodes)

    spare_count = int(round(len(nodes) * cfg.spare_fraction))
    spare_nodes = set(nodes[:spare_count])
    active_nodes = set(nodes[spare_count:])

    return active_nodes, spare_nodes


def remap_failed_active_nodes(
    failed_active_nodes: set[Coord],
    alive_spare_nodes: set[Coord],
    alive_nodes: set[Coord],
    alive_edges: set[Tuple[Coord, Coord]],
    node_to_component: Dict[Coord, int],
    cfg: NoCConfig,
) -> Tuple[Dict[Coord, Coord], List[int]]:
    """
    Remap each failed active node to the nearest reachable alive spare node.

    Constraint:
    - A spare can only be used once.
    - The spare must be in a connected component that is reachable from the failed node's
      nearest surviving neighborhood. Since the failed node itself is dead, we estimate
      reachable context by checking components of its live neighbors.

    This is still a first-order model. A more advanced version would include:
    - workload class,
    - memory affinity,
    - thermal zone constraints,
    - remap-table update latency,
    - checkpoint restore cost.
    """
    available_spares = set(alive_spare_nodes)
    remap: Dict[Coord, Coord] = {}
    remap_distances: List[int] = []

    # Sort failed nodes so remapping is deterministic with respect to nearest candidate.
    for failed in sorted(failed_active_nodes):
        # Components reachable from live neighbors of the failed node.
        reachable_components = set()
        for nb in neighbors(failed, cfg):
            if nb in alive_nodes and nb in node_to_component:
                reachable_components.add(node_to_component[nb])

        if not reachable_components:
            continue

        candidates = [
            s for s in available_spares
            if node_to_component.get(s) in reachable_components
        ]

        if not candidates:
            continue

        # Choose nearest spare by Manhattan distance.
        target = min(candidates, key=lambda s: manhattan(failed, s))
        available_spares.remove(target)
        remap[failed] = target
        remap_distances.append(manhattan(failed, target))

    return remap, remap_distances


def run_single_fault_trial_with_remap(
    cfg: NoCConfig,
    node_failure_rate: float,
    link_failure_rate: float,
    rng: random.Random,
) -> Dict[str, float]:
    physical_nodes = set(all_nodes(cfg))
    physical_edges = set(all_edges(cfg))

    active_nodes, spare_nodes = choose_active_and_spare_nodes(cfg, rng)
    active_total = len(active_nodes)

    failed_nodes = {n for n in physical_nodes if rng.random() < node_failure_rate}
    alive_nodes = physical_nodes - failed_nodes

    failed_edges = {e for e in physical_edges if rng.random() < link_failure_rate}
    alive_edges = physical_edges - failed_edges

    alive_active_nodes = active_nodes & alive_nodes
    failed_active_nodes = active_nodes & failed_nodes
    alive_spare_nodes = spare_nodes & alive_nodes

    if not alive_nodes:
        return {
            "raw_usable_fraction": 0.0,
            "remapped_usable_fraction": 0.0,
            "remap_success_fraction": 0.0,
            "mean_remap_distance_hops": float("nan"),
            "largest_component_fraction": 0.0,
            "reachable_pair_fraction_after_remap": 0.0,
            "avg_shortest_path_after_remap": float("nan"),
        }

    components, node_to_component = build_components(alive_nodes, alive_edges, cfg)
    largest_component_fraction = max(len(c) for c in components) / len(physical_nodes)

    remap, remap_distances = remap_failed_active_nodes(
        failed_active_nodes=failed_active_nodes,
        alive_spare_nodes=alive_spare_nodes,
        alive_nodes=alive_nodes,
        alive_edges=alive_edges,
        node_to_component=node_to_component,
        cfg=cfg,
    )

    remapped_count = len(remap)

    raw_usable_fraction = len(alive_active_nodes) / max(active_total, 1)
    remapped_usable_fraction = (len(alive_active_nodes) + remapped_count) / max(active_total, 1)

    remap_success_fraction = (
        remapped_count / len(failed_active_nodes)
        if failed_active_nodes else 1.0
    )

    mean_remap_distance = (
        float(np.mean(remap_distances))
        if remap_distances else float("nan")
    )

    # Logical active set after remapping:
    # - surviving active nodes remain active
    # - failed active nodes that were remapped use spare physical positions
    logical_operating_nodes = set(alive_active_nodes) | set(remap.values())
    logical_operating_list = list(logical_operating_nodes)

    reachable = 0
    path_lengths = []

    if len(logical_operating_list) >= 2:
        for _ in range(cfg.sample_pairs_per_trial):
            a, b = rng.sample(logical_operating_list, 2)
            dist = shortest_path_length(a, b, alive_nodes, alive_edges, cfg)
            if dist is not None:
                reachable += 1
                path_lengths.append(dist)

        reachable_pair_fraction = reachable / cfg.sample_pairs_per_trial
        avg_path = float(np.mean(path_lengths)) if path_lengths else float("nan")
    else:
        reachable_pair_fraction = 0.0
        avg_path = float("nan")

    return {
        "raw_usable_fraction": raw_usable_fraction,
        "remapped_usable_fraction": remapped_usable_fraction,
        "remap_success_fraction": remap_success_fraction,
        "mean_remap_distance_hops": mean_remap_distance,
        "largest_component_fraction": largest_component_fraction,
        "reachable_pair_fraction_after_remap": reachable_pair_fraction,
        "avg_shortest_path_after_remap": avg_path,
    }


def run_noc_fault_model() -> List[Dict[str, float | int]]:
    """
    VHS-C NoC fault model with remapping.

    Failure rates:
    - node failures model failed compute/memory/router blocks
    - link failures model failed VBUS/NoC links

    Remapping:
    - failed active nodes are reassigned to reachable alive spare nodes
    - this approximates VHS-C remap-table behavior
    """
    cfg = NoCConfig(
        x=8,
        y=8,
        z=10,
        trials=50,
        sample_pairs_per_trial=50,
        spare_fraction=0.15,
        seed=42,
    )

    rng = random.Random(cfg.seed)

    failure_rates = [0.00, 0.01, 0.05, 0.10, 0.20]
    rows: List[Dict[str, float | int]] = []

    for fr in failure_rates:
        trial_results = [
            run_single_fault_trial_with_remap(
                cfg=cfg,
                node_failure_rate=fr,
                link_failure_rate=fr,
                rng=rng,
            )
            for _ in range(cfg.trials)
        ]

        def mean_metric(key: str) -> float:
            values = np.array([r[key] for r in trial_results], dtype=float)
            values = values[~np.isnan(values)]
            return float(np.mean(values)) if len(values) else float("nan")

        rows.append({
            "grid_x": cfg.x,
            "grid_y": cfg.y,
            "grid_z": cfg.z,
            "physical_nodes": cfg.x * cfg.y * cfg.z,
            "spare_fraction_percent": cfg.spare_fraction * 100.0,
            "failure_rate_percent": fr * 100.0,
            "mean_raw_usable_fraction": mean_metric("raw_usable_fraction"),
            "mean_remapped_usable_fraction": mean_metric("remapped_usable_fraction"),
            "mean_remap_success_fraction": mean_metric("remap_success_fraction"),
            "mean_remap_distance_hops": mean_metric("mean_remap_distance_hops"),
            "mean_largest_component_fraction": mean_metric("largest_component_fraction"),
            "mean_reachable_pair_fraction_after_remap": mean_metric("reachable_pair_fraction_after_remap"),
            "mean_avg_shortest_path_after_remap": mean_metric("avg_shortest_path_after_remap"),
            "trials": cfg.trials,
        })

    write_csv(OUTDIR / "noc_fault_summary.csv", rows)

    x = [r["failure_rate_percent"] for r in rows]
    raw = [r["mean_raw_usable_fraction"] * 100 for r in rows]
    remap = [r["mean_remapped_usable_fraction"] * 100 for r in rows]
    reach = [r["mean_reachable_pair_fraction_after_remap"] * 100 for r in rows]
    remap_success = [r["mean_remap_success_fraction"] * 100 for r in rows]

    plt.figure(figsize=(9, 6))
    plt.plot(x, raw, marker="o", label="Raw usable active nodes [%]")
    plt.plot(x, remap, marker="s", label="Usable after remapping [%]")
    plt.plot(x, reach, marker="^", label="Reachable operating pairs [%]")
    plt.plot(x, remap_success, marker="d", label="Remap success [% of failed active nodes]")
    plt.xlabel("Injected node/link failure rate [%]")
    plt.ylabel("Survival / remap metric [%]")
    plt.title("VHS-C 3D NoC Fault Injection with Spare-Node Remapping")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "noc_fault_plot.png", dpi=200)
    plt.close()

    plt.figure(figsize=(9, 6))
    path = [r["mean_avg_shortest_path_after_remap"] for r in rows]
    dist = [r["mean_remap_distance_hops"] for r in rows]
    plt.plot(x, path, marker="o", label="Avg logical path after remap [hops]")
    plt.plot(x, dist, marker="s", label="Avg remap distance [Manhattan hops]")
    plt.xlabel("Injected node/link failure rate [%]")
    plt.ylabel("Hops")
    plt.title("VHS-C Remapping Cost and Path-Length Penalty")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTDIR / "noc_remap_cost_plot.png", dpi=200)
    plt.close()

    return rows


# =============================================================================
# Main execution
# =============================================================================

def main() -> None:
    print("\n=== VHS-C Section 14 First-Order Simulation Package ===\n")

    print("[1/4] Running roofline / memory-wall model with data-movement energy...")
    roof_rows = run_roofline_model()
    for r in roof_rows:
        print(
            f"  {r['system']}: peak={r['peak_TOPS']:.1f} TOPS, "
            f"BW={r['bandwidth_TB_s']:.1f} TB/s, "
            f"ridge={r['ridge_point_ops_per_byte']:.2f} ops/byte, "
            f"long_range_fraction={r['long_range_byte_fraction']:.2f}"
        )

    print("\n[2/4] Running vertical-bus RC model...")
    vbus_rows = run_vertical_bus_model()
    for r in vbus_rows:
        print(
            f"  {r['material']}: "
            f"R={r['R_ohm']:.4g} ohm, "
            f"C={r['C_fF']:.3g} fF, "
            f"L={r['L_pH']:.3g} pH, "
            f"tau={r['RC_tau_ps']:.3g} ps, "
            f"RC_rate={r['RC_limited_data_rate_Gbps']:.3g} Gbps, "
            f"capped_rate={r['practical_data_rate_Gbps_capped']:.3g} Gbps, "
            f"aggBW={r['aggregate_bandwidth_TB_s']:.3g} TB/s"
        )
    print("  NOTE: capacitance is order-of-magnitude only; field-solver extraction is required.")

    print("\n[3/4] Running thermal-resistance estimate with hotspot factor...")
    thermal_rows = run_thermal_model()
    
    for r in thermal_rows:
        if (
            r["Eop_fJ"] in (0.2, 1.0)
            and r["layers"] in (1, 10, 50)
            and r["hotspot_factor"] in (1.0, 3.0)
        ):
            print(
                f"  layers={r['layers']:>2}, "
                f"Eop={r['Eop_fJ']:>4} fJ/op, "
                f"hotspot={r['hotspot_factor']:.1f}x: "
                f"P={r['power_W']:.1f} W, "
                f"Tavg={r['avg_junction_C']:.1f} °C, "
                f"Thot={r['hotspot_junction_C']:.1f} °C, "
                f"below85={r['below_85C_hotspot']}, "
                f"safe_activity={r['max_safe_activity_percent']:.1f}%"
            )
    
    print("\n[4/4] Running NoC fault-injection model with remapping...")
    noc_rows = run_noc_fault_model()
    
    print("  NoC results by injected failure rate:")
    print("  fail% | raw usable | remapped usable | remap success | reachable pairs | avg path")
    print("  ------+------------+-----------------+---------------+-----------------+---------")
    
    for r in noc_rows:
        print(
            f"  {r['failure_rate_percent']:>5.0f}% | "
            f"{r['mean_raw_usable_fraction']*100:>9.1f}% | "
            f"{r['mean_remapped_usable_fraction']*100:>14.1f}% | "
            f"{r['mean_remap_success_fraction']*100:>12.1f}% | "
            f"{r['mean_reachable_pair_fraction_after_remap']*100:>14.1f}% | "
            f"{r['mean_avg_shortest_path_after_remap']:>7.2f}"
        )

    print("\nOutputs written to:")
    print(f"  {OUTDIR.resolve()}")
    print("\nGenerated files:")
    for p in sorted(OUTDIR.iterdir()):
        print(f"  - {p.name}")

    print("\nNOTE:")
    print("  These are first-order exploratory models only.")
    print("  Replace placeholder bandwidth, thermal, via, and NoC parameters")
    print("  with literature-backed values or measured coupon data before using")
    print("  the results as evidence in the VHS-C paper.\n")


if __name__ == "__main__":
    main()
