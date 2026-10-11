"""Oracle cases: outputs of the FertiliCalc reference script (GPL-3.0, F. Villalobos).

Each case was produced by running `fixtures/fertilicalc_reference/fertilicalc_script_231124.py`
with `crop_data_with_synthetic.csv` and the `input.txt` rows quoted in the case (see
`fixtures/fertilicalc_reference/README.md`). Expected tuples per crop:
(N_min, N_max, N_avg, P, K) in kg/ha of elemental N, P, K.

Two cases carry a documented script bug fixed (`*_FIXED`); their expected values come from
the script with exactly that line corrected.
"""
from app.engine import constants as C
from app.engine.texture import olsen_equivalent
from app.engine.types import CropParams, CropSeason, Management, SoilState

# crop_data.csv rows. Product N/P/K, HI and Fres come from the input.txt row of each crop
# (the script reads them there, not from the table).
SUNFLOWER = {"eppo": "HELAN", "crop_type": "industrial", "dm_product_pct": 91.5,
             "n_min_product_pct": 2.2, "n_residue_pct": 0.8, "p_residue_pct": 0.14,
             "k_residue_pct": 2.52, "n_fixing": False}
DURUM = {"eppo": "TRZDU", "crop_type": "cereal", "dm_product_pct": 87.5,
         "n_min_product_pct": 2.05, "n_residue_pct": 0.65, "p_residue_pct": 0.06,
         "k_residue_pct": 1.2, "n_fixing": False}
# Synthetic rows (test-only, marked "sintética" in the fixture CSV).
FABA = {"eppo": "VICFX", "crop_type": "grain_legume", "dm_product_pct": 88,
        "n_min_product_pct": 3.6, "n_residue_pct": 1.0, "p_residue_pct": 0.1,
        "k_residue_pct": 1.5, "n_fixing": True}
ALFALFA = {"eppo": "MEDSA", "crop_type": "forage_legume", "dm_product_pct": 90,
           "n_min_product_pct": 2.6, "n_residue_pct": 2.0, "p_residue_pct": 0.2,
           "k_residue_pct": 1.5, "n_fixing": True}
OLIVE = {"eppo": "OLVEU", "crop_type": "tree", "dm_product_pct": 50,
         "n_min_product_pct": 0.9, "n_residue_pct": 0.8, "p_residue_pct": 0.08,
         "k_residue_pct": 0.6, "n_fixing": False}
POTATO = {"eppo": "SOLTU", "crop_type": "tuber_root", "dm_product_pct": 21,
          "n_min_product_pct": 1.3, "n_residue_pct": 2.5, "p_residue_pct": 0.3,
          "k_residue_pct": 3.0, "n_fixing": False}


def season(base, y, cv, hi, fres, n, p, k, burn=0):
    crop = CropParams(**base, n_product_pct=n, p_product_pct=p, k_product_pct=k,
                      harvest_index_pct=hi, residue_left_pct=fres)
    # The script's per-row burning flag is applied to the PREVIOUS crop's residues.
    return CropSeason(crop, y, cv, previous_residues_burned=bool(burn))


def soil(cls, p, k, som, ph, p_method="olsen"):
    return SoilState(texture_class=cls, clay_pct=C.CLASS_CLAY[cls], ph=ph,
                     organic_matter_pct=som, p_olsen_mg_kg=olsen_equivalent(p, p_method),
                     k_mg_kg=k)


def rot_a():
    return [season(SUNFLOWER, 2000, 20, 35, 100, 2.95, 0.63, 0.72),
            season(DURUM, 3000, 20, 40, 10, 2.4, 0.42, 0.5)]


def durum():
    return season(DURUM, 3000, 20, 40, 10, 2.4, 0.42, 0.5)


