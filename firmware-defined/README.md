# VHS-C BootROM / Control-Plane Scaffold Inputs

Generated: 2026-05-18T18:50:42Z
Scaffold version: 0.2.0

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
