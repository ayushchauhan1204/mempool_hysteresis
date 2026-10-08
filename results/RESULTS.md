# Results (generated from numbers.json)

Held-out seeds 1000–1199 (n = 200), 8,200 simulation runs, generated 2026-10-04 22:45. Paired tests are two-sided Wilcoxon signed-rank with Holm correction within each table; r = matched-pairs rank-biserial correlation.

Calibration (dev seeds 0–4 only): tau_m = 6.47 s, eps_D = 0.0 (resolution floor applies), beta = 5.72 blocks, size-proxy limit = 0.125.

## Table I: hysteresis on the no-intervention network (B1), disturbed vs clean history

| Disturbance | Residue AUC, median (tx·s) | State convergence, median (s) | Excess backlog AUC, median (tx·s) | Δ confirmation latency, median (s) | p (Holm) | Ordering distortion, median | B1 declared before state converged |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Partition | 12,676 | 267 | 9,970 | 0.63 | <0.001 | 0.039 | 98% |
| Node isolation | 6,867 | 273 | 2,589 | 0.00 | 0.462 | 0.012 | 98% |
| Packet loss | 0 | 0 | 0 | 0.00 | <0.001 | 0.000 | 4% |
| Latency spike | 88 | 9 | 290 | 0.03 | <0.001 | 0.002 | 100% |
| Asymmetric link | 1,133 | 28 | 5,074 | 0.77 | <0.001 | 0.036 | 100% |
| Transaction burst | 0 | 0 | 147,304 | 29.65 | <0.001 | 0.334 | 2% |

Clean-history reference: residue is zero at every sample; state convergence 0 s by definition. Δ confirmation latency compares the identical post-recovery workload (created in the 300 s after the disturbance ended) between histories.

## Table II: recovery assessment, B1 vs B2 vs SARA

FRE = seconds after the disturbance ended during which the policy reported "recovered" while state had not recovered (FRE_state: residue remained; FRE: residue or backlog debt remained). Means with medians of time quantities.

| Disturbance | Policy | Detected | Declared, median (s) | State converged, median (s) | FRE_state, mean (s) | FRE overall, mean (s) | Over-delay, mean (s) | In-band traffic, mean (kB) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Partition | B1 | 100% | 6 | 267 | 297 | 299 | 0.0 | 0 |
|  | B2 | 100% | 6 | 4 | 36.1 | 128 | 0.5 | 321 |
|  | SARA | 100% | 18 | 8 | 0.0 | 99.8 | 53.2 | 280 |
| Node isolation | B1 | 100% | 6 | 273 | 312 | 313 | 0.0 | 0 |
|  | B2 | 100% | 6 | 4 | 10.7 | 59.1 | 0.9 | 97 |
|  | SARA | 100% | 17 | 8 | 0.0 | 43.7 | 66.9 | 93 |
| Packet loss | B1 | 100% | 4 | 0 | 0.9 | 11.8 | 2.8 | 0 |
|  | B2 | 100% | 4 | 0 | 0.9 | 11.7 | 3.3 | 142 |
|  | SARA | 100% | 14 | 0 | 0.0 | 9.0 | 82.8 | 0 |
| Latency spike | B1 | 100% | 4 | 9 | 6.8 | 64.4 | 0.0 | 0 |
|  | B2 | 100% | 4 | 6 | 3.6 | 57.2 | 0.0 | 169 |
|  | SARA | 100% | 16 | 8 | 0.1 | 45.7 | 70.4 | 229 |
| Asymmetric link | B1 | 100% | 4 | 28 | 25.8 | 137 | 0.0 | 0 |
|  | B2 | 100% | 4 | 7 | 14.8 | 123 | 0.0 | 245 |
|  | SARA | 100% | 22 | 11 | 0.0 | 89.7 | 49.1 | 173 |
| Transaction burst | B1 | 0% | 0 | 0 | 1.0 | 440 | 0.0 | 0 |
|  | B2 | 0% | 0 | 0 | 1.0 | 440 | 0.0 | 0 |
|  | SARA | 98% | 293 | 0 | 0.0 | 170 | 7.8 | 0 |

Paired differences, SARA minus baseline (median difference; Holm-adjusted p; r):

