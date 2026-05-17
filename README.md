# VHS-C Simulation

```
git clone https://github.com/fadjar340/vhsc-simulation.git
cd vhsc-simulation
python3 -m pip install -r requirements.txt
python3 vhsc_section14_sim.py
```
It will create new folder: `vhsc_sim_output`

## Content of the output folder
```
vhsc_sim_output
  - noc_fault_plot.png
  - noc_fault_summary.csv
  - noc_remap_cost_plot.png
  - roofline_energy_plot.png
  - roofline_energy_summary.csv
  - roofline_movement_reduction.png
  - roofline_plot.png
  - roofline_summary.csv
  - thermal_deltaT_plot.png
  - thermal_hotspot_plot.png
  - thermal_safe_activity_plot.png
  - thermal_summary.csv
  - vertical_bus_bandwidth.png
  - vertical_bus_impedance.png
  - vertical_bus_pitch_crosstalk_proxy.png
  - vertical_bus_pitch_rc_tau.png
  - vertical_bus_pitch_sweep.csv
  - vertical_bus_summary.csv
```

The simulation repository should be interpreted as a living scaffold. Version~v1.1 separates the near-term roofline throughput assumption from the aspirational ExaOPS thermal-stress assumption, clarifies the capped vertical-bus bandwidth interpretation, increases the effective vertical-bus capacitance screening multiplier, uses independent random-number streams for each NoC failure-rate point, and increases the NoC Monte Carlo sample count. These changes improve traceability and interpretation; they do not convert the scaffold into device proof.
