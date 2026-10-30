import React, { useMemo, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button, Checkbox, FormField, FormGrid, Inline, Input, Select, Stack, Surface } from '@nekazari/ui-kit';
import { calculatePlan, cropName, putSheets, storeRainNormal } from '../api/fast';
import type { CampaignParcel, CampaignParcels, Plan } from '../api/types';
import { useLoad } from '../hooks/useLoad';
import { errorView } from '../model/errors';
import { formatDate, formatHa } from '../model/format';
import {
  defaultManagement, EPPO_RE, groupParcels, wizardBlockers, wizardSheets,
  type GroupManagement, type ParcelGroup,
} from '../model/sheets';
import { ErrorBanner } from './ErrorBanner';
import { ProvenanceChip } from './ProvenanceChip';

type Step = 1 | 2 | 3;

export interface WizardInitial { step?: Step; rainError?: unknown; management?: Record<string, GroupManagement> }

/** Name of a crop from its EPPO code; the code itself when the name cannot be had. */
function CropLabel({ eppo }: { eppo: string }) {
  const { i18n } = useTranslation('fast-navigator');
  const name = useLoad((s) => cropName(eppo, i18n.language, s), [eppo, i18n.language], EPPO_RE.test(eppo));
  return <span>{name.data ?? eppo}</span>;
}

function ParcelRow({ parcel, campaign }: { parcel: CampaignParcel; campaign: number }) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;
  const cycle = parcel.cycle;
  const prov = cycle?.start.provenance ?? null;
  return (
    <Inline gap="inline" align="center" wrap>
      <span className="font-medium text-nkz-text-primary">{parcel.name ?? parcel.id}</span>
      <span className="text-nkz-sm text-nkz-text-secondary">{formatHa(parcel.area_ha.value as number | null, lang)} {t('common.unit.ha')}</span>
      {prov === 'planned' && (
        <a className="underline" href={`/bioorchestrator?parcel=${encodeURIComponent(parcel.id)}&campaign=${campaign}`}>
          <Badge intent="default">○ {t('provenance.plannedBioorch')}</Badge>
        </a>
      )}
      {prov === 'actual' && <Badge intent="positive">● {t('provenance.sown')} {formatDate(cycle?.start.date, lang)}</Badge>}
      {prov === 'declared' && <Badge intent="default">◐ {t('provenance.declared')}</Badge>}
      <span className="text-nkz-sm text-nkz-text-secondary">
        {t('wizard.previous')}{' '}
        {parcel.previous_crop.value != null ? String(parcel.previous_crop.value) : ''}{' '}
        <ProvenanceChip value={parcel.previous_crop} />
      </span>
    </Inline>
  );
}

function GroupCard({ group, campaign, m, onChange, children }: {
  group: ParcelGroup; campaign: number; m: GroupManagement; onChange: (m: GroupManagement) => void; children?: React.ReactNode;
}) {
  const { t, i18n } = useTranslation('fast-navigator');
  const regime = group.regime ? t(`wizard.regime.${group.regime}`) : t('wizard.regime.unknown');
  return (
    <Surface variant="raised" padding="stack">
      <Stack gap="inline">
        <Inline gap="inline" align="center" justify="between" wrap>
          <Checkbox checked={m.included} onChange={(included) => onChange({ ...m, included })} label={t('wizard.include')} />
          <span className="text-nkz-base font-semibold text-nkz-text-primary">
            {group.noCrop ? t('wizard.noCrop.title', { campaign, count: group.parcels.length }) : <><CropLabel eppo={group.crop as string} /> · {regime}</>}
          </span>
          <span className="text-nkz-sm text-nkz-text-secondary">
            {t('wizard.parcels', { count: group.parcels.length })} · {formatHa(group.areaHa, i18n.language)} {t('common.unit.ha')}
          </span>
        </Inline>
        {group.parcels.map((p) => <ParcelRow key={p.id} parcel={p} campaign={campaign} />)}
        {children}
      </Stack>
    </Surface>
  );
}