| Disturbance | FRE_state vs B1 | FRE_state vs B2 | FRE vs B1 | FRE vs B2 | State convergence vs B2 | In-band traffic vs B2 |
| --- | --- | --- | --- | --- | --- | --- |
| Partition | -261 (<0.001; r=-1.00) | 0.0 (<0.001; r=-1.00) | -138 (<0.001; r=-1.00) | -10.0 (<0.001; r=-0.96) | 3.0 (1.000; r=0.06) | -41.5 (<0.001; r=-0.49) |
| Node isolation | -267 (<0.001; r=-1.00) | 0.0 (0.022; r=-1.00) | -216 (<0.001; r=-1.00) | -7.0 (<0.001; r=-0.89) | 4.0 (<0.001; r=0.90) | 2.9 (1.000; r=-0.04) |
| Packet loss | 0.0 (0.539; r=-1.00) | 0.0 (0.539; r=-1.00) | 0.0 (<0.001; r=-1.00) | 0.0 (<0.001; r=-1.00) | 0.0 (1.000; r=0.00) | -102 (<0.001; r=-1.00) |
| Latency spike | -5.0 (<0.001; r=-1.00) | -1.7 (<0.001; r=-1.00) | -11.0 (<0.001; r=-1.00) | -9.2 (<0.001; r=-0.96) | 1.0 (<0.001; r=0.92) | 77.9 (<0.001; r=0.58) |
| Asymmetric link | -24.0 (<0.001; r=-1.00) | -2.7 (<0.001; r=-1.00) | -23.0 (<0.001; r=-1.00) | -14.7 (<0.001; r=-0.90) | 0.0 (0.480; r=0.23) | -36.7 (<0.001; r=-0.64) |
| Transaction burst | 0.0 (0.992; r=-1.00) | 0.0 (0.992; r=-1.00) | -235 (<0.001; r=-1.00) | -235 (<0.001; r=-1.00) | 0.0 (1.000; r=-1.00) | 0.0 (0.737; r=1.00) |
| Pooled (per-seed mean) | -102 (<0.001; r=-1.00) | -2.4 (<0.001; r=-1.00) | -122 (<0.001; r=-1.00) | -48.3 (<0.001; r=-1.00) | 1.3 (1.000; r=0.03) | -7.7 (<0.001; r=-0.39) |

Monitoring traffic for SARA (incremental mirror), mean per run: 2,358 kB (full snapshots would be 31,441 kB).

## Table III: ablation, full SARA minus each variant

Negative FRE differences mean the full framework had less false-recovery exposure. Mean of the variant is shown with the paired median difference and Holm-adjusted p.

