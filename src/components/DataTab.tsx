import React, { useMemo, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button, FormField, FormGrid, Inline, Input, Select, Stack, Surface, Textarea } from '@nekazari/ui-kit';
import { deleteOverride, putOverride, putSheets } from '../api/fast';
import { useCrops } from '../hooks/useCrops';
import type { CampaignParcel, OrganicInput, Plan, PlanSheet, PlanSheetIn, SheetResult, Sourced } from '../api/types';
import { errorView } from '../model/errors';
import { formatDate, formatKgHa } from '../model/format';
import { mayAdjust, overrideRange } from '../model/overrides';
import { COEFFICIENT_PARAMS, formatParam, PARAMS, paramLabelKey, SOIL_PARAMS, WATER_PARAMS, YIELD_PARAMS } from '../model/params';
import type { Roles } from '../model/roles';
import { ORGANIC_MATERIALS } from '../model/organic';
import { applyPreviousCrop, editSheet, lacksPreviousCrop, ownerLink } from '../model/sheets';
import { CropLabel } from './CropLabel';
import { CropPicker } from './CropPicker';
import { DeclareYearForm } from './DeclareYearForm';
import { ErrorBanner } from './ErrorBanner';
import { ProvenanceChip, SourcedValue } from './ProvenanceChip';

const AUTO = '__auto__';

interface Props {
  plan: Plan;
  sheet: PlanSheet;
  parcels: CampaignParcel[];
  editable: boolean;
  roles: Roles;
  onSaved: (plan: Plan) => void;
  onReload: () => void;
}

