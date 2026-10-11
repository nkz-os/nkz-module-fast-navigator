# FertiliCalc reference script (test oracle)

`fertilicalc_script_231124.py` and `gpl-3.0.txt` come unmodified from the authors' public
package `FC_public_with_license_231124.zip` (F. J. Villalobos, Universidad de Córdoba),
distributed under the GNU GPL v3. SHA-256 of the zip:
`81f7e4a2652dd558c0f8870ebdf3822cfeb4a95ddf003622cbb18fd0b250a237`.

`crop_data_with_synthetic.csv` is the package's `crop_data.csv` (2 crops: sunflower, durum
wheat) plus 4 **synthetic** rows marked "(sintetica)" — invented, plausible values used only
to exercise the legume, forage-legume, tree and tuber branches of the script. They are not
agronomic data and must never be used outside tests.

## How the expected values in `oracle_cases.py` were produced

1. Python 3.12 venv with `numpy==2.1.3` and `pandas==2.2.3`.
2. For each case, a directory with the script, `crop_data_with_synthetic.csv` renamed to
   `crop_data.csv`, and an `input.txt` with the rows below; run the script there; read
   `out.csv` (N_min, N_max, N_avg, P, K per crop; elemental kg/ha).
3. Cases ending in `_FIXED` ran a copy of the script with one bug corrected:
   - `k_rate = p_exported` (strategy 4) → `k_rate = k_exported`;
   - the soil P method factor is applied once (`p_conc_olsen = factor * p_conc` and the three
     comparisons/build-up use `p_conc_olsen`) instead of once per crop of the rotation.

| case | input.txt |
|---|---|
| v1_strategy2 | `3,12.0,150.0,2.0,80.,7.5,0,0,2,1,2` / `1,2000.,20.,35.,100.,2.95,0.63,0.72,0` / `2,3000.,20.,40.,10.,2.4,0.42,0.5,0` |
| v2_strategy1 | as v1 with strategy `1` (9th value of row 0) |
| v3_strategy3 | as v1 with strategy `3` |
| v4_rich_soil_no_tillage_burned | `6,40.0,400.0,4.0,80.,8.0,0,0,2,0,2` / `1,2000.,30.,35.,100.,2.95,0.63,0.72,0` / `2,3000.,10.,40.,10.,2.4,0.42,0.5,1` |
| v5_cv0 | as v1 with CV `0.` in both crop rows |
| vL1_faba_after_durum | `3,12.0,150.0,2.0,80.,7.5,0,0,2,1,2` / `2,3000.,20.,40.,10.,2.4,0.42,0.5,0` / `3,2500.,20.,40.,100.,4.0,0.45,1.1,0` |
| vL2_alfalfa_som4_no_tillage | `3,12.0,150.0,4.0,80.,7.5,0,0,3,0,2` / `4,9000.,15.,80.,10.,3.0,0.25,2.2,0` / `2,3000.,20.,40.,10.,2.4,0.42,0.5,0` |
| vT1_olive_irrigated | `3,12.0,150.0,2.0,80.,7.5,0,1,2,1,1` / `5,5000.,25.,50.,100.,1.0,0.12,1.3,0` |
| vT2_olive_rainfed | as vT1 with water supply `0` (8th value of row 0) |
| vP_potato_after_durum | `2,12.0,150.0,2.0,80.,7.5,0,1,2,1,2` / `2,3000.,20.,40.,10.,2.4,0.42,0.5,0` / `6,40000.,15.,75.,100.,1.5,0.25,2.2,0` |
| v0_shipped_input_strategy4_FIXED | the package's own `input.txt`: `1,0.0,0.0,1.0,80.,7.0,0,0,4,1,2` / `1,2000.,20.,40.,80.,2.0,0.1,1.0,0` / `2,3000.,20.,40.,80.,2.0,0.1,1.0,0` |
| v6_bray_converted_once_FIXED | `3,20.0,150.0,2.0,80.,7.5,3,0,2,1,2` / rows as v1 |

Row 0: soil class, soil P, soil K, SOM %, CEC, pH, P method index, water supply, strategy,
tillage, number of crops. Crop rows: crop index in the table, yield kg/ha, CV %, HI %, Fres %,
N %, P %, K % of product DM, burning flag (applied by the script to the previous crop's residues).