| Disturbance | Metric | −D (no divergence detection) | −R (no risk assessment) | −V (no recovery verification) |
| --- | --- | --- | --- | --- |
| Partition | FRE_state | variant 31.2; Δ 0.0 (<0.001 ***) | variant 0.1; Δ 0.0 (1.000 n.s.) | variant 41.9; Δ -1.0 (<0.001 ***) |
|  | FRE | variant 112; Δ 0.0 (1.000 n.s.) | variant 111; Δ 0.0 (1.000 n.s.) | variant 140; Δ -9.0 (<0.001 ***) |
|  | T_conv | variant 67.0; Δ -2.0 (<0.001 ***) | variant 11.6; Δ 0.0 (1.000 n.s.) | variant 48.5; Δ 0.0 (<0.001 ***) |
|  | inband_kB | variant 335; Δ 29.0 (1.000 n.s.) | variant 161; Δ 116 (<0.001 ***) | variant 251; Δ 0.0 (<0.001 ***) |
| Node isolation | FRE_state | variant 5.3; Δ 0.0 (0.168 n.s.) | variant 0.0; Δ 0.0 (1.000 n.s.) | variant 29.6; Δ -1.0 (<0.001 ***) |
|  | FRE | variant 51.8; Δ 0.0 (0.016 *) | variant 47.0; Δ 0.0 (1.000 n.s.) | variant 78.3; Δ -8.0 (<0.001 ***) |
|  | T_conv | variant 16.5; Δ 0.0 (1.000 n.s.) | variant 9.6; Δ 0.0 (1.000 n.s.) | variant 36.1; Δ 0.0 (1.000 n.s.) |
|  | inband_kB | variant 45.2; Δ 49.1 (<0.001 ***) | variant 43.2; Δ 47.6 (<0.001 ***) | variant 86.9; Δ 0.0 (<0.001 ***) |
| Packet loss | FRE_state | variant 0.0; Δ 0.0 (1.000 n.s.) | variant 0.0; Δ 0.0 (1.000 n.s.) | variant 0.9; Δ 0.0 (1.000 n.s.) |
|  | FRE | variant 9.0; Δ 0.0 (1.000 n.s.) | variant 9.0; Δ 0.0 (1.000 n.s.) | variant 11.3; Δ 0.0 (<0.001 ***) |
|  | T_conv | variant 1.1; Δ 0.0 (1.000 n.s.) | variant 1.1; Δ 0.0 (1.000 n.s.) | variant 1.1; Δ 0.0 (1.000 n.s.) |
|  | inband_kB | variant 0.0; Δ 0.0 (1.000 n.s.) | variant 0.0; Δ 0.0 (1.000 n.s.) | variant 0.0; Δ 0.0 (1.000 n.s.) |
| Latency spike | FRE_state | variant 0.2; Δ 0.0 (1.000 n.s.) | variant 0.0; Δ 0.0 (1.000 n.s.) | variant 5.2; Δ -3.0 (<0.001 ***) |
|  | FRE | variant 49.4; Δ 0.0 (<0.001 ***) | variant 47.9; Δ 0.0 (1.000 n.s.) | variant 57.2; Δ -8.0 (<0.001 ***) |
|  | T_conv | variant 10.1; Δ 0.0 (0.005 **) | variant 9.5; Δ 0.0 (1.000 n.s.) | variant 10.1; Δ 0.0 (<0.001 ***) |
|  | inband_kB | variant 99.6; Δ 108 (<0.001 ***) | variant 146; Δ 84.7 (<0.001 ***) | variant 217; Δ 0.3 (<0.001 ***) |
| Asymmetric link | FRE_state | variant 2.7; Δ 0.0 (<0.001 ***) | variant 0.0; Δ 0.0 (1.000 n.s.) | variant 18.0; Δ -15.0 (<0.001 ***) |
|  | FRE | variant 93.4; Δ 0.0 (<0.001 ***) | variant 105; Δ 0.0 (0.042 *) | variant 126; Δ -16.0 (<0.001 ***) |
|  | T_conv | variant 20.2; Δ 0.0 (<0.001 ***) | variant 15.4; Δ 0.0 (1.000 n.s.) | variant 22.9; Δ -2.0 (<0.001 ***) |
|  | inband_kB | variant 66.8; Δ 100 (<0.001 ***) | variant 105; Δ 65.1 (<0.001 ***) | variant 156; Δ 4.6 (<0.001 ***) |
| Transaction burst | FRE_state | variant 0.0; Δ 0.0 (1.000 n.s.) | variant 0.9; Δ 0.0 (1.000 n.s.) | variant 1.0; Δ 0.0 (1.000 n.s.) |
|  | FRE | variant 170; Δ 0.0 (1.000 n.s.) | variant 440; Δ -235 (<0.001 ***) | variant 440; Δ -235 (<0.001 ***) |
|  | T_conv | variant 1.0; Δ 0.0 (1.000 n.s.) | variant 0.9; Δ 0.0 (1.000 n.s.) | variant 1.0; Δ 0.0 (1.000 n.s.) |
|  | inband_kB | variant 0.1; Δ 0.0 (1.000 n.s.) | variant 0.0; Δ 0.0 (1.000 n.s.) | variant 0.0; Δ 0.0 (1.000 n.s.) |
| Pooled | FRE_state | variant 6.5; Δ 0.0 (<0.001 ***) | variant 0.2; Δ 0.0 (1.000 n.s.) | variant 16.1; Δ -4.5 (<0.001 ***) |
|  | FRE | variant 80.9; Δ -0.7 (<0.001 ***) | variant 127; Δ -39.6 (<0.001 ***) | variant 142; Δ -53.4 (<0.001 ***) |
|  | T_conv | variant 19.3; Δ -1.8 (<0.001 ***) | variant 8.0; Δ 0.0 (0.828 n.s.) | variant 19.9; Δ -1.4 (<0.001 ***) |
|  | inband_kB | variant 91.2; Δ 46.3 (<0.001 ***) | variant 75.8; Δ 53.5 (<0.001 ***) | variant 118; Δ 1.4 (<0.001 ***) |

## False alarms in clean runs

| Policy | Incidents per clean run | Runs with any |
| --- | --- | --- |
| B1 | 0.000 | 0.0% |
| SARA | 0.425 | 21.5% |
| SARA-D | 0.420 | 21.0% |
| SARA-R | 0.015 | 1.5% |
| SARA-V | 0.205 | 20.5% |

## Downstream effect by policy: identical post-recovery workload vs clean history

| Disturbance | Δ confirmation latency B1 (mean s) | B2 | SARA | Ordering distortion B1 (mean) | B2 | SARA |
| --- | --- | --- | --- | --- | --- | --- |
| Partition | 2.16 | 2.49 | 2.58 | 0.051 | 0.049 | 0.052 |
| Node isolation | 0.38 | 0.43 | 0.46 | 0.018 | 0.010 | 0.011 |
| Packet loss | 0.03 | 0.02 | 0.03 | 0.001 | 0.001 | 0.001 |
| Latency spike | 0.46 | 0.45 | 0.44 | 0.009 | 0.009 | 0.009 |
| Asymmetric link | 2.73 | 2.33 | 2.48 | 0.050 | 0.045 | 0.047 |
| Transaction burst | 33.00 | 33.00 | 33.00 | 0.324 | 0.324 | 0.324 |

## Robustness sweeps (seeds 2000–2049)

**Partition duration** (partition); means per seed.

