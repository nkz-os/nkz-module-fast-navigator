/** Shapes of the FaST API (backend `app/plans/service.py:_view`, `app/calc/sheet.py`, contract G1-G6). */

export interface Sourced<T = unknown> {
  value: T | null;
  provenance: string; // measured | table:<id> | declared | entered | estimated | missing
  source: string | null;
  note: string | null;
}

export interface Notice { code: string; params: Record<string, unknown> }
export interface MissingInput { field: string; owner: string; params: Record<string, unknown> }

export type PlanState = 'draft' | 'calculated' | 'in_review' | 'signed' | 'superseded';
export type SoilClass = 'low' | 'medium' | 'high';
export type DoseBasis = 'buildup' | 'buildup_and_export' | 'export' | 'half_export' | 'none';

/** G2: the main crop cycle chosen for the campaign. */
export interface CycleView {
  crop_id: string;
  start: { date: string | null; provenance: 'planned' | 'declared' | 'actual' | null };
  pending: boolean;
  status: string | null;
}

export interface SoilAnalysisRef {
  id: string;
  samplingDate: string | null;
  laboratoryReference: string | null;
  fields: string[];
}

/** G1: one parcel of a campaign. */
export interface CampaignParcel {
  id: string;
  name: string | null;
  area_ha: Sourced<number>;
  identifier: Sourced<string>;
  enclosures?: Enclosure[];
  farm: string | null;
  irrigation_regime: 'rainfed' | 'irrigated' | null;
  crop: Sourced<string>;
  previous_crop: Sourced<string>;
  previous_campaign: number | null;
  cycle: CycleView | null;
  /** EPPO of a cover crop grown right before the main crop: a hint, never a previous crop. */
  cover_before: string | null;
  analyses: SoilAnalysisRef[];
  notices: Notice[];
}
export interface CampaignParcels { campaign: number; parcels: CampaignParcel[] }

/** G3: an item of the plan list. */
export interface PlanListItem {
  id: string;
  farm: string;
  campaign: number;
  version: number;
  state: PlanState;
  row_version: number;
  calc_fresh: boolean;
  updated_at: string | null;
  findings: { block: number; warn: number; info: number };
  sheets_count: number;
  signed_at: string | null;
}

export interface NResult {
  min_kg_ha: number;
  avg_kg_ha: number;
  max_kg_ha: number;
  before_credits: { min_kg_ha: number; avg_kg_ha: number; max_kg_ha: number };
  levels_kg_ha: number[];
  terms_kg_ha: {
    crop_uptake: number; n_end: number; previous_residues: number; previous_roots: number;
    n_other: number; fixation: number; loss_divisor: number;
  };
  credits_kg_ha: { soil_mineral_n: number; organic_available_n: number; irrigation_n: number };
}

/** G5: P2O5 / K2O with the soil class decided by the engine. */
export interface OxideResult {
  rate_kg_ha: number;
  before_organic_kg_ha: number;
  exported_kg_ha: number;
  buildup_per_year_kg_ha: number;
  organic_credit_kg_ha: number;
  threshold_mg_kg: number | null;
  soil_class: SoilClass | null;
  high_from_mg_kg: number | null;
  basis: DoseBasis;
  strategy: 1 | 2 | 3 | 4;
}

export interface SheetResult {
  status: 'complete' | 'incomplete';
  provisional: boolean;
  n: NResult | null;
  p2o5: OxideResult | null;
  k2o: OxideResult | null;
  inputs: Record<string, Sourced | Record<string, unknown>>;
  notices: Notice[];
  missing: MissingInput[];
  versions: Record<string, string | null>;
}

export interface OrganicInput {
  material: string; rate_t_ha: number; n_pct: number; p2o5_pct: number; k2o_pct: number;
  /** Absent in sheets saved before the suggestions: read as declared. */
  composition_source?: 'table:mapa_guia_2010' | 'declared';
}

/** A SIGPAC enclosure the parcel overlaps; `selected` ones identify it in the plan. */
export interface Enclosure {
  reference: string;
  overlap_pct: number | null;
  overlap_ha?: number | null;
  sigpac_use?: string | null;
  selected?: boolean;
}

/** What a sheet stores: the SheetIn fields without key, parcels, applications, sigpac, overrides. */
export interface SheetInputs {
  campaign: number;
  tillage: boolean;
  irrigated: boolean;
  rotation_years: number;
  strategy: 1 | 2 | 3 | 4;
  previous_residues_burned: boolean;
  crop_eppo: string | null;
  previous_crop_eppo: string | null;
  /** What happens to the residues of the campaign crop: chosen on the plan. */
  residues?: 'left' | 'removed' | null;
  /** Same, for the previous crop (feeds the N term of its residues). */
  previous_residues?: 'left' | 'removed' | null;
  cycle_index: number;
  soil_analysis_id: string | null;
  nmin_analysis_id: string | null;
  declared_yields: Record<string, number>;
  previous_declared_yields: Record<string, number>;
  organic: OrganicInput[];
  water_m3_ha: number | null;
  water_quality_id: string | null;
  no3_mg_l: number | null;
  nuts: string | null;
  /** SIGPAC enclosures chosen per parcel URN; absent = the farmland ones. */
  enclosures?: Record<string, string[]>;
  [extra: string]: unknown;
}

