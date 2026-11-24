import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button, Checkbox, FormField, FormGrid, Inline, Input, Select, Stack, Surface, Textarea } from '@nekazari/ui-kit';
import { deleteNAdjustment, putNAdjustment, putSheets } from '../api/fast';
import type {
  AnnexVCode, ApplicationData, ApplicationKind, ApplicationMethod, NAdjustment,
  NAdjustmentBasis, NitrogenForm, Plan, PlanSheet,
} from '../api/types';
import { formatKgHa } from '../model/format';
import type { Roles } from '../model/roles';
import { toSheetIn } from '../model/sheets';
import { ErrorBanner } from './ErrorBanner';

const KINDS: ApplicationKind[] = ['mineral', 'urea', 'urea_solution', 'organo_mineral', 'organic'];
const N_FORMS: NitrogenForm[] = ['ammoniacal', 'nitric', 'ureic', 'organic', 'mixed'];
const METHODS: ApplicationMethod[] = ['broadcast', 'localized', 'band', 'injection', 'incorporated', 'fertigation', 'foliar', 'other'];
const ANNEX_V_A: AnnexVCode[] = ['A.a', 'A.b', 'A.c', 'A.d', 'A.e', 'A.f', 'A.g', 'A.h', 'A.i'];
const ANNEX_V_B: AnnexVCode[] = ['B.a', 'B.b', 'B.c', 'B.d', 'B.e', 'B.f', 'B.g', 'B.h', 'B.i'];

interface Props {
  plan: Plan;
  sheet: PlanSheet;
  editable: boolean;
  roles: Roles;
  onSaved: (plan: Plan) => void;
}