| partition duration (s) | B1 state conv. (s) | B2 | SARA | B1 FRE_state (s) | B2 | SARA | B1 FRE (s) | B2 | SARA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | 224 | 12.7 | 11.3 | 218 | 9.3 | 0.0 | 220 | 29.7 | 29.7 |
| 30 | 212 | 8.7 | 8.7 | 206 | 5.3 | 0.0 | 206 | 73.3 | 65.9 |
| 60 | 266 | 31.5 | 10.1 | 260 | 27.5 | 0.4 | 260 | 126 | 91.5 |
| 120 | 368 | 40.4 | 8.4 | 362 | 35.7 | 0.0 | 363 | 221 | 165 |
| 240 | 465 | 28.4 | 10.3 | 459 | 22.9 | 0.0 | 460 | 339 | 173 |

**Loss with lossy transport** (loss); means per seed.

| message loss probability | B1 state conv. (s) | B2 | SARA | B1 FRE_state (s) | B2 | SARA | B1 FRE (s) | B2 | SARA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.2 | 55.1 | 27.5 | 1.9 | 53.2 | 20.9 | 0.1 | 67.7 | 30.1 | 11.9 |
| 0.4 | 267 | 5.1 | 6.3 | 263 | 0.0 | 0.0 | 273 | 26.6 | 37.2 |
| 0.6 | 388 | 14.2 | 14.9 | 384 | 9.8 | 1.4 | 389 | 73.0 | 72.2 |
| 0.8 | 451 | 107 | 26.2 | 447 | 103 | 0.9 | 449 | 158 | 95.2 |

**Block-space utilisation** (partition, burst); means per seed.

| utilisation ρ | B1 state conv. (s) | B2 | SARA | B1 FRE_state (s) | B2 | SARA | B1 FRE (s) | B2 | SARA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.5 | 81.3 | 7.9 | 5.6 | 78.3 | 5.9 | 0.0 | 153 | 97.0 | 44.1 |
| 0.75 | 148 | 14.9 | 5.5 | 145 | 12.9 | 0.0 | 332 | 243 | 118 |
| 0.9 | 176 | 14.3 | 5.5 | 173 | 12.3 | 0.0 | 451 | 379 | 240 |

Recalibrated on dev seeds: 0.5: beta=2.86, tau_m=6.47, size limit=0.083; 0.75: beta=5.72, tau_m=6.47, size limit=0.125; 0.9: beta=9.69, tau_m=6.47, size limit=0.119

**Reorged transactions re-announced** (partition, isolation); means per seed.

| relay_reorged | B1 state conv. (s) | B2 | SARA | B1 FRE_state (s) | B2 | SARA | B1 FRE (s) | B2 | SARA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| False | 300 | 17.1 | 9.9 | 294 | 13.2 | 0.1 | 294 | 94.6 | 76.5 |
| True | 291 | 4.7 | 9.6 | 285 | 1.1 | 0.1 | 289 | 91.8 | 76.7 |

**Outage semantics** (partition, isolation); means per seed.

| outage mode | B1 state conv. (s) | B2 | SARA | B1 FRE_state (s) | B2 | SARA | B1 FRE (s) | B2 | SARA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| reset | 300 | 17.1 | 9.9 | 294 | 13.2 | 0.1 | 294 | 94.6 | 76.5 |
| buffered | 20.5 | 10.1 | 9.8 | 16.5 | 5.7 | 0.1 | 104 | 97.1 | 77.7 |

**Network size** (partition); means per seed.

| nodes N | B1 state conv. (s) | B2 | SARA | B1 FRE_state (s) | B2 | SARA | B1 FRE (s) | B2 | SARA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 296 | 28.9 | 10.2 | 290 | 24.9 | 0.0 | 290 | 114 | 89.2 |
| 20 | 392 | 61.7 | 14.7 | 386 | 56.8 | 0.0 | 387 | 128 | 89.1 |

Recalibrated on dev seeds: 10: beta=5.72, tau_m=6.47, size limit=0.125; 20: beta=5.89, tau_m=8.12, size limit=0.140

**Calibration sample (post hoc)** (all six disturbances; SARA only). Added after the held-out run showed false incidents in clean runs; the main results keep the pre-specified 5-seed calibration.

| dev seeds | beta (blocks) | false incidents per clean run | FRE_state (s) | FRE (s) | over-delay (s) | declared (s) |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 5.72 | 0.260 | 0.0 | 77.2 | 44.8 | 115 |
| 50 | 11.40 | 0.000 | 0.2 | 114 | 2.9 | 27.9 |

## Hand verification

Seed 1000, partition, B1. Residue from raw state dumps: +10 s: hand 234 vs pipeline 234; +30 s: hand 221 vs pipeline 221; +120 s: hand 55 vs pipeline 55. FRE_state by hand 173 s vs pipeline 173 s (declared 6 s, state converged 179 s). All match: True.