export interface Override { param: string; value: number | string | boolean; reason: string; user_id: string; at: string }

/** An application (calendar) is opaque to S1: it travels back unchanged. */
export type ApplicationData = Record<string, unknown>;

export interface PlanSheet {
  key: string;
  seq: number;
  inputs: SheetInputs;
  overrides: Override[];
  parcels: { urn: string; sigpac: string | null }[];
  applications: ApplicationData[];
  n_adjustment: Record<string, unknown> | null;
  result: SheetResult | null;
  applications_summary: Record<string, unknown> | null;
}

export interface Finding {
  rule_id: string;
  severity: 'block' | 'warn' | 'info';
  params: Record<string, unknown> & { citation?: string };
  sheet_key?: string | null;
  sheet_id?: string | null;
}

export interface RainNormal {
  years: number[];
  annual_mm: number | null;
  monthly_mm: number[];
  sources: string[];
  notices: Notice[];
  attribution?: string;
}

export interface Signature {
  kind: 'advisor' | 'holder';
  name: string;
  registration_number?: string;
  closure_basis?: string;
  signed_at: string;
  [extra: string]: unknown;
}

export interface Plan {
  id: string;
  farm: string;
  campaign: number;
  version: number;
  state: PlanState;
  row_version: number;
  supersedes: string | null;
  calc_fresh: boolean;
  calculated_at: string | null;
  rain_normal: RainNormal | null;
  sheets: PlanSheet[];
  findings: Finding[];
  declarations: {
    vulnerable_zone: boolean | null; vulnerable_zone_source: string | null;
    voluntary_digital_notebook: boolean; irrigated_spring_2026: boolean | null;
  };
  signature: Signature | null;
  signed_at: string | null;
  snapshot_sha256: string | null;
  rules_version: string;
}

/** The body of PUT /plans/{id}/sheets for one sheet (overrides are never sent here). */
export interface PlanSheetIn extends SheetInputs {
  key: string;
  parcel_ids: string[];
  sigpac: Record<string, string>;
  applications: ApplicationData[];
}

export interface PdfEnvelope { filename: string; media_type: string; content_base64: string }

/** A saved zoning of a parcel (GET /plans/{id}/sheets/{key}/zonings). */
export interface ZoningInfo {
  run_id: string;
  method: string | null;
  variable: string | null;
  date: string | null;
  zone_count: number;
  has_vegetation_value: boolean;
}

export type ZoneStrategy = 'uniform' | 'potential' | 'compensate';
export type ZoneBasis = 'vigor' | 'sheet' | 'zone_soil';

/** The body of POST /plans/{id}/sheets/{key}/zone-doses (a dose of N given by the technician). */
export interface ZoneDosesRequest {
  parcel_urn: string;
  zoning_run_id: string;
  strategy: ZoneStrategy;
  cap_pct: number;
  target: { n_kg_ha: number; product?: { name: string; n_pct: number } };
}

export interface ZoneDoseRow {
  zone_id: string;
  label: string | null;
  rank: number | null;
  area_ha: number | null;
  basis: ZoneBasis;
  relative_vigor: number | null;
  factor: number | null;
  capped: boolean;
  n_kg_ha: number | null;
  product_kg_ha: number | null;
  soil_analysis: { id: string; date: string | null } | null;
  missing: string[];
}

export interface ZoneDosesResponse {
  plan: { id: string; state: string; campaign: number };
  sheet: { key: string; n_kg_ha: { min: number; avg: number; max: number } | null; crop: { eppo: string | null; n_fixing: boolean | null } };
  zoning: { run_id: string; method: string | null; variable: string | null; date: string | null; zone_count: number };
  strategy: ZoneStrategy;
  strategy_unavailable: string | null;
  target: { n_kg_ha: number | null; source: 'application' | 'given'; product: { name: string; n_pct: number } | null };
  cap: { pct: number; min_n_kg_ha: number | null; max_n_kg_ha: number | null };
  zones: ZoneDoseRow[];
  rest: { area_ha: number | null; n_kg_ha: number | null; product_kg_ha: number | null };
  totals: { area_ha: number | null; n_kg: number | null; mean_n_kg_ha: number | null; uniform_n_kg: number | null };
  notices: { code: string; params?: Record<string, string | number | null> }[];
  units: { n: string; product: string };
  versions: Record<string, string>;
}