function RainBars({ plan }: { plan: Plan }) {
  const { t, i18n } = useTranslation('fast-navigator');
  const rain = plan.rain_normal;
  if (!rain || rain.monthly_mm.length !== 12) return null;
  const max = Math.max(...rain.monthly_mm, 1);
  const month = (i: number) => new Intl.DateTimeFormat(i18n.language, { month: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(2001, i, 1)));
  return (
    <Stack gap="tight">
      <p className="text-nkz-sm text-nkz-text-secondary">
        {t('wizard.rain.years', { count: rain.years.length })} · {t('wizard.rain.annual', { mm: Math.round(rain.annual_mm ?? 0) })}
      </p>
      {rain.monthly_mm.map((mm, i) => (
        <div key={i} className="flex items-center gap-nkz-inline" aria-label={t('wizard.rain.month', { month: month(i), mm: Math.round(mm) })}>
          <span className="w-12 text-nkz-xs text-nkz-text-muted">{month(i)}</span>
          <div className="h-3 flex-1 rounded-nkz-sm bg-nkz-surface-sunken">
            <div className="h-3 rounded-nkz-sm bg-nkz-info" style={{ width: `${(mm / max) * 100}%` }} />
          </div>
          <span className="w-16 text-right text-nkz-xs text-nkz-text-secondary">{Math.round(mm)} mm</span>
        </div>
      ))}
    </Stack>
  );
}