# name -> (soil, management, rotation, expected per crop)
# input.txt row 0 = soil class, P, K, SOM, CEC, pH, P method, water supply, strategy, tillage, n.
CASES = {
    # 3,12,150,2.0,80,7.5,0,0,2,1,2
    "v1_strategy2": (soil(3, 12, 150, 2.0, 7.5), Management(2, True, False), rot_a(), [
        (49.66784121428572, 76.86310521428572, 63.26547321428572, 23.423024999999996, 13.176),
        (46.75748571428571, 78.77408571428572, 62.76578571428571, 25.04527499999999, 55.65)]),
    "v2_strategy1": (soil(3, 12, 150, 2.0, 7.5), Management(1, True, False), rot_a(), [
        (49.66784121428572, 76.86310521428572, 63.26547321428572, 11.894024999999994, 0.0),
        (46.75748571428571, 78.77408571428572, 62.76578571428571, 11.894024999999994, 0.0)]),
    "v3_strategy3": (soil(3, 12, 150, 2.0, 7.5), Management(3, True, False), rot_a(), [
        (61.53338121428571, 94.26256521428573, 77.89797321428573, 29.85802499999999, 73.176),
        (53.185285714285726, 88.90628571428572, 71.04578571428571, 31.48027499999999, 115.65)]),
    # 6,40,400,4.0,80,8.0,0,0,2,0,2 ; durum row burning=1
    "v4_rich_soil_no_tillage_burned": (
        soil(6, 40, 400, 4.0, 8.0), Management(2, False, False),
        [season(SUNFLOWER, 2000, 30, 35, 100, 2.95, 0.63, 0.72),
         season(DURUM, 3000, 10, 40, 10, 2.4, 0.42, 0.5, burn=1)], [
            (43.380900214285724, 84.17379621428574, 63.77734821428572, 5.7645, 0.0),
            (73.79363571428571, 89.80193571428569, 81.79778571428571, 6.575624999999999, 0.0)]),
    "v5_cv0": (soil(3, 12, 150, 2.0, 7.5), Management(2, True, False),
               [season(SUNFLOWER, 2000, 0, 35, 100, 2.95, 0.63, 0.72),
                season(DURUM, 3000, 0, 40, 10, 2.4, 0.42, 0.5)], [
        (63.26547321428572, 63.26547321428572, 63.26547321428572, 23.423024999999996, 13.176),
        (62.76578571428571, 62.76578571428571, 62.76578571428571, 25.04527499999999, 55.65)]),
    "vL1_faba_after_durum": (
        soil(3, 12, 150, 2.0, 7.5), Management(2, True, False),
        [durum(), season(FABA, 2500, 20, 40, 100, 4.0, 0.45, 1.1)], [
            (27.139199999999988, 59.1558, 43.147499999999994, 25.04527499999999, 55.65),
            (4.7312835000000035, 13.779091500000007, 9.255187500000005, 21.794024999999994,
             24.200000000000003)]),
    # 3,12,150,4.0,80,7.5,0,0,3,0,2
    "vL2_alfalfa_som4_no_tillage": (
        soil(3, 12, 150, 4.0, 7.5), Management(3, False, False),
        [season(ALFALFA, 9000, 15, 80, 10, 3.0, 0.25, 2.2), durum()], [
            (99.93548249999995, 134.22764249999992, 117.08156249999996, 42.22402499999999,
             265.5375),
            (28.917000000000016, 64.63799999999999, 46.7775, 31.48027499999999, 115.65)]),
    # 3,12,150,2.0,80,7.5,0,1,2,1,1
    "vT1_olive_irrigated": (
        soil(3, 12, 150, 2.0, 7.5), Management(2, True, True),
        [season(OLIVE, 5000, 25, 50, 100, 1.0, 0.12, 1.3)], [
            (27.15625, 41.59375000000001, 34.375, 26.788049999999988, 32.5)]),
    "vT2_olive_rainfed": (
        soil(3, 12, 150, 2.0, 7.5), Management(2, True, False),
        [season(OLIVE, 5000, 25, 50, 100, 1.0, 0.12, 1.3)], [
            (37.03125, 56.71875000000001, 46.875, 26.788049999999988, 32.5)]),
    # 2,12,150,2.0,80,7.5,0,1,2,1,2
    "vP_potato_after_durum": (
        soil(2, 12, 150, 2.0, 7.5), Management(2, True, True),
        [durum(), season(POTATO, 40000, 15, 75, 100, 1.5, 0.25, 2.2)], [
            (0.0, 26.455800000000004, 10.447499999999998, 29.12175, 55.65),
            (170.27214750000002, 224.46222749999995, 197.3671875, 51.0, 184.8)]),
    # input.txt shipped with the script (1,0.0,0.0,1.0,80.,7.0,0,0,4,1,2), strategy 4.
    # FIXED: script line `k_rate = p_exported` -> `k_rate = k_exported`.
    "v0_shipped_input_strategy4_FIXED": (
        soil(1, 0.0, 0.0, 1.0, 7.0), Management(4, True, False),
        [season(SUNFLOWER, 2000, 20, 40, 80, 2.0, 0.1, 1.0),
         season(DURUM, 3000, 20, 40, 80, 2.0, 0.1, 1.0)], [
            (28.515053999999992, 52.12644600000001, 40.32075000000001, 2.5986000000000002,
             32.1348),
            (53.959199999999996, 85.44659999999999, 69.70289999999999, 3.0974999999999997,
             35.699999999999996)]),
    # 3,20,150,2.0,80,7.5,3,0,2,1,2 (Bray). FIXED: the script multiplies soil P by the
    # method factor once per crop of the rotation; converted once here.
    "v6_bray_converted_once_FIXED": (
        soil(3, 20.0, 150.0, 2.0, 7.5, p_method="bray1"), Management(2, True, False), rot_a(), [
            (49.66784121428572, 76.86310521428572, 63.26547321428572, 29.000024999999997, 13.176),
            (46.75748571428571, 78.77408571428572, 62.76578571428571, 30.622274999999995,
             55.65)]),
}