/** "Adjust" beside a value: a number in the allowed range and a reason, stored with who and when. */
function AdjustControl({ plan, sheet, param, current, onSaved }: {
  plan: Plan; sheet: PlanSheet; param: string; current: number | null; onSaved: (p: Plan) => void;
}) {
  const { t } = useTranslation('fast-navigator');
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<string>(current == null ? '' : String(current));
  const [reason, setReason] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const existing = sheet.overrides.some((o) => o.param === param);
  const range = overrideRange(param);

  const run = async (fn: () => Promise<Plan>) => {
    setBusy(true); setError(null);
    try { onSaved(await fn()); setOpen(false); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const apply = () => run(() => putOverride(plan.id, sheet.key, param, plan.row_version, Number(value), reason.trim()));
  const clear = () => run(() => deleteOverride(plan.id, sheet.key, param, plan.row_version));

  return (
    <span className="inline-flex flex-col gap-nkz-tight">
      <Inline gap="tight" align="center">
        {!open && <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>{t('data.adjust')}</Button>}
        {existing && !open && <Button size="sm" variant="ghost" loading={busy} onClick={clear}>{t('data.unadjust')}</Button>}
      </Inline>
      {open && (
        <Surface variant="sunken" padding="inline">
          <Stack gap="tight">
            <FormField label={t(paramLabelKey(param), { defaultValue: param })}
              description={range ? t('data.range', { min: range[0], max: range[1] }) : undefined}>
              <Input type="number" value={value} min={range?.[0]} max={range?.[1]} step="any" onChange={(e) => setValue(e.target.value)} />
            </FormField>
            <FormField label={t('data.reason')} required>
              <Textarea value={reason} rows={2} maxLength={500} onChange={(e) => setReason(e.target.value)} />
            </FormField>
            {error != null && <ErrorBanner error={error} />}
            <Inline gap="inline">
              <Button size="sm" variant="primary" loading={busy} disabled={reason.trim() === '' || value === ''} onClick={apply}>{t('data.apply')}</Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>{t('common.close')}</Button>
            </Inline>
          </Stack>
        </Surface>
      )}
    </span>
  );
}

export function DataTab({ plan, sheet, parcels, editable, roles, onSaved, onReload }: Props) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  const result: SheetResult | null = sheet.result;
  const inputs = (result?.inputs ?? {}) as Record<string, Sourced & { value: unknown }>;
  const urns = sheet.parcels.map((p) => p.urn);
  const sheetIndex = plan.sheets.findIndex((s) => s.key === sheet.key);

  const [patch, setPatch] = useState<Partial<PlanSheetIn>>({});
  const [sigpac, setSigpac] = useState<Record<string, string>>({});
  const crops = useCrops(editable);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const dirty = Object.keys(patch).length > 0 || Object.keys(sigpac).length > 0;

  const val = <K extends keyof PlanSheetIn>(k: K): PlanSheetIn[K] => (k in patch ? (patch[k] as PlanSheetIn[K]) : (sheet.inputs[k as string] as PlanSheetIn[K]));
  const set = (p: Partial<PlanSheetIn>) => setPatch((cur) => ({ ...cur, ...p }));
  const fields = error != null ? errorView(error).fieldErrors ?? {} : {};
  const fieldError = (name: string) => fields[`sheets.${sheetIndex}.${name}`];

  const analyses = useMemo(() => {
    const seen = new Map<string, string>();
    for (const p of parcels) {
      if (!urns.includes(p.id)) continue;
      for (const a of p.analyses) seen.set(a.id, `${a.samplingDate ? formatDate(a.samplingDate, lang) : '—'} · ${a.laboratoryReference ?? a.id}`);
    }
    return [{ value: AUTO, label: t('data.auto') }, ...[...seen].map(([value, label]) => ({ value, label }))];
  }, [parcels, urns, lang, t]);

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const merged: Record<string, string> = {};
      for (const p of sheet.parcels) if (p.sigpac) merged[p.urn] = p.sigpac;
      for (const [urn, v] of Object.entries(sigpac)) { if (v.trim()) merged[urn] = v.trim().toUpperCase(); else delete merged[urn]; }
      onSaved(await putSheets(plan.id, plan.row_version, editSheet(plan, sheet.key, { ...patch, sigpac: merged })));
      setPatch({}); setSigpac({});
    } catch (e) {
      setError(e);
      if (errorView(e).reload) onReload();   // someone else saved first: reload, keep what was typed
    } finally { setSaving(false); }
  };

  const previousValue = val('previous_crop_eppo') as string | null;
  const prevResiduesNow = inputs['previous_crop.residue_left_pct']?.value;
  const prevResiduesChoice = (val('previous_residues') as 'left' | 'removed' | null | undefined)
    ?? (prevResiduesNow === 100 ? 'left' : prevResiduesNow === 0 ? 'removed' : null);
  // Hidden for a fallow: nothing was grown, so no residues.
  const previousIsFallow = previousValue === 'fallow' || (previousValue == null && inputs['previous_crop.eppo']?.value === 'fallow');
  const othersLackingPrevious = plan.sheets.filter((s) => s.key !== sheet.key && lacksPreviousCrop(s)).length;
  const applyPreviousToAll = async () => {
    if (!previousValue) return;
    setSaving(true); setError(null);
    try {
      onSaved(await putSheets(plan.id, plan.row_version, applyPreviousCrop(plan, sheet.key, { ...patch }, previousValue, prevResiduesChoice)));
      setPatch({});
    } catch (e) {
      setError(e);
      if (errorView(e).reload) onReload();
    } finally { setSaving(false); }
  };
  const coverSpecies = [...new Set(parcels.filter((p) => urns.includes(p.id)).map((p) => p.cover_before).filter((c): c is string => !!c))];

  const num = (v: string): number | null => (v === '' ? null : Number(v));

  const row = (param: string) => {
    const s = inputs[param];
    const info = PARAMS[param];
    const current = s && typeof s.value === 'number' ? s.value : null;
    return (
      <Inline key={param} gap="inline" align="center" wrap>
        <span className="w-64 text-nkz-sm text-nkz-text-secondary">{t(paramLabelKey(param), { defaultValue: param })}</span>
        <SourcedValue value={s} unit={param === 'yield.kg_ha' ? t('data.yieldUnit') : (info?.unit ?? undefined)} format={(v) => formatParam(param, v, lang)} />
        {editable && mayAdjust(param, roles) && <AdjustControl plan={plan} sheet={sheet} param={param} current={current} onSaved={onSaved} />}
      </Inline>
    );
  };

  // What is missing, once per kind and owner, with where to put it.
  const missing = useMemo(() => {
    const out = new Map<string, { group: string; owner: string; field: string; count: number }>();
    for (const m of result?.missing ?? []) {
      const group = m.field.split('.')[0];
      const k = `${group}|${m.owner}`;
      const cur = out.get(k);
      if (cur) cur.count += 1; else out.set(k, { group, owner: m.owner, field: m.field, count: 1 });
    }
    return [...out.values()];
  }, [result]);

  const organic = val('organic') as OrganicInput[];
  const declared = val('declared_yields') as Record<string, number>;
  const canAddYear = editable;
  // The button that is "on": the pending choice, else the stored one, else what the value says (100 / 0).
  const residueNow = inputs['crop.residue_left_pct']?.value;
  const residueChoice = (val('residues') as 'left' | 'removed' | null | undefined)
    ?? (residueNow === 100 ? 'left' : residueNow === 0 ? 'removed' : null);
  const materialOptions = ORGANIC_MATERIALS.map((m) => ({ value: m, label: t(`data.organic.materials.${m}`) }));
  const organicIncomplete = organic.some((o) => !(ORGANIC_MATERIALS as readonly string[]).includes(o.material));

  return (
    <Stack gap="stack">
      {result && result.missing.length > 0 && (
        <Surface variant="sunken" padding="stack">
          <Stack gap="tight">
            <p className="font-medium text-nkz-warning">{t('data.missing.title', { count: result.missing.length })}</p>
            {missing.map((m) => {
              const link = ownerLink(m.owner, urns, m.field);
              return (
                <Inline key={`${m.group}|${m.owner}`} gap="inline" align="center" wrap>
                  <span className="text-nkz-sm text-nkz-text-primary">✕ {t(`missing.${m.group}`, { defaultValue: m.group })}</span>
                  <span className="text-nkz-xs text-nkz-text-muted">{t('data.missing.owner', { owner: t(`owner.${m.owner}`, { defaultValue: m.owner }) })}</span>
                  {link.href
                    ? <a className="underline text-nkz-sm" href={link.href}>{t(link.key)}</a>
                    : <span className="text-nkz-sm text-nkz-text-secondary">{t(link.key)}</span>}
                </Inline>
              );
            })}
          </Stack>
        </Surface>
      )}

      {result && result.notices.length > 0 && (
        <Stack gap="tight">
          {result.notices.map((n, i) => (
            <p key={`${n.code}-${i}`} className="text-nkz-sm text-nkz-warning">
              ⚠ {t(`notice.${n.code}`, { ...(n.params as Record<string, string>), defaultValue: `${n.code} ${JSON.stringify(n.params)}` })}
            </p>
          ))}
        </Stack>
      )}

      {!result && <p className="text-nkz-sm text-nkz-text-secondary">{t('data.notCalculated')}</p>}

      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 id="field-crop" className="font-semibold text-nkz-text-primary">{t('data.section.crop')}</h3>
          <Inline gap="inline" align="center" wrap>
            <span className="w-64 text-nkz-sm text-nkz-text-secondary">{t('data.crop')}</span>
            <CropLabel eppo={(inputs['crop.eppo']?.value as string | null) ?? sheet.inputs.crop_eppo} />
            <ProvenanceChip value={inputs['crop.eppo']} />
          </Inline>
          <Inline gap="inline" align="center" wrap>
            <span className="w-64 text-nkz-sm text-nkz-text-secondary">{t('data.previousCrop')}</span>
            <CropLabel eppo={(inputs['previous_crop.eppo']?.value as string | null) ?? sheet.inputs.previous_crop_eppo} />
            <ProvenanceChip value={inputs['previous_crop.eppo']} />
          </Inline>
          <Inline gap="inline" align="center" wrap>
            <span className="w-64 text-nkz-sm text-nkz-text-secondary">{t('data.coefficients')}</span>
            <ProvenanceChip value={inputs['crop.n_product_pct']} />
          </Inline>
          <Inline gap="inline" align="center" wrap>
            <span className="w-64 text-nkz-sm text-nkz-text-secondary">{t('data.residues.label')}</span>
            <Button size="sm" variant={residueChoice === 'left' ? 'primary' : 'secondary'} disabled={!editable}
              aria-pressed={residueChoice === 'left'} onClick={() => set({ residues: 'left' })}>{t('data.residues.left')}</Button>
            <Button size="sm" variant={residueChoice === 'removed' ? 'primary' : 'secondary'} disabled={!editable}
              aria-pressed={residueChoice === 'removed'} onClick={() => set({ residues: 'removed' })}>{t('data.residues.removed')}</Button>
            {'residues' in patch
              ? <span className="text-nkz-sm text-nkz-text-muted">{t('data.residues.pending')}</span>
              : <SourcedValue value={inputs['crop.residue_left_pct']} unit={t('data.residues.unit')} format={(v) => formatParam('crop.residue_left_pct', v, lang)} />}
          </Inline>
          {roles.technician && result && (
            <details>
              <summary className="cursor-pointer text-nkz-sm text-nkz-text-secondary">{t('data.coefficientsAll')}</summary>
              <Stack gap="tight">{COEFFICIENT_PARAMS.map(row)}</Stack>
            </details>
          )}
          {coverSpecies.map((c) => (
            <p key={c} className="text-nkz-sm text-nkz-text-secondary">{t('data.coverBefore')} <CropLabel eppo={c} /></p>
          ))}
          {editable && (
            <FormGrid columns={2}>
              <FormField label={t('data.declaredCrop')} description={t('data.declaredCropHint')} error={fieldError('crop_eppo')}>
                <CropPicker crops={crops.data} loading={crops.loading} failed={crops.error != null}
                  value={(val('crop_eppo') as string | null) ?? null} ariaLabel={t('data.declaredCrop')}
                  onChange={(v) => set({ crop_eppo: v })} />
              </FormField>
              <FormField label={t('data.declaredPrevious')} description={t('data.declaredPreviousHint')} error={fieldError('previous_crop_eppo')}>
                <Stack gap="tight">
                  <CropPicker crops={crops.data} loading={crops.loading} failed={crops.error != null} allowFallow
                    value={previousValue} ariaLabel={t('data.declaredPrevious')}
                    onChange={(v) => set({ previous_crop_eppo: v })} />
                  {!previousIsFallow && (previousValue != null || inputs['previous_crop.eppo']?.value != null) && (
                    <Inline gap="inline" align="center" wrap>
                      <span className="text-nkz-sm text-nkz-text-secondary">{t('data.previousResidues.label')}</span>
                      <Button size="sm" variant={prevResiduesChoice === 'left' ? 'primary' : 'secondary'}
                        aria-pressed={prevResiduesChoice === 'left'} onClick={() => set({ previous_residues: 'left' })}>{t('data.previousResidues.left')}</Button>
                      <Button size="sm" variant={prevResiduesChoice === 'removed' ? 'primary' : 'secondary'}
                        aria-pressed={prevResiduesChoice === 'removed'} onClick={() => set({ previous_residues: 'removed' })}>{t('data.previousResidues.removed')}</Button>
                      {'previous_residues' in patch
                        ? <span className="text-nkz-sm text-nkz-text-muted">{t('data.residues.pending')}</span>
                        : <SourcedValue value={inputs['previous_crop.residue_left_pct']} unit={t('data.residues.unit')} format={(v) => formatParam('crop.residue_left_pct', v, lang)} />}
                    </Inline>
                  )}
                  {previousValue && othersLackingPrevious > 0 && (
                    <Button size="sm" variant="secondary" loading={saving} onClick={applyPreviousToAll}>
                      {t('data.applyPreviousToAll', { count: othersLackingPrevious })}
                    </Button>
                  )}
                </Stack>
              </FormField>
            </FormGrid>
          )}
          {editable && crops.error != null && <ErrorBanner error={crops.error} onRetry={crops.retry} />}
        </Stack>
      </Surface>

      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 id="field-yield" className="font-semibold text-nkz-text-primary">{t('data.section.yield')}</h3>
          {YIELD_PARAMS.map(row)}
          <p className="text-nkz-xs text-nkz-text-muted">{t('data.yieldHelp')}</p>
          <p className="text-nkz-xs text-nkz-text-muted">{t('data.cvHelp')}</p>
          {inputs['yield.basis'] && (
            <p className="text-nkz-xs text-nkz-text-muted">
              {t(`data.basis.${String((inputs['yield.basis'] as { value?: string }).value)}`, { defaultValue: String((inputs['yield.basis'] as { value?: string }).value) })}
              {' '}{((inputs['yield.basis'] as unknown as { years?: number[] }).years ?? []).join(', ')}
            </p>
          )}
          {Object.entries(declared).map(([year, kg]) => (
            <Inline key={year} gap="inline" align="center">
              <span className="w-64 text-nkz-sm text-nkz-text-secondary">{t('data.declaredYield', { year })}</span>
              {editable ? (
                <>
                  <Input type="number" value={kg} min={1} step="any" aria-label={t('data.declaredYield', { year })}
                    onChange={(e) => { const n = num(e.target.value); const next = { ...declared }; if (n === null) delete next[year]; else next[year] = n; set({ declared_yields: next }); }} />
                  <span className="text-nkz-sm text-nkz-text-secondary">{t('data.yieldUnit')}</span>
                  <Button size="sm" variant="ghost" onClick={() => { const next = { ...declared }; delete next[year]; set({ declared_yields: next }); }}>{t('data.organic.remove')}</Button>
                </>
              ) : <span>{formatKgHa(kg, lang)} {t('data.yieldUnit')}</span>}
              <ProvenanceChip value={{ value: kg, provenance: 'declared', source: 'plan', note: null }} />
            </Inline>
          ))}
          {canAddYear && (
            <DeclareYearForm campaign={plan.campaign} declared={declared}
              onAdd={(y, kg) => set({ declared_yields: { ...declared, [String(y)]: kg } })} />
          )}
          {fieldError('declared_yields') && <p role="alert" className="text-nkz-sm text-nkz-danger">{fieldError('declared_yields')}</p>}
        </Stack>
      </Surface>

      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 id="field-soil" className="font-semibold text-nkz-text-primary">{t('data.section.soil')}</h3>
          {inputs['soil.analysis_id'] && (
            <p className="text-nkz-sm text-nkz-text-secondary">
              {t('data.analysis', { id: String((inputs['soil.analysis_id'] as { value?: unknown }).value ?? '—'),
                date: formatDate((inputs['soil.analysis_id'] as { sampling_date?: string | null }).sampling_date, lang) })}
            </p>
          )}
          {SOIL_PARAMS.map(row)}
          {editable && (
            <FormGrid columns={2}>
              <FormField label={t('data.soilAnalysis')}>
                <Select value={(val('soil_analysis_id') as string | null) ?? AUTO} options={analyses}
                  onValueChange={(v) => set({ soil_analysis_id: v === AUTO ? null : v })} />
              </FormField>
              <FormField label={t('data.nminAnalysis')}>
                <Select value={(val('nmin_analysis_id') as string | null) ?? AUTO} options={analyses}
                  onValueChange={(v) => set({ nmin_analysis_id: v === AUTO ? null : v })} />
              </FormField>
            </FormGrid>
          )}
        </Stack>
      </Surface>

      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 id="field-irrigation" className="font-semibold text-nkz-text-primary">{t('data.section.water')}</h3>
          {sheet.inputs.irrigated ? WATER_PARAMS.map(row) : <p className="text-nkz-sm text-nkz-text-secondary">{t('data.rainfed')}</p>}
          {editable && sheet.inputs.irrigated && (
            <FormGrid columns={2}>
              <FormField label={t('param.irrigation_water_m3_ha')} error={fieldError('water_m3_ha')}>
                <Input type="number" min={0} step="any" value={(val('water_m3_ha') as number | null) ?? ''} onChange={(e) => set({ water_m3_ha: num(e.target.value) })} />
              </FormField>
              <FormField label={t('param.irrigation_no3_mg_l')} error={fieldError('no3_mg_l')}>
                <Input type="number" min={0} step="any" value={(val('no3_mg_l') as number | null) ?? ''} onChange={(e) => set({ no3_mg_l: num(e.target.value) })} />
              </FormField>
            </FormGrid>
          )}
        </Stack>
      </Surface>

      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 id="field-organic" className="font-semibold text-nkz-text-primary">{t('data.section.organic')}</h3>
          {organic.length === 0 && <p className="text-nkz-sm text-nkz-text-secondary">{t('data.noOrganic')}</p>}
          {organic.map((o, i) => {
            const param = `organic.${i}.availability`;
            const a = inputs[param];
            const edit = (p: Partial<OrganicInput>) => set({ organic: organic.map((x, j) => (j === i ? { ...x, ...p } : x)) });
            return (
              <Stack key={i} gap="tight">
                {editable ? (
                  <FormGrid columns={3}>
                    <FormField label={t('data.organic.material')} error={fieldError(`organic.${i}.material`)}>
                      <Select value={o.material} placeholder={t('wizard.form.choose')} options={materialOptions} onValueChange={(v) => edit({ material: v })} />
                    </FormField>
                    <FormField label={t('data.organic.rate')}><Input type="number" min={0} step="any" value={o.rate_t_ha} onChange={(e) => edit({ rate_t_ha: Number(e.target.value) })} /></FormField>
                    <FormField label={t('data.organic.n')}><Input type="number" min={0} step="any" value={o.n_pct} onChange={(e) => edit({ n_pct: Number(e.target.value) })} /></FormField>
                    <FormField label={t('data.organic.p2o5')}><Input type="number" min={0} step="any" value={o.p2o5_pct} onChange={(e) => edit({ p2o5_pct: Number(e.target.value) })} /></FormField>
                    <FormField label={t('data.organic.k2o')}><Input type="number" min={0} step="any" value={o.k2o_pct} onChange={(e) => edit({ k2o_pct: Number(e.target.value) })} /></FormField>
                    <div className="flex items-end">
                      <Button size="sm" variant="danger" onClick={() => set({ organic: organic.filter((_, j) => j !== i) })}>{t('data.organic.remove')}</Button>
                    </div>
                  </FormGrid>
                ) : (
                  <p className="text-nkz-sm text-nkz-text-primary">{t(`data.organic.materials.${o.material}`, { defaultValue: o.material })} · {o.rate_t_ha} t/ha · N {o.n_pct} % · P₂O₅ {o.p2o5_pct} % · K₂O {o.k2o_pct} %</p>
                )}
                <Inline gap="inline" align="center" wrap>
                  <span className="w-64 text-nkz-sm text-nkz-text-secondary">{t('data.organic.availability')}</span>
                  <SourcedValue value={a} format={(v) => formatParam('irrigation.uptake', v, lang)} />
                  {editable && mayAdjust(param, roles) && (
                    <AdjustControl plan={plan} sheet={sheet} param={param} current={a && typeof a.value === 'number' ? a.value : null} onSaved={onSaved} />
                  )}
                </Inline>
              </Stack>
            );
          })}
          {editable && organic.length < 20 && (
            <Button size="sm" variant="ghost" onClick={() => set({ organic: [...organic, { material: '', rate_t_ha: 0, n_pct: 0, p2o5_pct: 0, k2o_pct: 0 }] })}>
              {t('data.organic.add')}
            </Button>
          )}
        </Stack>
      </Surface>

      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 id="field-parcel" className="font-semibold text-nkz-text-primary">{t('data.section.parcels')}</h3>
          {sheet.parcels.map((p) => {
            const name = parcels.find((x) => x.id === p.urn)?.name ?? p.urn;
            const id = inputs[`parcel.${p.urn}.identifier`];
            const known = !!p.sigpac || (id != null && id.value != null && id.provenance !== 'missing');
            const typed = sigpac[p.urn];
            return (
              <Inline key={p.urn} gap="inline" align="center" wrap>
                <span className="w-64 text-nkz-sm text-nkz-text-primary">{name}</span>
                {known
                  ? <span className="text-nkz-sm">{p.sigpac ?? String(id?.value)}</span>
                  : <span className="text-nkz-sm text-nkz-text-muted">—</span>}
                <ProvenanceChip value={p.sigpac ? { value: p.sigpac, provenance: 'declared', source: 'plan', note: null } : id} />
                {editable && (
                  <FormField label={known ? t('data.sigpacLabel') : t('data.sigpacWrite')} error={fieldError('sigpac')}>
                    <Input value={typed ?? p.sigpac ?? ''} placeholder="31:201:0:0:12:45:1"
                      onChange={(e) => setSigpac((cur) => ({ ...cur, [p.urn]: e.target.value }))} />
                  </FormField>
                )}
                {!editable && !known && <span className="text-nkz-sm text-nkz-warning">{t('data.sigpacWrite')}</span>}
              </Inline>
            );
          })}
          {editable && (
            <FormField label={t('data.nuts')} error={fieldError('nuts')}>
              <Input value={(val('nuts') as string | null) ?? ''} placeholder="ES22" onChange={(e) => set({ nuts: e.target.value.toUpperCase().trim() || null })} />
            </FormField>
          )}
          {inputs['region.nuts'] && (
            <Inline gap="inline" align="center">
              <span className="w-64 text-nkz-sm text-nkz-text-secondary">{t('data.nuts')}</span>
              <SourcedValue value={inputs['region.nuts']} format={(v) => String(v)} />
            </Inline>
          )}
        </Stack>
      </Surface>

      {error != null && <ErrorBanner error={error} />}
      {editable && (
        <Inline gap="inline" align="center">
          <Button variant="primary" disabled={!dirty || organicIncomplete} loading={saving} onClick={save}>{t('data.save')}</Button>
          {organicIncomplete && <span role="alert" className="text-nkz-sm text-nkz-warning">{t('data.organic.chooseMaterial')}</span>}
          {dirty && <Button variant="ghost" onClick={() => { setPatch({}); setSigpac({}); setError(null); }}>{t('data.discard')}</Button>}
        </Inline>
      )}
    </Stack>
  );
}
