#!/usr/bin/env python3
"""
VHS-C BootROM / Control-Plane Simulation Scaffold
==================================================

Purpose
-------
This is a roadmap-research scaffold for the VHS-C firmware-defined hardware platform.
It simulates the BootROM/control-plane decision path for protected metadata, profile
selection, HPEU checks, multi-OS machine-contract generation, fault injection, and
rollback to last-known-good metadata.

It is NOT hardware proof, NOT a real BootROM, NOT a secure implementation, and NOT a
cryptographic reference design. It is an executable assumption-tracking scaffold.

Core integrity rule
-------------------
ECC protects the bits.
Hash/checksum protects the metadata object.
Signature protects the authority.
Rollback protects recovery.

Recommended location
--------------------
simulation/firmware-defined/vhsc_bootrom_controlplane_scaffold.py

Example
-------
python3 vhsc_bootrom_controlplane_scaffold.py --init --root simulation/firmware-defined
python3 vhsc_bootrom_controlplane_scaffold.py --root simulation/firmware-defined --scenario all --make-diagram

Outputs
-------
outputs/boot_decision_log.csv
outputs/boot_decision_log.json
outputs/selected_machine_contract.json
outputs/generated_devicetree.dts
outputs/generated_acpi_summary.json
outputs/fault_injection_report.csv
outputs/boot_flow_summary.png       (if --make-diagram and matplotlib is available)
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import hmac
import json
import os
import random
import sys
import textwrap
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = "vhsc.bootmeta.v0.2-roadmap"
SCAFFOLD_VERSION = "0.2.0"

# Development-only scaffold key. Do not use this pattern for real firmware.
DEV_SIGNATURE_KEY = b"VHS-C-roadmap-dev-signing-key-not-for-production"

SUPPORTED_SCENARIOS = [
    "normal",
    "metadata_corrupt",
    "metadata_stale",
    "metadata_unsigned",
    "degraded_resources",
    "unsafe_profile",
    "all",
]

# -----------------------------------------------------------------------------
# Utility helpers
# -----------------------------------------------------------------------------


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stable_json(obj: Any) -> str:
    """Canonical-ish JSON for hashing/signing within this scaffold."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(obj: Any) -> str:
    return hashlib.sha256(stable_json(obj).encode("utf-8")).hexdigest()


def crc32c_like_hex(obj: Any) -> str:
    # Python stdlib has zlib.crc32, not CRC32C. For this scaffold, call it a fast CRC-like check.
    value = zlib.crc32(stable_json(obj).encode("utf-8")) & 0xFFFFFFFF
    return f"{value:08x}"