export function ApplicationsTab({ plan, sheet, editable, roles, onSaved }: Props) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  const apps = sheet.applications ?? [];
  const summary = sheet.applications_summary as {
    mineral_n_kg_ha?: number; organic_n_total_kg_ha?: number; p2o5_kg_ha?: number; k2o_kg_ha?: number;
  } | null;

  // New application form state
  const [adding, setAdding] = useState(false);
  const [stage, setStage] = useState('pre_plant');
  const [plannedDate, setPlannedDate] = useState('');
  const [kind, setKind] = useState<ApplicationKind>('mineral');
  const [productName, setProductName] = useState('');
  const [registryRef, setRegistryRef] = useState('');
  const [organicIndex, setOrganicIndex] = useState('0');
  const [rate, setRate] = useState('');
  const [nPct, setNPct] = useState('0');
  const [pPct, setPPct] = useState('0');
  const [kPct, setKPct] = useState('0');
  const [nForm, setNForm] = useState<NitrogenForm>('ammoniacal');
  const [nUreicPct, setNUreicPct] = useState('');
  const [method, setMethod] = useState<ApplicationMethod>('broadcast');
  const [machine, setMachine] = useState('');
  const [annexV, setAnnexV] = useState<AnnexVCode[]>([]);
  const [otherMeasure, setOtherMeasure] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Justified N adjustment (Anexo III-I.3, technician only)
  const existingAdj = sheet.n_adjustment as NAdjustment | null;
  const [adjOpen, setAdjOpen] = useState(false);
  const [adjBasis, setAdjBasis] = useState<NAdjustmentBasis>(existingAdj?.basis ?? 'foliar_analysis');
  const [adjDate, setAdjDate] = useState(existingAdj?.date ?? new Date().toISOString().slice(0, 10));
  const [adjRef, setAdjRef] = useState(existingAdj?.reference ?? '');
  const [adjDesc, setAdjDesc] = useState(existingAdj?.description ?? '');
  const [adjN, setAdjN] = useState(existingAdj ? String(existingAdj.justified_n_kg_ha) : '');
  const [adjBusy, setAdjBusy] = useState(false);
  const [adjError, setAdjError] = useState<unknown>(null);

  const isOrganic = kind === 'organic';
  const needsAnnexA = kind === 'organic' || kind === 'organo_mineral';
  const needsAnnexB = kind === 'urea' || kind === 'urea_solution'
    || ((kind === 'mineral' || kind === 'organo_mineral') && (nForm === 'ureic' || Number(nUreicPct) > 0));

  const toggleAnnex = (code: AnnexVCode, checked: boolean) => {
    setAnnexV((prev) => (checked ? [...new Set([...prev, code])] : prev.filter((c) => c !== code)));
  };

  const saveApps = async (nextApps: ApplicationData[]) => {
    setBusy(true);
    setError(null);
    try {
      const sheets = plan.sheets.map((s) => {
        const base = toSheetIn(s, plan.campaign);
        return s.key === sheet.key ? { ...base, applications: nextApps } : base;
      });
      const updated = await putSheets(plan.id, plan.row_version, sheets);
      onSaved(updated);
      setAdding(false);
      setProductName('');
      setRegistryRef('');
      setRate('');
      setNPct('0');
      setPPct('0');
      setKPct('0');
      setNUreicPct('');
      setMachine('');
      setAnnexV([]);
      setOtherMeasure('');
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const handleAdd = () => {
    const base: ApplicationData = {
      stage: stage.trim() || 'pre_plant',
      planned_date: plannedDate || null,
      kind,
      product_name: productName.trim(),
      registry_ref: registryRef.trim() || null,
      method,
      machine: machine.trim(),
      annex_v: annexV,
      other_measure: otherMeasure.trim() || null,
    };
    if (isOrganic) {
      base.organic_index = Number(organicIndex);
    } else {
      const n = Number(nPct) || 0;
      base.product_rate_kg_ha = Number(rate);
      base.n_pct = n;
      base.p2o5_pct = Number(pPct) || 0;
      base.k2o_pct = Number(kPct) || 0;
      if (n > 0) {
        base.n_form = nForm;
        if (nForm === 'mixed') {
          base.n_ureic_pct = Number(nUreicPct);
        } else if (nForm === 'ureic' && nUreicPct.trim() !== '') {
          base.n_ureic_pct = Number(nUreicPct);
        }
      }
    }
    saveApps([...apps, base]);
  };

  const canSaveApp = Boolean(productName.trim() && machine.trim()) && (
    isOrganic
      ? (sheet.inputs.organic || []).length > 0
      : (
        Number(rate) > 0
        && !(Number(nPct) > 0 && nForm === 'mixed' && nUreicPct.trim() === '')
        && !(Number(nPct) > 0 && nForm === 'ureic' && nUreicPct.trim() !== '' && Number(nUreicPct) <= 0)
      )
  );
  const canSaveAdj = Boolean(
    plan.calc_fresh
    && sheet.result
    && adjDesc.trim()
    && Number(adjN) > 0
    && Number(adjN) <= 1000
    && (adjBasis === 'year_evolution' || adjRef.trim() !== ''),
  );

  const handleDelete = (idx: number) => {
    saveApps(apps.filter((_, i) => i !== idx));
  };

  const handleSaveAdj = async () => {
    setAdjBusy(true);
    setAdjError(null);
    try {
      const updated = await putNAdjustment(plan.id, sheet.key, plan.row_version, {
        basis: adjBasis,
        date: adjDate,
        reference: adjRef.trim() || null,
        description: adjDesc.trim(),
        justified_n_kg_ha: Number(adjN),
      });
      onSaved(updated);
      setAdjOpen(false);
    } catch (e) {
      setAdjError(e);
    } finally {
      setAdjBusy(false);
    }
  };

  const handleClearAdj = async () => {
    setAdjBusy(true);
    setAdjError(null);
    try {
      const updated = await deleteNAdjustment(plan.id, sheet.key, plan.row_version);
      onSaved(updated);
    } catch (e) {
      setAdjError(e);
    } finally {
      setAdjBusy(false);
    }
  };

  return (
    <Stack gap="stack">
      {/* Planned vs calculated summary */}
      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <Inline gap="inline" align="center" justify="between" wrap>
            <h3 className="font-semibold text-nkz-text-primary">{t('applications.title')}</h3>
            {editable && !adding && (
              <Button size="sm" variant="primary" onClick={() => setAdding(true)}>
                + {t('applications.add')}
              </Button>
            )}
          </Inline>
          {summary && (
            <Inline gap="inline" wrap>
              <Badge intent="info">N min.: {formatKgHa(summary.mineral_n_kg_ha ?? 0, lang)} {t('common.unit.kgHa')}</Badge>
              <Badge intent="default">N org.: {formatKgHa(summary.organic_n_total_kg_ha ?? 0, lang)} {t('common.unit.kgHa')}</Badge>
              <Badge intent="default">P₂O₅: {formatKgHa(summary.p2o5_kg_ha ?? 0, lang)} {t('common.unit.kgHa')}</Badge>
              <Badge intent="default">K₂O: {formatKgHa(summary.k2o_kg_ha ?? 0, lang)} {t('common.unit.kgHa')}</Badge>
            </Inline>
          )}
        </Stack>
      </Surface>

      {error != null && <ErrorBanner error={error} planState={plan.state} />}

      {/* Existing planned applications */}
      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          {apps.length === 0 ? (
            <p className="text-nkz-sm text-nkz-text-secondary">{t('applications.empty')}</p>
          ) : (
            apps.map((app, i) => (
              <Surface key={i} variant="sunken" padding="inline">
                <Inline gap="inline" align="center" justify="between" wrap>
                  <Stack gap="tight">
                    <Inline gap="tight" align="center" wrap>
                      <strong className="text-nkz-sm text-nkz-text-primary">{app.product_name}</strong>
                      <Badge intent="default">{app.kind}</Badge>
                      <span className="text-nkz-xs text-nkz-text-secondary">{app.stage}</span>
                      {app.planned_date && <span className="text-nkz-xs text-nkz-text-muted">{app.planned_date}</span>}
                    </Inline>
                    <p className="text-nkz-xs text-nkz-text-secondary">
                      {app.kind === 'organic'
                        ? `${t('applications.organicRef')} #${(app.organic_index ?? 0) + 1}`
                        : `${app.product_rate_kg_ha ?? 0} ${t('common.unit.kgHa')} · N ${app.n_pct ?? 0}% / P₂O₅ ${app.p2o5_pct ?? 0}% / K₂O ${app.k2o_pct ?? 0}%`}
                      {' · '}{app.method} · {app.machine}
                      {(app.annex_v?.length ?? 0) > 0 ? ` · Anexo V: ${app.annex_v?.join(', ')}` : ''}
                    </p>
                  </Stack>
                  {editable && (
                    <Button size="sm" variant="danger" loading={busy} onClick={() => handleDelete(i)}>
                      {t('applications.remove')}
                    </Button>
                  )}
                </Inline>
              </Surface>
            ))
          )}
        </Stack>
      </Surface>

      {/* Add application form */}
      {editable && adding && (
        <Surface variant="raised" padding="stack">
          <Stack gap="inline">
            <h4 className="font-semibold text-nkz-text-primary">{t('applications.newTitle')}</h4>
            <FormGrid columns={2}>
              <FormField label={t('applications.kind')}>
                <Select
                  value={kind}
                  onValueChange={(v) => setKind(v as ApplicationKind)}
                  options={KINDS.map((k) => ({ value: k, label: k }))}
                />
              </FormField>
              <FormField label={t('applications.product')}>
                <Input value={productName} onChange={(e) => setProductName(e.target.value)} />
              </FormField>
              <FormField label={t('applications.stage')}>
                <Input value={stage} onChange={(e) => setStage(e.target.value)} />
              </FormField>
              <FormField label={t('applications.date')}>
                <Input type="date" value={plannedDate} onChange={(e) => setPlannedDate(e.target.value)} />
              </FormField>
              <FormField label={t('applications.method')}>
                <Select
                  value={method}
                  onValueChange={(v) => setMethod(v as ApplicationMethod)}
                  options={METHODS.map((m) => ({ value: m, label: m }))}
                />
              </FormField>
              <FormField label={t('applications.machine')}>
                <Input value={machine} onChange={(e) => setMachine(e.target.value)} />
              </FormField>
            </FormGrid>

            {isOrganic ? (
              <FormField label={t('applications.organicIndex')}>
                <Select
                  value={organicIndex}
                  onValueChange={setOrganicIndex}
                  options={(sheet.inputs.organic || []).map((o, idx) => ({
                    value: String(idx),
                    label: `#${idx + 1} ${o.material} (${o.rate_t_ha} t/ha)`,
                  }))}
                />
              </FormField>
            ) : (
              <FormGrid columns={3}>
                <FormField label={t('applications.rate')}>
                  <Input type="number" value={rate} onChange={(e) => setRate(e.target.value)} />
                </FormField>
                <FormField label="N (%)">
                  <Input type="number" value={nPct} onChange={(e) => setNPct(e.target.value)} />
                </FormField>
                <FormField label="P₂O₅ (%)">
                  <Input type="number" value={pPct} onChange={(e) => setPPct(e.target.value)} />
                </FormField>
                <FormField label="K₂O (%)">
                  <Input type="number" value={kPct} onChange={(e) => setKPct(e.target.value)} />
                </FormField>
                <FormField label={t('applications.nForm')}>
                  <Select
                    value={nForm}
                    onValueChange={(v) => setNForm(v as NitrogenForm)}
                    options={N_FORMS.map((f) => ({ value: f, label: f }))}
                  />
                </FormField>
                {(nForm === 'mixed' || nForm === 'ureic') && (
                  <FormField label={t('applications.nUreicPct')}>
                    <Input type="number" value={nUreicPct} onChange={(e) => setNUreicPct(e.target.value)} />
                  </FormField>
                )}
                <FormField label={t('applications.registryRef')}>
                  <Input value={registryRef} onChange={(e) => setRegistryRef(e.target.value)} />
                </FormField>
              </FormGrid>
            )}

            {(needsAnnexA || needsAnnexB) && (
              <Surface variant="sunken" padding="inline">
                <Stack gap="tight">
                  <strong className="text-nkz-xs text-nkz-text-primary">{t('applications.annexVTitle')}</strong>
                  <Inline gap="inline" wrap>
                    {(needsAnnexA ? ANNEX_V_A : []).concat(needsAnnexB ? ANNEX_V_B : []).map((code) => (
                      <Checkbox
                        key={code}
                        label={code}
                        checked={annexV.includes(code)}
                        onChange={(checked) => toggleAnnex(code, checked)}
                      />
                    ))}
                  </Inline>
                  <FormField label={t('applications.otherMeasure')}>
                    <Input value={otherMeasure} onChange={(e) => setOtherMeasure(e.target.value)} />
                  </FormField>
                </Stack>
              </Surface>
            )}

            <Inline gap="inline">
              <Button variant="primary" loading={busy} disabled={!canSaveApp} onClick={handleAdd}>
                {t('applications.save')}
              </Button>
              <Button variant="ghost" onClick={() => setAdding(false)}>
                {t('applications.cancel')}
              </Button>
            </Inline>
          </Stack>
        </Surface>
      )}

      {/* Justified N adjustment (Anexo III-I.3 — technician only) */}
      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <Inline gap="inline" align="center" justify="between" wrap>
            <h4 className="font-semibold text-nkz-text-primary">{t('applications.nAdjTitle')}</h4>
            {roles.technician && editable && !adjOpen && (
              <Inline gap="tight">
                <Button size="sm" variant="secondary" onClick={() => setAdjOpen(true)}>
                  {existingAdj ? t('applications.nAdjEdit') : t('applications.nAdjAdd')}
                </Button>
                {existingAdj && (
                  <Button size="sm" variant="ghost" loading={adjBusy} onClick={handleClearAdj}>
                    {t('applications.remove')}
                  </Button>
                )}
              </Inline>
            )}
          </Inline>
          {existingAdj ? (
            <p className="text-nkz-xs text-nkz-text-secondary">
              <strong>{existingAdj.justified_n_kg_ha} {t('common.unit.kgHa')}</strong> · {existingAdj.basis} · {existingAdj.date}
              {existingAdj.reference ? ` · ${existingAdj.reference}` : ''} — {existingAdj.description}
            </p>
          ) : (
            <p className="text-nkz-xs text-nkz-text-muted">{t('applications.nAdjNone')}</p>
          )}
          {adjError != null && <ErrorBanner error={adjError} planState={plan.state} />}
          {adjOpen && roles.technician && editable && (
            <Stack gap="inline">
              <FormGrid columns={2}>
                <FormField label={t('applications.nAdjBasis')}>
                  <Select
                    value={adjBasis}
                    onValueChange={(v) => setAdjBasis(v as NAdjustmentBasis)}
                    options={[
                      { value: 'foliar_analysis', label: 'foliar_analysis' },
                      { value: 'other_technique', label: 'other_technique' },
                      { value: 'year_evolution', label: 'year_evolution' },
                    ]}
                  />
                </FormField>
                <FormField label={t('applications.nAdjDose')}>
                  <Input type="number" value={adjN} onChange={(e) => setAdjN(e.target.value)} />
                </FormField>
                <FormField label={t('applications.date')}>
                  <Input type="date" value={adjDate} onChange={(e) => setAdjDate(e.target.value)} />
                </FormField>
                <FormField label={t('applications.nAdjRef')}>
                  <Input value={adjRef} onChange={(e) => setAdjRef(e.target.value)} />
                </FormField>
              </FormGrid>
              <FormField label={t('applications.nAdjDesc')}>
                <Textarea value={adjDesc} onChange={(e) => setAdjDesc(e.target.value)} />
              </FormField>
              <Inline gap="inline">
                <Button variant="primary" loading={adjBusy} disabled={!canSaveAdj} onClick={handleSaveAdj}>
                  {t('applications.save')}
                </Button>
                <Button variant="ghost" onClick={() => setAdjOpen(false)}>
                  {t('applications.cancel')}
                </Button>
              </Inline>
            </Stack>
          )}
        </Stack>
      </Surface>
    </Stack>
  );
}