/** Three steps: which parcels, how they are managed, the normal rainfall. Saves and calculates at the end. */
export function Wizard({ plan, parcels, onSaved, initial }: {
  plan: Plan; parcels: CampaignParcels; onSaved: (plan: Plan) => void; initial?: WizardInitial;
}) {
  const { t } = useTranslation('fast-navigator');
  const campaign = plan.campaign;
  const used = useMemo(() => new Set(plan.sheets.flatMap((s) => s.parcels.map((p) => p.urn))), [plan.sheets]);
  const groups = useMemo(() => groupParcels(parcels.parcels.filter((p) => !used.has(p.id))), [parcels.parcels, used]);

  const [step, setStep] = useState<Step>(initial?.step ?? 1);
  const [management, setManagement] = useState<Record<string, GroupManagement>>(() => {
    const base: Record<string, GroupManagement> = {};
    for (const g of groups) base[g.id] = defaultManagement(g);
    return { ...base, ...(initial?.management ?? {}) };
  });
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState<string | null>(null);
  const [latest, setLatest] = useState<Plan>(plan);
  const [dirty, setDirty] = useState(true);
  const [busy, setBusy] = useState<'save' | 'rain' | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [rainError, setRainError] = useState<unknown>(initial?.rainError ?? null);

  const kept = plan.sheets.filter((s) => !removed.has(s.key));
  const blockers = wizardBlockers(groups, management);
  const sheets = wizardSheets(groups, management, kept, campaign);
  const nothing = sheets.length === 0;
  const canSave = blockers.length === 0 && !nothing && busy === null;

  const update = (id: string, m: GroupManagement) => {
    setManagement((cur) => ({ ...cur, [id]: m }));
    setDirty(true);
  };

  /** Saves the sheets unless they are already saved as they are; keeps the newest plan (row_version). */
  const ensureSaved = async (): Promise<Plan> => {
    if (!dirty) return latest;
    const saved = await putSheets(latest.id, latest.row_version, sheets);
    setLatest(saved);
    setDirty(false);
    return saved;
  };

  const getRain = async () => {
    setBusy('rain'); setRainError(null); setError(null);
    try {
      const saved = await ensureSaved();
      setLatest(await storeRainNormal(saved.id));
    } catch (e) {
      setRainError(e);
    } finally { setBusy(null); }
  };

  const saveAndCalculate = async () => {
    setBusy('save'); setError(null);
    try {
      const saved = await ensureSaved();
      onSaved(await calculatePlan(saved.id, saved.row_version));
    } catch (e) {
      setError(e);
    } finally { setBusy(null); }
  };

  // 422 per sheet: show it beside the group that produced that sheet.
  const groupErrors = useMemo(() => {
    const out: Record<string, string[]> = {};
    const fields = error != null ? errorView(error).fieldErrors ?? {} : {};
    const order = sheets.slice(kept.length);
    for (const [path, msg] of Object.entries(fields)) {
      const m = /^sheets\.(\d+)\.(.+)$/.exec(path);
      if (!m) continue;
      const idx = Number(m[1]) - kept.length;
      const target = groups.filter((g) => management[g.id]?.included)[idx];
      if (target && order[idx]) (out[target.id] ??= []).push(`${m[2]}: ${msg}`);
    }
    return out;
  }, [error, sheets, kept.length, groups, management]);

  const saveButton = (
    <Button variant="primary" disabled={!canSave} loading={busy === 'save'} onClick={saveAndCalculate}>
      {t('wizard.saveCalc')}
    </Button>
  );

  return (
    <Stack gap="stack">
      <h2 className="text-nkz-lg font-semibold text-nkz-text-primary">{t(`wizard.step${step}`, { campaign })}</h2>

      {step === 1 && (
        <Stack gap="stack">
          {plan.sheets.length > 0 && (
            <Surface variant="sunken" padding="stack">
              <Stack gap="inline">
                <p className="text-nkz-sm font-medium text-nkz-text-primary">{t('wizard.existing.title')}</p>
                {plan.sheets.map((s) => (
                  <Inline key={s.key} gap="inline" align="center" wrap>
                    <span className={removed.has(s.key) ? 'line-through' : ''}>{s.key}</span>
                    <span className="text-nkz-xs text-nkz-text-muted">{t('wizard.parcels', { count: s.parcels.length })}</span>
                    {removed.has(s.key) ? (
                      <Button size="sm" variant="ghost" onClick={() => { setRemoved((r) => { const n = new Set(r); n.delete(s.key); return n; }); setDirty(true); }}>
                        {t('wizard.existing.keep')}
                      </Button>
                    ) : confirming === s.key ? (
                      <Inline gap="inline" align="center" wrap>
                        <span role="alert" className="text-nkz-sm text-nkz-warning">{t('wizard.existing.confirm')}</span>
                        <Button size="sm" variant="danger" onClick={() => { setRemoved((r) => new Set(r).add(s.key)); setConfirming(null); setDirty(true); }}>
                          {t('wizard.existing.yes')}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>{t('wizard.existing.cancel')}</Button>
                      </Inline>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => {
                        if (s.overrides.length > 0) setConfirming(s.key);
                        else { setRemoved((r) => new Set(r).add(s.key)); setDirty(true); }
                      }}>{t('wizard.existing.remove')}</Button>
                    )}
                  </Inline>
                ))}
              </Stack>
            </Surface>
          )}
          {groups.length === 0 && <p className="text-nkz-sm text-nkz-text-secondary">{t('wizard.noParcels')}</p>}
          {groups.map((g) => (
            <GroupCard key={g.id} group={g} campaign={campaign} m={management[g.id] ?? defaultManagement(g)} onChange={(m) => update(g.id, m)}>
              {g.noCrop && (
                <Stack gap="tight">
                  <p className="text-nkz-sm text-nkz-text-secondary">{t('wizard.noCrop.hint')}</p>
                  <FormField label={t('wizard.declare.label')} description={t('wizard.declare.hint')}
                    error={management[g.id]?.declaredCrop && !EPPO_RE.test(management[g.id].declaredCrop as string) ? t('wizard.declare.invalid') : undefined}>
                    <Inline gap="inline" align="center">
                      <Input value={management[g.id]?.declaredCrop ?? ''} placeholder={t('wizard.declare.placeholder')}
                        onChange={(e) => update(g.id, { ...(management[g.id] ?? defaultManagement(g)), declaredCrop: e.target.value.toUpperCase().trim() })} />
                      {EPPO_RE.test(management[g.id]?.declaredCrop ?? '') && <CropLabel eppo={management[g.id].declaredCrop as string} />}
                    </Inline>
                  </FormField>
                </Stack>
              )}
            </GroupCard>
          ))}
        </Stack>
      )}

      {step === 2 && (
        <Stack gap="stack">
          {groups.filter((g) => management[g.id]?.included).map((g) => {
            const m = management[g.id];
            const regimeOptions = [{ value: 'rainfed', label: t('wizard.regime.rainfed') }, { value: 'irrigated', label: t('wizard.regime.irrigated') }];
            const yesNo = [{ value: 'yes', label: t('wizard.form.tillageYes') }, { value: 'no', label: t('wizard.form.tillageNo') }];
            const strategies = ([1, 2, 3, 4] as const).map((n) => ({ value: String(n), label: t(`wizard.strategy.${n}`) }));
            return (
              <Surface key={g.id} variant="raised" padding="stack">
                <Stack gap="inline">
                  <p className="text-nkz-base font-semibold text-nkz-text-primary">
                    {g.noCrop ? <CropLabel eppo={m.declaredCrop ?? ''} /> : <CropLabel eppo={g.crop as string} />} · {t('wizard.parcels', { count: g.parcels.length })}
                  </p>
                  <FormGrid columns={2}>
                    <FormField label={t('wizard.form.regime')} required>
                      <Select value={m.irrigated === null ? '' : m.irrigated ? 'irrigated' : 'rainfed'} options={regimeOptions}
                        placeholder={t('wizard.form.choose')} onValueChange={(v) => update(g.id, { ...m, irrigated: v === 'irrigated' })} />
                    </FormField>
                    <FormField label={t('wizard.form.tillage')} required>
                      <Select value={m.tillage === null ? '' : m.tillage ? 'yes' : 'no'} options={yesNo}
                        placeholder={t('wizard.form.choose')} onValueChange={(v) => update(g.id, { ...m, tillage: v === 'yes' })} />
                    </FormField>
                    <FormField label={t('wizard.form.rotation')} required>
                      <Input type="number" min={1} max={20} step={1} value={m.rotationYears ?? ''}
                        onChange={(e) => update(g.id, { ...m, rotationYears: e.target.value === '' ? null : Number(e.target.value) })} />
                    </FormField>
                    <FormField label={t('wizard.form.strategy')}>
                      <Select value={String(m.strategy)} options={strategies}
                        onValueChange={(v) => update(g.id, { ...m, strategy: Number(v) as 1 | 2 | 3 | 4 })} />
                    </FormField>
                  </FormGrid>
                  <Checkbox checked={m.residuesBurned} onChange={(residuesBurned) => update(g.id, { ...m, residuesBurned })} label={t('wizard.form.residues')} />
                  {(groupErrors[g.id] ?? []).map((msg) => <p key={msg} role="alert" className="text-nkz-sm text-nkz-danger">{msg}</p>)}
                </Stack>
              </Surface>
            );
          })}
        </Stack>
      )}

      {step === 3 && (
        <Surface variant="raised" padding="stack">
          <Stack gap="inline">
            <p className="text-nkz-sm text-nkz-text-secondary">{t('wizard.rain.hint')}</p>
            <div>
              <Button variant="secondary" loading={busy === 'rain'} disabled={!canSave && busy === null} onClick={getRain}>
                {t(busy === 'rain' ? 'wizard.rain.getting' : 'wizard.rain.get')}
              </Button>
            </div>
            {rainError != null && <ErrorBanner error={rainError} onRetry={getRain} />}
            <RainBars plan={latest} />
          </Stack>
        </Surface>
      )}

      {blockers.length > 0 && step !== 1 && (
        <ul className="list-disc pl-nkz-section text-nkz-sm text-nkz-warning">
          {blockers.map((k) => <li key={k}>{t(k)}</li>)}
        </ul>
      )}
      {step !== 1 && nothing && <p className="text-nkz-sm text-nkz-warning">{t('wizard.blocker.nothing')}</p>}
      {error != null && <ErrorBanner error={error} onRetry={saveAndCalculate} planState={latest.state} />}

      <Inline gap="inline" align="center" justify="between" wrap>
        <div>{step > 1 && <Button variant="ghost" onClick={() => setStep((s) => (s - 1) as Step)}>{t('wizard.back')}</Button>}</div>
        <Inline gap="inline" align="center">
          {step < 3 && <Button variant="secondary" onClick={() => setStep((s) => (s + 1) as Step)}>{t('wizard.next')}</Button>}
          {step > 1 && saveButton}
        </Inline>
      </Inline>
    </Stack>
  );
}
