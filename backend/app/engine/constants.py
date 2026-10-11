"""Constants of the FertiliCalc balance.

Sources:
- Villalobos F.J. et al. (2020) FertiliCalc: A Decision Support System for Fertilizer
  Management. Int. J. Plant Production 14:299-308, Table 4 (N parameters) and Table 5
  (soil P test conversion to Olsen).
- FertiliCalc reference script `fertilicalc_script_231124.py` (F. Villalobos, GPL-3.0),
  which implements Villalobos & Fereres (2024) 2nd ed. Soil-class tables are copied
  from it verbatim.
"""

# --- Nitrogen (Table 4) ------------------------------------------------------------------
N_END_KG_HA = 10.0          # residual inorganic N at the end of the cycle
F_NR = 0.2                  # ratio N in roots / N in shoots
N_OTHER_KG_HA = 10.0        # atmospheric deposition (irrigation water is added on top)
N_LOSS_FRACTION = 0.0       # the reference script does not model losses (spec D2)
SOIL_NMIN_EFFICIENCY = 0.9  # efficiency of measured soil mineral N (paper, l. 255-259)

# Student t values of the 9 yield probability levels (script `t_i`, index 1..9).
T_LEVELS = (-1.29, -0.84, -0.525, -0.25, 0.0, 0.25, 0.525, 0.84, 1.29)
LEVEL_MIN, LEVEL_AVG, LEVEL_MAX = 1, 4, 7   # 0-based: script indices 2, 5, 8

# Trees (script `beta_pl`, `efic`).
TREE_BETA = 0.8
TREE_EFFICIENCY = 0.8

# --- Soil classes 1..6 (script tables, index 0 unused) -------------------------------------
CLASS_CLAY = (0, 3, 10, 18, 15, 34, 60)
CLASS_SAND = (0, 92, 65, 42, 20, 32, 20)
CLASS_BULK_DENSITY = (0, 1.68, 1.56, 1.43, 1.41, 1.31, 1.21)   # g/cm3
K_THRESHOLD_LOW = (0, 100.0, 150.0, 150.0, 150.0, 150.0, 200.0)   # mg/kg, strategies 1-2
K_THRESHOLD_HIGH = (0, 100.0, 175.0, 175.0, 175.0, 175.0, 300.0)  # mg/kg, strategies 3-4
K_FIX_LOW = (0, 1.1, 1.1, 1.5, 1.5, 2.0, 2.5)
K_FIX_HIGH = (0, 1.2, 1.2, 1.7, 1.7, 2.0, 5.0)
SAMPLING_DEPTH_M = 0.3

# --- P and K build-up ------------------------------------------------------------------------
P_BUILDUP_MAX_KG_HA_YEAR = 30.0
K_BUILDUP_MAX_KG_HA_YEAR = 60.0

# --- Oxides ----------------------------------------------------------------------------------
P_TO_P2O5 = 2.29
K_TO_K2O = 1.2047

# --- Soil P test -> Olsen (Table 5 of the paper; the script's 0.2 for ammonium lactate
# differs from the published 0.25 — the published table wins, spec §6) ---------------------
OLSEN_FACTOR = {
    "olsen": 1.0,
    "ammonium_lactate": 0.25,
    "mehlich3": 0.36,
    "bray1": 0.47,
    "ammonium_acetate_edta": 0.48,
    "calcium_lactate": 0.49,
    "calcium_lactate_acetate": 0.52,
    "water": 3.8,
    "cacl2": 25.0,
}

RICE_EPPO = "ORYSA"
RICE_P_THRESHOLD = 4.0