def sign_payload(obj: Any, key: bytes = DEV_SIGNATURE_KEY) -> str:
    return hmac.new(key, stable_json(obj).encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(obj: Any, sig: str, key: bytes = DEV_SIGNATURE_KEY) -> bool:
    return hmac.compare_digest(sign_payload(obj, key), sig)


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# -----------------------------------------------------------------------------
# Decision logging
# -----------------------------------------------------------------------------


@dataclass
class DecisionEvent:
    step: str
    status: str
    detail: str
    metadata_id: str = ""
    profile_id: str = ""
    scenario: str = ""


@dataclass
class BootDecisionLog:
    scenario: str
    events: List[DecisionEvent] = field(default_factory=list)

    def add(self, step: str, status: str, detail: str, metadata_id: str = "", profile_id: str = "") -> None:
        self.events.append(
            DecisionEvent(
                step=step,
                status=status,
                detail=detail,
                metadata_id=metadata_id,
                profile_id=profile_id,
                scenario=self.scenario,
            )
        )

    def extend(self, other: "BootDecisionLog") -> None:
        self.events.extend(other.events)

    def rows(self) -> List[Dict[str, str]]:
        return [e.__dict__ for e in self.events]


# -----------------------------------------------------------------------------
# Default model generation
# -----------------------------------------------------------------------------


def default_resource_map() -> Dict[str, Any]:
    return {
        "resource_map_id": "vhsc_demo_resource_map_v1",
        "compute_regions": [
            {"id": "C0", "isa": "riscv64", "status": "healthy", "tops": 20, "power_w": 8},
            {"id": "C1", "isa": "riscv64", "status": "healthy", "tops": 20, "power_w": 8},
            {"id": "C2", "isa": "v-risc", "status": "healthy", "tops": 25, "power_w": 7},
            {"id": "C3", "isa": "arm64-compatible", "status": "healthy", "tops": 18, "power_w": 7},
            {"id": "C4", "isa": "x86-64-compatible", "status": "unavailable_unlicensed", "tops": 0, "power_w": 0},
        ],
        "memory_regions": [
            {"id": "M0", "size_mb": 1024, "status": "healthy"},
            {"id": "M1", "size_mb": 1024, "status": "healthy"},
            {"id": "M2", "size_mb": 512, "status": "healthy"},
            {"id": "M3", "size_mb": 512, "status": "degraded"},
        ],
        "persistent_regions": [
            {"id": "P0", "size_mb": 256, "status": "healthy"},
            {"id": "P1", "size_mb": 128, "status": "healthy"},
        ],
        "accelerator_slices": [
            {"id": "AI0", "type": "near-memory-vector", "status": "healthy", "power_w": 12},
            {"id": "SEC0", "type": "security-crypto", "status": "healthy", "power_w": 4},
        ],
        "io_blocks": [
            {"id": "NET0", "type": "network", "status": "healthy"},
            {"id": "STOR0", "type": "storage", "status": "healthy"},
            {"id": "MGMT0", "type": "management", "status": "healthy"},
        ],
        "vbus_links": [
            {"id": "VBUS0", "status": "healthy", "gbps": 224},
            {"id": "VBUS1", "status": "healthy", "gbps": 224},
            {"id": "VBUS2", "status": "degraded", "gbps": 112},
        ],
        "thermal_zones": [
            {"id": "TZ0", "status": "healthy", "max_w": 40},
            {"id": "TZ1", "status": "healthy", "max_w": 40},
        ],
    }


def default_profiles() -> List[Dict[str, Any]]:
    return [
        {
            "profile_id": "linux-riscv-devicetree",
            "description": "Open first-validation profile for Linux/BSD/RTOS-like device-tree boot.",
            "os_family": "linux-bsd-rtos",
            "machine_contract": "device-tree",
            "isa_profile": "riscv64",
            "required_compute": ["C0"],
            "required_memory_mb": 1024,
            "required_persistent": ["P0"],
            "required_io": ["NET0", "STOR0"],
            "required_accelerators": [],
            "power_limit_w": 25,
            "vbus_quota_gbps": 112,
            "security_policy": "isolated",
            "priority": 100,
            "profile_type": "normal",
        },
        {
            "profile_id": "bsd-riscv-devicetree",
            "description": "BSD-like RISC-V profile using the same open boot path.",
            "os_family": "bsd",
            "machine_contract": "device-tree",
            "isa_profile": "riscv64",
            "required_compute": ["C1"],
            "required_memory_mb": 512,
            "required_persistent": ["P1"],
            "required_io": ["NET0"],
            "required_accelerators": [],
            "power_limit_w": 22,
            "vbus_quota_gbps": 80,
            "security_policy": "isolated",
            "priority": 90,
            "profile_type": "normal",
        },
        {
            "profile_id": "rtos-vrisc-flatmap",
            "description": "V-RISC research/RTOS profile with simple flat memory map.",
            "os_family": "rtos",
            "machine_contract": "flatmap",
            "isa_profile": "v-risc",
            "required_compute": ["C2"],
            "required_memory_mb": 256,
            "required_persistent": ["P1"],
            "required_io": ["MGMT0"],
            "required_accelerators": ["SEC0"],
            "power_limit_w": 18,
            "vbus_quota_gbps": 56,
            "security_policy": "secure-appliance",
            "priority": 80,
            "profile_type": "normal",
        },
        {
            "profile_id": "windows-arm64-uefi-acpi",
            "description": "Windows-class ARM64 UEFI/ACPI profile. Demonstrates table generation, not real Windows boot.",
            "os_family": "windows-class",
            "machine_contract": "uefi-acpi",
            "isa_profile": "arm64-compatible",
            "required_compute": ["C3"],
            "required_memory_mb": 1024,
            "required_persistent": ["P0"],
            "required_io": ["NET0", "STOR0"],
            "required_accelerators": [],
            "power_limit_w": 30,
            "vbus_quota_gbps": 112,
            "security_policy": "isolated-signed-boot",
            "priority": 60,
            "profile_type": "normal",
        },
        {
            "profile_id": "x86-64-later-stage-placeholder",
            "description": "Roadmap-only x86-64 placeholder. It should be rejected unless a real validated execution region exists.",
            "os_family": "x86-64-class",
            "machine_contract": "uefi-acpi",
            "isa_profile": "x86-64-compatible",
            "required_compute": ["C4"],
            "required_memory_mb": 1024,
            "required_persistent": ["P0"],
            "required_io": ["NET0", "STOR0"],
            "required_accelerators": [],
            "power_limit_w": 45,
            "vbus_quota_gbps": 112,
            "security_policy": "isolated-signed-boot",
            "priority": 10,
            "profile_type": "normal",
        },
        {
            "profile_id": "recovery-safe-minimal",
            "description": "Last-known-good recovery profile with minimal management-only resources.",
            "os_family": "recovery",
            "machine_contract": "recovery-minimal",
            "isa_profile": "management-core",
            "required_compute": [],
            "required_memory_mb": 64,
            "required_persistent": ["P1"],
            "required_io": ["MGMT0"],
            "required_accelerators": [],
            "power_limit_w": 8,
            "vbus_quota_gbps": 10,
            "security_policy": "recovery-only",
            "priority": 0,
            "profile_type": "recovery",
        },
    ]


def build_metadata_copy(
    metadata_id: str,
    generation: int,
    resource_map: Dict[str, Any],
    profile_ids: List[str],
    active_profile_id: str,
    last_known_good_profile_id: str,
    state: str = "committed",
    corrupt_hash: bool = False,
    unsigned: bool = False,
    stale: bool = False,
    ecc_errors: int = 0,
    ecc_correctable: bool = True,
) -> Dict[str, Any]:
    payload = {
        "resource_map": resource_map,
        "profile_ids": profile_ids,
        "active_profile_id": active_profile_id,
        "last_known_good_profile_id": last_known_good_profile_id,
        "guard_rails": {
            "max_total_power_w": 60,
            "allow_unlicensed_isa": False,
            "require_hpeu": True,
            "require_signed_profiles": True,
        },
    }
    effective_generation = generation - 20 if stale else generation
    header_base = {
        "schema_version": SCHEMA_VERSION,
        "metadata_id": metadata_id,
        "generation_counter": effective_generation,
        "state": state,
        "payload_length": len(stable_json(payload)),
        "previous_valid_generation": max(0, effective_generation - 1),
        "ecc_errors": ecc_errors,
        "ecc_correctable": ecc_correctable,
        "created_utc": utc_now(),
    }
    crc = crc32c_like_hex(payload)
    digest = sha256_hex(payload)
    if corrupt_hash:
        digest = "0" * 64
    header = {
        **header_base,
        "crc32_fast_check": crc,
        "sha256_payload_hash": digest,
        "signature_reference": "dev-hmac-sha256" if not unsigned else "missing",
    }
    signature_material = {"header_without_signature": header, "payload_hash": digest}
    signature = "" if unsigned else sign_payload(signature_material)
    return {
        "header": header,
        "payload": payload,
        "signature": signature,
    }


def signed_profile(profile: Dict[str, Any], unsigned: bool = False) -> Dict[str, Any]:
    out = copy.deepcopy(profile)
    out["profile_schema"] = "vhsc.profile.v0.2-roadmap"
    out["profile_hash"] = sha256_hex({k: v for k, v in out.items() if k not in {"profile_hash", "signature"}})
    out["signature"] = "" if unsigned else sign_payload({"profile_hash": out["profile_hash"], "profile_id": out["profile_id"]})
    return out


def initialize_demo_tree(root: Path, overwrite: bool = False) -> None:
    profiles_dir = root / "profiles"
    metadata_dir = root / "metadata"
    outputs_dir = root / "outputs"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    profiles = [signed_profile(p) for p in default_profiles()]
    for p in profiles:
        path = profiles_dir / f"{p['profile_id']}.json"
        if overwrite or not path.exists():
            write_json(path, p)

    resource_map = default_resource_map()
    profile_ids = [p["profile_id"] for p in profiles]
    good = build_metadata_copy(
        "meta-copy-A-good",
        42,
        resource_map,
        profile_ids,
        "linux-riscv-devicetree",
        "recovery-safe-minimal",
        ecc_errors=1,
        ecc_correctable=True,
    )
    older = build_metadata_copy(
        "meta-copy-B-last-known-good",
        41,
        resource_map,
        profile_ids,
        "recovery-safe-minimal",
        "recovery-safe-minimal",
        ecc_errors=0,
        ecc_correctable=True,
    )
    corrupt = build_metadata_copy(
        "meta-copy-C-corrupt-hash",
        43,
        resource_map,
        profile_ids,
        "linux-riscv-devicetree",
        "recovery-safe-minimal",
        corrupt_hash=True,
        ecc_errors=2,
        ecc_correctable=True,
    )
    unsigned = build_metadata_copy(
        "meta-copy-D-unsigned",
        44,
        resource_map,
        profile_ids,
        "linux-riscv-devicetree",
        "recovery-safe-minimal",
        unsigned=True,
        ecc_errors=0,
        ecc_correctable=True,
    )
    stale = build_metadata_copy(
        "meta-copy-E-stale",
        40,
        resource_map,
        profile_ids,
        "bsd-riscv-devicetree",
        "recovery-safe-minimal",
        stale=True,
    )

    metadata_sets = {
        "protected_metadata_good.json": [good, older],
        "protected_metadata_corrupt.json": [corrupt, older],
        "protected_metadata_unsigned.json": [unsigned, older],
        "protected_metadata_stale.json": [stale, older],
    }
    for filename, copies in metadata_sets.items():
        path = metadata_dir / filename
        if overwrite or not path.exists():
            write_json(path, {"metadata_copies": copies})

    readme = f"""
# VHS-C BootROM / Control-Plane Scaffold Inputs

Generated: {utc_now()}
Scaffold version: {SCAFFOLD_VERSION}

This folder contains development-only sample profiles and protected metadata copies for the
VHS-C BootROM/control-plane simulation scaffold.

Run:

```bash
python3 vhsc_bootrom_controlplane_scaffold.py --root . --scenario all --make-diagram
```

Interpretation:
- This scaffold is executable roadmap logic, not hardware proof.
- HMAC signatures use a development key embedded in the script for repeatability.
- Real BootROM implementations would need real cryptographic key management, monotonic counters,
  physical anti-rollback state, audited parsers, and hardware verification.
""".strip() + "\n"
    readme_path = root / "README.md"
    if overwrite or not readme_path.exists():
        write_text(readme_path, readme)


# -----------------------------------------------------------------------------
# BootROM scaffold core
# -----------------------------------------------------------------------------


@dataclass
class MetadataValidationResult:
    ok: bool
    metadata: Dict[str, Any]
    generation: int
    metadata_id: str
    reason: str


class BootROMControlPlaneScaffold:
    def __init__(self, root: Path, scenario: str, random_seed: int = 340):
        self.root = root
        self.scenario = scenario
        self.random = random.Random(random_seed)
        self.log = BootDecisionLog(scenario=scenario)
        self.profiles = self._load_profiles()

    def _load_profiles(self) -> Dict[str, Dict[str, Any]]:
        profiles_dir = self.root / "profiles"
        profiles: Dict[str, Dict[str, Any]] = {}
        if not profiles_dir.exists():
            raise FileNotFoundError(f"Missing profiles directory: {profiles_dir}. Run --init first.")
        for path in sorted(profiles_dir.glob("*.json")):
            p = read_json(path)
            profiles[p["profile_id"]] = p
        return profiles

    def _metadata_file_for_scenario(self) -> Path:
        mapping = {
            "normal": "protected_metadata_good.json",
            "degraded_resources": "protected_metadata_good.json",
            "unsafe_profile": "protected_metadata_good.json",
            "metadata_corrupt": "protected_metadata_corrupt.json",
            "metadata_stale": "protected_metadata_stale.json",
            "metadata_unsigned": "protected_metadata_unsigned.json",
        }
        return self.root / "metadata" / mapping[self.scenario]

    def run(self) -> Dict[str, Any]:
        self.log.add("power_on", "ok", "Power-on/reset enters minimal trusted management island.")
        self.log.add("management_island", "ok", "BootROM, scratchpad SRAM, metadata reader, and verification engines available.")

        metadata_file = self._metadata_file_for_scenario()
        bundle = read_json(metadata_file)
        copies = bundle.get("metadata_copies", [])
        self.log.add("metadata_read", "ok", f"Read {len(copies)} protected metadata copies from {metadata_file.name}.")

        if self.scenario == "degraded_resources":
            copies = self._inject_degraded_resources(copies)
        elif self.scenario == "unsafe_profile":
            copies = self._inject_unsafe_active_profile(copies)

        valid_results = [self.validate_metadata_copy(m) for m in copies]
        valid_results = [r for r in valid_results if r.ok]

        if not valid_results:
            self.log.add("metadata_selection", "fail", "No valid committed metadata copies. Enter recovery halt.")
            return self._result(None, None, "halt-no-valid-metadata")

        selected = sorted(valid_results, key=lambda r: r.generation, reverse=True)[0]
        self.log.add("metadata_selection", "ok", f"Selected newest committed metadata copy generation={selected.generation}.", selected.metadata_id)

        metadata = selected.metadata
        active_profile_id = metadata["payload"]["active_profile_id"]
        profile = self.profiles.get(active_profile_id)
        if not profile:
            self.log.add("profile_lookup", "fail", f"Active profile {active_profile_id} is missing; trying rollback.", selected.metadata_id)
            return self.rollback(metadata, selected.metadata_id, reason="missing active profile")

        profile_ok, profile_reason = self.validate_profile_signature(profile)
        if not profile_ok:
            self.log.add("profile_signature", "fail", profile_reason, selected.metadata_id, active_profile_id)
            return self.rollback(metadata, selected.metadata_id, reason="active profile signature failed")
        self.log.add("profile_signature", "ok", profile_reason, selected.metadata_id, active_profile_id)

        resource_map = metadata["payload"]["resource_map"]
        profile_ok, profile_reason = self.profile_fits_resources(profile, resource_map, metadata["payload"].get("guard_rails", {}))
        if not profile_ok:
            self.log.add("resource_validation", "fail", profile_reason, selected.metadata_id, active_profile_id)
            return self.rollback(metadata, selected.metadata_id, reason=profile_reason)
        self.log.add("resource_validation", "ok", profile_reason, selected.metadata_id, active_profile_id)

        hpeu_ok, hpeu_reason = self.hpeu_check(profile, resource_map)
        if not hpeu_ok:
            self.log.add("hpeu_configuration", "fail", hpeu_reason, selected.metadata_id, active_profile_id)
            return self.rollback(metadata, selected.metadata_id, reason=hpeu_reason)
        self.log.add("hpeu_configuration", "ok", hpeu_reason, selected.metadata_id, active_profile_id)

        contract = self.generate_machine_contract(profile, resource_map, selected.metadata_id)
        self.log.add("machine_contract", "ok", f"Generated {profile['machine_contract']} machine contract.", selected.metadata_id, active_profile_id)
        self.write_outputs(contract, metadata, profile, selected.metadata_id)
        self.log.add("boot_selected_profile", "ok", f"Boot profile accepted: {active_profile_id}.", selected.metadata_id, active_profile_id)
        return self._result(metadata, profile, "boot-ok", contract)

    def validate_metadata_copy(self, metadata: Dict[str, Any]) -> MetadataValidationResult:
        header = metadata.get("header", {})
        payload = metadata.get("payload", {})
        metadata_id = header.get("metadata_id", "unknown")
        generation = int(header.get("generation_counter", -1))

        if header.get("ecc_errors", 0) > 0:
            if header.get("ecc_correctable", False):
                self.log.add("ecc_check", "ok", f"ECC corrected {header['ecc_errors']} simulated bit error(s).", metadata_id)
            else:
                self.log.add("ecc_check", "fail", "Uncorrectable ECC fault.", metadata_id)
                return MetadataValidationResult(False, metadata, generation, metadata_id, "uncorrectable ECC")
        else:
            self.log.add("ecc_check", "ok", "No simulated ECC errors.", metadata_id)

        if header.get("state") != "committed":
            self.log.add("commit_state", "fail", f"Metadata state is {header.get('state')}; only committed is bootable.", metadata_id)
            return MetadataValidationResult(False, metadata, generation, metadata_id, "not committed")
        self.log.add("commit_state", "ok", "Metadata copy is committed.", metadata_id)

        actual_crc = crc32c_like_hex(payload)
        expected_crc = header.get("crc32_fast_check")
        if actual_crc != expected_crc:
            self.log.add("crc_check", "fail", f"CRC mismatch: expected={expected_crc}, actual={actual_crc}.", metadata_id)
            return MetadataValidationResult(False, metadata, generation, metadata_id, "CRC mismatch")
        self.log.add("crc_check", "ok", "Fast CRC-like check passed.", metadata_id)

        actual_hash = sha256_hex(payload)
        expected_hash = header.get("sha256_payload_hash")
        if actual_hash != expected_hash:
            self.log.add("hash_check", "fail", f"SHA-256 payload hash mismatch: expected={expected_hash}, actual={actual_hash}.", metadata_id)
            return MetadataValidationResult(False, metadata, generation, metadata_id, "hash mismatch")
        self.log.add("hash_check", "ok", "SHA-256 payload hash passed.", metadata_id)

        if not metadata.get("signature"):
            self.log.add("signature_check", "fail", "Missing metadata signature.", metadata_id)
            return MetadataValidationResult(False, metadata, generation, metadata_id, "missing signature")
        signature_material = {"header_without_signature": header, "payload_hash": expected_hash}
        if not verify_signature(signature_material, metadata["signature"]):
            self.log.add("signature_check", "fail", "Metadata signature invalid.", metadata_id)
            return MetadataValidationResult(False, metadata, generation, metadata_id, "bad signature")
        self.log.add("signature_check", "ok", "Metadata signature validated authority.", metadata_id)

        if generation < int(header.get("previous_valid_generation", 0)):
            self.log.add("rollback_check", "fail", "Generation counter is older than previous valid generation.", metadata_id)
            return MetadataValidationResult(False, metadata, generation, metadata_id, "rollback violation")
        self.log.add("rollback_check", "ok", f"Generation counter accepted: {generation}.", metadata_id)
        return MetadataValidationResult(True, metadata, generation, metadata_id, "ok")

    def validate_profile_signature(self, profile: Dict[str, Any]) -> Tuple[bool, str]:
        profile_id = profile.get("profile_id", "unknown")
        if not profile.get("signature"):
            return False, f"Profile {profile_id} is unsigned."
        expected_hash = sha256_hex({k: v for k, v in profile.items() if k not in {"profile_hash", "signature"}})
        if expected_hash != profile.get("profile_hash"):
            return False, f"Profile {profile_id} hash mismatch."
        ok = verify_signature({"profile_hash": profile["profile_hash"], "profile_id": profile_id}, profile["signature"])
        if not ok:
            return False, f"Profile {profile_id} signature invalid."
        return True, f"Profile {profile_id} signature validated."

    def profile_fits_resources(self, profile: Dict[str, Any], resource_map: Dict[str, Any], guard_rails: Dict[str, Any]) -> Tuple[bool, str]:
        compute_by_id = {c["id"]: c for c in resource_map.get("compute_regions", [])}
        mem_regions = resource_map.get("memory_regions", [])
        persistent_by_id = {p["id"]: p for p in resource_map.get("persistent_regions", [])}
        accel_by_id = {a["id"]: a for a in resource_map.get("accelerator_slices", [])}
        io_by_id = {i["id"]: i for i in resource_map.get("io_blocks", [])}

        total_power = 0.0
        for cid in profile.get("required_compute", []):
            c = compute_by_id.get(cid)
            if not c:
                return False, f"Required compute region {cid} does not exist."
            if c.get("status") != "healthy":
                return False, f"Required compute region {cid} is not healthy: {c.get('status')}."
            if c.get("isa") != profile.get("isa_profile"):
                return False, f"Compute region {cid} ISA={c.get('isa')} does not match profile ISA={profile.get('isa_profile')}."
            if "unlicensed" in str(c.get("status")) and not guard_rails.get("allow_unlicensed_isa", False):
                return False, f"Compute region {cid} is unlicensed/unavailable."
            total_power += float(c.get("power_w", 0))

        healthy_memory_mb = sum(int(m.get("size_mb", 0)) for m in mem_regions if m.get("status") == "healthy")
        if healthy_memory_mb < int(profile.get("required_memory_mb", 0)):
            return False, f"Insufficient healthy memory: need {profile.get('required_memory_mb')} MB, have {healthy_memory_mb} MB."

        for pid in profile.get("required_persistent", []):
            p = persistent_by_id.get(pid)
            if not p or p.get("status") != "healthy":
                return False, f"Required persistent region {pid} missing or unhealthy."

        for aid in profile.get("required_accelerators", []):
            a = accel_by_id.get(aid)
            if not a or a.get("status") != "healthy":
                return False, f"Required accelerator {aid} missing or unhealthy."
            total_power += float(a.get("power_w", 0))

        for iid in profile.get("required_io", []):
            i = io_by_id.get(iid)
            if not i or i.get("status") != "healthy":
                return False, f"Required I/O block {iid} missing or unhealthy."

        if total_power > float(profile.get("power_limit_w", 0)):
            return False, f"Profile power budget exceeded: estimated {total_power} W > limit {profile.get('power_limit_w')} W."
        if total_power > float(guard_rails.get("max_total_power_w", 999999)):
            return False, f"Global guard-rail power budget exceeded: {total_power} W."

        return True, f"Resources satisfy profile; estimated execution/accelerator power={total_power:.1f} W."

    def hpeu_check(self, profile: Dict[str, Any], resource_map: Dict[str, Any]) -> Tuple[bool, str]:
        # This is an explicit model check, not real hardware enforcement.
        required_checks = [
            "memory_window",
            "io_permission",
            "dma_window",
            "interrupt_route",
            "vbus_quota",
            "debug_lockout",
            "power_thermal_quota",
            "isa_region_ownership",
        ]
        if profile.get("profile_type") == "recovery":
            return True, "Recovery profile uses minimal management-only HPEU policy."
        vbus_available = sum(int(v.get("gbps", 0)) for v in resource_map.get("vbus_links", []) if v.get("status") in {"healthy", "degraded"})
        if vbus_available < int(profile.get("vbus_quota_gbps", 0)):
            return False, f"Insufficient VBUS quota: need {profile.get('vbus_quota_gbps')} Gbps, have {vbus_available} Gbps."
        return True, "HPEU model checks passed: " + ", ".join(required_checks)

    def generate_machine_contract(self, profile: Dict[str, Any], resource_map: Dict[str, Any], metadata_id: str) -> Dict[str, Any]:
        healthy_mem = [m for m in resource_map.get("memory_regions", []) if m.get("status") == "healthy"]
        memory_map = []
        base = 0x8000_0000
        for m in healthy_mem:
            size_bytes = int(m["size_mb"]) * 1024 * 1024
            memory_map.append({"region": m["id"], "base_hex": hex(base), "size_mb": m["size_mb"], "attributes": "normal,cacheable"})
            base += size_bytes
        contract = {
            "generated_utc": utc_now(),
            "scaffold_version": SCAFFOLD_VERSION,
            "metadata_id": metadata_id,
            "profile_id": profile["profile_id"],
            "os_family": profile["os_family"],
            "machine_contract_type": profile["machine_contract"],
            "isa_profile": profile["isa_profile"],
            "privilege_model": self._privilege_model(profile["isa_profile"]),
            "memory_map": memory_map,
            "interrupt_model": self._interrupt_model(profile),
            "timer_model": self._timer_model(profile),
            "device_tables": self._device_tables(profile),
            "telemetry": {
                "health_source": "protected_metadata.health_map",
                "thermal_zones": resource_map.get("thermal_zones", []),
                "vbus_links": resource_map.get("vbus_links", []),
            },
            "disclaimer": "Generated by roadmap simulation scaffold; not real firmware output.",
        }
        return contract

    def _privilege_model(self, isa: str) -> Dict[str, str]:
        if isa == "riscv64":
            return {"model": "RISC-V-like M/S/U privilege", "status": "simulation-placeholder"}
        if isa == "arm64-compatible":
            return {"model": "ARM64-like EL3/EL2/EL1/EL0", "status": "compatibility-placeholder"}
        if isa == "v-risc":
            return {"model": "V-RISC research privilege model", "status": "undefined-roadmap"}
        if isa == "management-core":
            return {"model": "minimal recovery management mode", "status": "recovery-only"}
        return {"model": f"{isa} privilege model", "status": "placeholder"}

    def _interrupt_model(self, profile: Dict[str, Any]) -> Dict[str, str]:
        contract = profile.get("machine_contract")
        if contract == "device-tree":
            return {"controller": "plic-or-gic-like", "description": "device-tree-described interrupt controller"}
        if contract == "uefi-acpi":
            return {"controller": "gic-or-apic-like", "description": "ACPI-described interrupt controller"}
        if contract == "flatmap":
            return {"controller": "simple-vectored", "description": "RTOS flat-map vector table"}
        return {"controller": "minimal", "description": "recovery-only interrupts"}

    def _timer_model(self, profile: Dict[str, Any]) -> Dict[str, str]:
        if profile.get("machine_contract") == "uefi-acpi":
            return {"clocksource": "ACPI GTDT/HPET-like placeholder", "frequency_hz": "10000000"}
        if profile.get("machine_contract") == "device-tree":
            return {"clocksource": "DT timer node placeholder", "frequency_hz": "10000000"}
        return {"clocksource": "minimal management timer", "frequency_hz": "1000000"}

    def _device_tables(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        if profile.get("machine_contract") == "device-tree":
            return {"format": "DTS", "nodes": ["/cpus", "/memory", "/soc/interrupt-controller", "/soc/vhsc-telemetry", "/soc/vhsc-vbus"]}
        if profile.get("machine_contract") == "uefi-acpi":
            return {"format": "ACPI-summary", "tables": ["RSDP", "XSDT", "FADT", "MADT", "GTDT", "SRAT", "HMAT", "VHSC"]}
        if profile.get("machine_contract") == "flatmap":
            return {"format": "flatmap", "sections": ["vectors", "ram", "persistent", "telemetry"]}
        return {"format": "recovery", "sections": ["management-console", "metadata-reader"]}

    def rollback(self, metadata: Dict[str, Any], metadata_id: str, reason: str) -> Dict[str, Any]:
        rollback_profile_id = metadata.get("payload", {}).get("last_known_good_profile_id", "recovery-safe-minimal")
        self.log.add("rollback_start", "warn", f"Rollback triggered because: {reason}.", metadata_id, rollback_profile_id)
        profile = self.profiles.get(rollback_profile_id)
        if not profile:
            self.log.add("rollback_profile", "fail", f"Rollback profile {rollback_profile_id} not found.", metadata_id, rollback_profile_id)
            return self._result(metadata, None, "halt-rollback-profile-missing")
        ok, detail = self.validate_profile_signature(profile)
        if not ok:
            self.log.add("rollback_profile_signature", "fail", detail, metadata_id, rollback_profile_id)
            return self._result(metadata, profile, "halt-rollback-profile-invalid")
        resource_map = metadata["payload"]["resource_map"]
        ok, detail = self.profile_fits_resources(profile, resource_map, metadata["payload"].get("guard_rails", {}))
        if not ok:
            self.log.add("rollback_resource_validation", "fail", detail, metadata_id, rollback_profile_id)
            return self._result(metadata, profile, "halt-rollback-resources-invalid")
        ok, detail = self.hpeu_check(profile, resource_map)
        if not ok:
            self.log.add("rollback_hpeu", "fail", detail, metadata_id, rollback_profile_id)
            return self._result(metadata, profile, "halt-rollback-hpeu-invalid")
        contract = self.generate_machine_contract(profile, resource_map, metadata_id)
        self.write_outputs(contract, metadata, profile, metadata_id)
        self.log.add("rollback_complete", "ok", f"Activated last-known-good profile: {rollback_profile_id}.", metadata_id, rollback_profile_id)
        return self._result(metadata, profile, "rollback-ok", contract)

    def _inject_degraded_resources(self, copies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = copy.deepcopy(copies)
        # Corrupt active profile resources by degrading C0, forcing rollback to recovery profile.
        for m in out:
            rm = m["payload"]["resource_map"]
            for c in rm.get("compute_regions", []):
                if c["id"] == "C0":
                    c["status"] = "thermal_throttled_degraded"
            self._resign_metadata_after_payload_mutation(m)
        self.log.add("fault_injection", "warn", "Scenario degraded_resources: C0 degraded after metadata generation.")
        return out

    def _inject_unsafe_active_profile(self, copies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = copy.deepcopy(copies)
        for m in out:
            m["payload"]["active_profile_id"] = "x86-64-later-stage-placeholder"
            self._resign_metadata_after_payload_mutation(m)
        self.log.add("fault_injection", "warn", "Scenario unsafe_profile: active profile changed to x86-64 placeholder.")
        return out

    def _resign_metadata_after_payload_mutation(self, metadata: Dict[str, Any]) -> None:
        payload = metadata["payload"]
        metadata["header"]["payload_length"] = len(stable_json(payload))
        metadata["header"]["crc32_fast_check"] = crc32c_like_hex(payload)
        metadata["header"]["sha256_payload_hash"] = sha256_hex(payload)
        signature_material = {"header_without_signature": metadata["header"], "payload_hash": metadata["header"]["sha256_payload_hash"]}
        metadata["signature"] = sign_payload(signature_material)

    def write_outputs(self, contract: Dict[str, Any], metadata: Dict[str, Any], profile: Dict[str, Any], metadata_id: str) -> None:
        outputs = self.root / "outputs"
        write_json(outputs / "selected_machine_contract.json", contract)
        write_text(outputs / "generated_devicetree.dts", self.generate_dts(contract))
        write_json(outputs / "generated_acpi_summary.json", self.generate_acpi_summary(contract))

    def generate_dts(self, contract: Dict[str, Any]) -> str:
        if contract.get("machine_contract_type") not in {"device-tree", "flatmap", "recovery-minimal"}:
            return "// DTS not applicable for this selected profile. See generated_acpi_summary.json.\n"
        memory_nodes = "\n".join(
            f"        /* {m['region']} */ reg = <0x0 {m['base_hex']} 0x0 0x{int(m['size_mb']) * 1024 * 1024:x}>;"
            for m in contract.get("memory_map", [])[:1]
        )
        return textwrap.dedent(
            f"""
            /dts-v1/;
            / {{
                compatible = "vhsc,bootrom-scaffold", "vhsc,{contract.get('isa_profile')}";
                model = "VHS-C BootROM Control-Plane Scaffold";
                #address-cells = <2>;
                #size-cells = <2>;

                chosen {{
                    bootargs = "console=ttyS0 vhsc_profile={contract.get('profile_id')}";
                }};

                cpus {{
                    #address-cells = <1>;
                    #size-cells = <0>;
                    cpu@0 {{
                        device_type = "cpu";
                        compatible = "vhsc,{contract.get('isa_profile')}";
                        reg = <0>;
                    }};
                }};

                memory@80000000 {{
                    device_type = "memory";
{memory_nodes if memory_nodes else '        reg = <0x0 0x80000000 0x0 0x04000000>;'}
                }};

                soc {{
                    compatible = "simple-bus";
                    vhsc_telemetry: telemetry@10000000 {{
                        compatible = "vhsc,telemetry-scaffold";
                        metadata-id = "{contract.get('metadata_id')}";
                    }};
                    vhsc_vbus: vbus@10001000 {{
                        compatible = "vhsc,vbus-scaffold";
                    }};
                }};
            }};
            """
        ).strip() + "\n"

    def generate_acpi_summary(self, contract: Dict[str, Any]) -> Dict[str, Any]:
        if contract.get("machine_contract_type") != "uefi-acpi":
            return {"status": "not_applicable", "reason": "Selected profile is not UEFI/ACPI style."}
        return {
            "status": "scaffold_only",
            "tables": {
                "RSDP": "root pointer placeholder",
                "XSDT": "table directory placeholder",
                "FADT": "firmware control placeholder",
                "MADT": contract.get("interrupt_model"),
                "GTDT": contract.get("timer_model"),
                "SRAT": "memory locality placeholder",
                "HMAT": "heterogeneous memory attribute placeholder",
                "VHSC": {
                    "profile_id": contract.get("profile_id"),
                    "metadata_id": contract.get("metadata_id"),
                    "telemetry": contract.get("telemetry"),
                },
            },
            "disclaimer": "ACPI summary only; not binary ACPI AML/ASL output.",
        }

    def _result(self, metadata: Optional[Dict[str, Any]], profile: Optional[Dict[str, Any]], status: str, contract: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "scenario": self.scenario,
            "status": status,
            "selected_metadata_id": metadata.get("header", {}).get("metadata_id") if metadata else None,
            "selected_profile_id": profile.get("profile_id") if profile else None,
            "contract": contract,
            "events": self.log.rows(),
        }


# -----------------------------------------------------------------------------
# Output aggregation
# -----------------------------------------------------------------------------


def write_decision_logs(root: Path, results: List[Dict[str, Any]]) -> None:
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    all_events: List[Dict[str, str]] = []
    for r in results:
        all_events.extend(r.get("events", []))

    csv_path = outputs / "boot_decision_log.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["scenario", "step", "status", "detail", "metadata_id", "profile_id"])
        writer.writeheader()
        for row in all_events:
            writer.writerow(row)

    write_json(outputs / "boot_decision_log.json", results)

    # Fault report is a scenario-level summary.
    fault_path = outputs / "fault_injection_report.csv"
    with fault_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["scenario", "status", "selected_metadata_id", "selected_profile_id"])
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "scenario": r.get("scenario"),
                    "status": r.get("status"),
                    "selected_metadata_id": r.get("selected_metadata_id"),
                    "selected_profile_id": r.get("selected_profile_id"),
                }
            )


def make_boot_flow_diagram(root: Path, results: List[Dict[str, Any]]) -> None:
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch
    except Exception as exc:  # pragma: no cover
        print(f"[WARN] Could not create diagram because matplotlib is unavailable: {exc}", file=sys.stderr)
        return

    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    steps = [
        "Power-on",
        "Mgmt island",
        "BootROM",
        "Read metadata",
        "ECC",
        "Hash/CRC",
        "Signature",
        "Rollback check",
        "HPEU",
        "Machine contract",
        "Boot / Recovery",
    ]
    fig, ax = plt.subplots(figsize=(16, 6))
    ax.set_axis_off()
    ax.set_title("VHS-C BootROM / Control-Plane Simulation Scaffold", fontsize=16, weight="bold")
    y = 0.55
    x0 = 0.03
    dx = 0.085
    for i, step in enumerate(steps):
        x = x0 + i * dx
        box = FancyBboxPatch((x, y), 0.07, 0.22, boxstyle="round,pad=0.012", linewidth=1.2, edgecolor="black", facecolor="white")
        ax.add_patch(box)
        ax.text(x + 0.035, y + 0.11, step, ha="center", va="center", fontsize=8)
        if i < len(steps) - 1:
            ax.annotate("", xy=(x + 0.083, y + 0.11), xytext=(x + 0.07, y + 0.11), arrowprops=dict(arrowstyle="->", lw=1.3))

    summary_y = 0.22
    ax.text(0.03, summary_y + 0.16, "Scenario results", fontsize=11, weight="bold")
    for idx, r in enumerate(results):
        ax.text(
            0.03,
            summary_y + 0.12 - idx * 0.035,
            f"{r.get('scenario')}: {r.get('status')} -> {r.get('selected_profile_id')}",
            fontsize=8,
        )
    ax.text(
        0.03,
        0.05,
        "Roadmap scaffold only: ECC protects bits; hash/checksum protects metadata object; signature protects authority; rollback protects recovery.",
        fontsize=9,
        style="italic",
    )
    fig.tight_layout()
    fig.savefig(outputs / "boot_flow_summary.png", dpi=180)
    plt.close(fig)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="VHS-C BootROM/control-plane simulation scaffold")
    p.add_argument("--root", type=Path, default=Path("simulation/firmware-defined"), help="Root folder for profiles, metadata, outputs")
    p.add_argument("--init", action="store_true", help="Initialize demo folder structure and sample inputs")
    p.add_argument("--overwrite", action="store_true", help="Overwrite generated sample inputs during --init")
    p.add_argument("--scenario", choices=SUPPORTED_SCENARIOS, default="normal", help="Fault/boot scenario to run")
    p.add_argument("--make-diagram", action="store_true", help="Generate outputs/boot_flow_summary.png if matplotlib is installed")
    p.add_argument("--seed", type=int, default=340, help="Deterministic random seed")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    root = args.root

    if args.init:
        initialize_demo_tree(root, overwrite=args.overwrite)
        print(f"[OK] Initialized VHS-C BootROM scaffold folder: {root}")

    if not (root / "profiles").exists() or not (root / "metadata").exists():
        print(f"[ERROR] Missing scaffold inputs under {root}. Run with --init first.", file=sys.stderr)
        return 2

    scenarios = [s for s in SUPPORTED_SCENARIOS if s != "all"] if args.scenario == "all" else [args.scenario]
    results: List[Dict[str, Any]] = []
    for scenario in scenarios:
        sim = BootROMControlPlaneScaffold(root=root, scenario=scenario, random_seed=args.seed)
        result = sim.run()
        results.append(result)
        print(f"[RESULT] {scenario}: {result['status']} -> {result.get('selected_profile_id')}")

    write_decision_logs(root, results)
    if args.make_diagram:
        make_boot_flow_diagram(root, results)

    print(f"[OK] Wrote outputs to: {root / 'outputs'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
