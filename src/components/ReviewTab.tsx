import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button, Checkbox, FormField, FormGrid, Inline, Input, Select, Stack, Surface, Textarea } from '@nekazari/ui-kit';
import {
  closePlan, getMyAdvisor, planAudit, putDeclarations, putMyAdvisor, returnPlan,
  revisePlan, signPlan, submitPlan,
} from '../api/fast';
import type { Plan } from '../api/types';
import { useLoad } from '../hooks/useLoad';
import { formatDate } from '../model/format';
import type { Roles } from '../model/roles';
import { ErrorBanner } from './ErrorBanner';

interface Props {
  plan: Plan;
  editable: boolean;
  roles: Roles;
  onSaved: (plan: Plan) => void;
}

export function ReviewTab({ plan, editable, roles, onSaved }: Props) {
  const { t, i18n } = useTranslation('fast-navigator');
  const lang = i18n.language;

  // Declarations state
  const [zvn, setZvn] = useState<'yes' | 'no' | 'unset'>(
    plan.declarations.vulnerable_zone === true ? 'yes'
      : plan.declarations.vulnerable_zone === false ? 'no' : 'unset',
  );
  const [zvnSource, setZvnSource] = useState(plan.declarations.vulnerable_zone_source ?? '');
  const [digitalNotebook, setDigitalNotebook] = useState(Boolean(plan.declarations.voluntary_digital_notebook));
  const [irrigSpring, setIrrigSpring] = useState<'yes' | 'no' | 'unset'>(
    plan.declarations.irrigated_spring_2026 === true ? 'yes'
      : plan.declarations.irrigated_spring_2026 === false ? 'no' : 'unset',
  );

  // Advisor profile (technician) — null means "not edited yet, show loaded value"
  const advisorLoad = useLoad((s) => getMyAdvisor(s), [roles.technician ? 'adv' : 'none'], roles.technician);
  const [advName, setAdvName] = useState<string | null>(null);
  const [advReg, setAdvReg] = useState<string | null>(null);
  const [advSaved, setAdvSaved] = useState(false);

  const effectiveAdvName = advName ?? advisorLoad.data?.name ?? '';
  const effectiveAdvReg = advReg ?? advisorLoad.data?.registration_number ?? '';

  // Workflow action state
  const [returnComment, setReturnComment] = useState('');
  const [closeBasis, setCloseBasis] = useState<'titular_cualificado' | 'titular_sin_obligacion'>('titular_sin_obligacion');
  const [closeSigner, setCloseSigner] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Audit trail
  const auditLoad = useLoad((s) => planAudit(plan.id, s), [plan.id, plan.row_version]);

  const runAction = async (fn: () => Promise<Plan>) => {
    setBusy(true);
    setError(null);
    try {
      onSaved(await fn());
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const handleSaveDeclarations = () => runAction(() => putDeclarations(plan.id, plan.row_version, {
    vulnerable_zone: zvn === 'yes' ? true : zvn === 'no' ? false : null,
    vulnerable_zone_source: zvnSource.trim() || null,
    voluntary_digital_notebook: digitalNotebook,
    irrigated_spring_2026: irrigSpring === 'yes' ? true : irrigSpring === 'no' ? false : null,
  }));

  const handleSaveAdvisor = async () => {
    setBusy(true);
    setError(null);
    setAdvSaved(false);
    try {
      await putMyAdvisor({
        name: effectiveAdvName.trim(),
        registration_number: effectiveAdvReg.trim(),
      });
      setAdvSaved(true);
      setAdvName(null);
      setAdvReg(null);
      advisorLoad.retry();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const canSaveDeclarations = zvn !== 'no' || Boolean(zvnSource.trim());
  const canSaveAdvisor = Boolean(effectiveAdvName.trim() && effectiveAdvReg.trim());
  const hasLifecycleActions =
    (plan.state === 'calculated' && (roles.canWrite || roles.canClose))
    || (plan.state === 'in_review' && roles.technician)
    || (plan.state === 'signed' && roles.canWrite);

  const blockingCount = plan.findings.filter((f) => f.severity === 'block').length;

  return (
    <Stack gap="stack">
      {error != null && <ErrorBanner error={error} planState={plan.state} />}

      {/* 1. Findings list */}
      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 className="font-semibold text-nkz-text-primary">{t('review.findingsTitle')}</h3>
          {plan.findings.length === 0 ? (
            <p className="text-nkz-sm text-nkz-text-secondary">{t('review.noFindings')}</p>
          ) : (
            plan.findings.map((f, idx) => (
              <Inline key={`${f.rule_id}-${idx}`} gap="inline" align="center" wrap>
                <Badge intent={f.severity === 'block' ? 'negative' : f.severity === 'warn' ? 'warning' : 'info'}>
                  {f.severity}
                </Badge>
                <strong className="text-nkz-xs text-nkz-text-primary">{f.rule_id}</strong>
                {f.sheet_key && <Badge intent="default">{f.sheet_key}</Badge>}
                {f.params?.citation && <span className="text-nkz-xs text-nkz-text-muted">{String(f.params.citation)}</span>}
              </Inline>
            ))
          )}
        </Stack>
      </Surface>

      {/* 2. Plan declarations (ZVN, voluntary digital notebook, irrigated spring 2026) */}
      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 className="font-semibold text-nkz-text-primary">{t('review.declarationsTitle')}</h3>
          <FormGrid columns={2}>
            <FormField label={t('review.zvn')}>
              <Select
                value={zvn}
                disabled={!editable}
                onValueChange={(v) => setZvn(v as 'yes' | 'no' | 'unset')}
                options={[
                  { value: 'unset', label: t('review.unset') },
                  { value: 'yes', label: t('review.yes') },
                  { value: 'no', label: t('review.no') },
                ]}
              />
            </FormField>
            <FormField label={t('review.zvnSource')}>
              <Input value={zvnSource} disabled={!editable} onChange={(e) => setZvnSource(e.target.value)} />
            </FormField>
            <FormField label={t('review.irrigSpring')}>
              <Select
                value={irrigSpring}
                disabled={!editable}
                onValueChange={(v) => setIrrigSpring(v as 'yes' | 'no' | 'unset')}
                options={[
                  { value: 'unset', label: t('review.unset') },
                  { value: 'yes', label: t('review.yes') },
                  { value: 'no', label: t('review.no') },
                ]}
              />
            </FormField>
          </FormGrid>
          <Checkbox
            label={t('review.digitalNotebook')}
            checked={digitalNotebook}
            disabled={!editable}
            onChange={setDigitalNotebook}
          />
          {editable && (
            <div>
              <Button size="sm" variant="secondary" loading={busy} disabled={!canSaveDeclarations} onClick={handleSaveDeclarations}>
                {t('review.saveDeclarations')}
              </Button>
            </div>
          )}
        </Stack>
      </Surface>

      {/* 3. Advisor profile (art. 21 — technician only) */}
      {roles.technician && (
        <Surface variant="raised" padding="stack">
          <Stack gap="inline">
            <h3 className="font-semibold text-nkz-text-primary">{t('review.advisorTitle')}</h3>
            <FormGrid columns={2}>
              <FormField label={t('review.advisorName')}>
                <Input
                  value={effectiveAdvName}
                  onChange={(e) => setAdvName(e.target.value)}
                />
              </FormField>
              <FormField label={t('review.advisorReg')}>
                <Input
                  value={effectiveAdvReg}
                  onChange={(e) => setAdvReg(e.target.value)}
                />
              </FormField>
            </FormGrid>
            <Inline gap="inline" align="center">
              <Button size="sm" variant="secondary" loading={busy} disabled={!canSaveAdvisor} onClick={handleSaveAdvisor}>
                {t('review.saveAdvisor')}
              </Button>
              {advSaved && <Badge intent="positive">{t('review.saved')}</Badge>}
            </Inline>
          </Stack>
        </Surface>
      )}

      {/* 4. Lifecycle transitions: Submit / Return / Sign / Close / Revise */}
      {hasLifecycleActions && (
      <Surface variant="raised" padding="stack">
        <Stack gap="inline">
          <h3 className="font-semibold text-nkz-text-primary">{t('review.actionsTitle')}</h3>
          <Inline gap="inline" wrap>
            {plan.state === 'calculated' && roles.canWrite && (
              <Button
                variant="primary"
                loading={busy}
                disabled={!plan.calc_fresh}
                onClick={() => runAction(() => submitPlan(plan.id, plan.row_version))}
              >
                {t('review.submit')}
              </Button>
            )}
            {plan.state === 'in_review' && roles.technician && (
              <Button
                variant="primary"
                loading={busy}
                disabled={!plan.calc_fresh || blockingCount > 0}
                onClick={() => runAction(() => signPlan(plan.id, plan.row_version))}
              >
                {t('review.sign')}
              </Button>
            )}
            {plan.state === 'signed' && roles.canWrite && (
              <Button
                variant="secondary"
                loading={busy}
                onClick={() => runAction(() => revisePlan(plan.id, plan.row_version))}
              >
                {t('review.revise')}
              </Button>
            )}
          </Inline>

          {plan.state === 'in_review' && roles.technician && (
            <Stack gap="tight">
              <FormField label={t('review.returnComment')}>
                <Textarea value={returnComment} onChange={(e) => setReturnComment(e.target.value)} />
              </FormField>
              <div>
                <Button
                  size="sm"
                  variant="danger"
                  loading={busy}
                  disabled={!returnComment.trim()}
                  onClick={async () => {
                    await runAction(() => returnPlan(plan.id, plan.row_version, returnComment.trim()));
                    setReturnComment('');
                  }}
                >
                  {t('review.return')}
                </Button>
              </div>
            </Stack>
          )}

          {plan.state === 'calculated' && roles.canClose && (
            <Surface variant="sunken" padding="inline">
              <Stack gap="tight">
                <strong className="text-nkz-xs text-nkz-text-primary">{t('review.closeTitle')}</strong>
                <FormGrid columns={2}>
                  <FormField label={t('review.closeBasis')}>
                    <Select
                      value={closeBasis}
                      onValueChange={(v) => setCloseBasis(v as 'titular_cualificado' | 'titular_sin_obligacion')}
                      options={[
                        { value: 'titular_sin_obligacion', label: t('review.basisExempt') },
                        { value: 'titular_cualificado', label: t('review.basisQualified') },
                      ]}
                    />
                  </FormField>
                  <FormField label={t('review.signerName')}>
                    <Input value={closeSigner} onChange={(e) => setCloseSigner(e.target.value)} />
                  </FormField>
                </FormGrid>
                <div>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={busy}
                    disabled={!plan.calc_fresh || blockingCount > 0 || !closeSigner.trim()}
                    onClick={() => runAction(() => closePlan(plan.id, plan.row_version, closeBasis, closeSigner.trim()))}
                  >
                    {t('review.close')}
                  </Button>
                </div>
              </Stack>
            </Surface>
          )}
        </Stack>
      </Surface>
      )}

      {/* 5. Audit history */}
      <Surface variant="raised" padding="stack">
        <Stack gap="tight">
          <h3 className="font-semibold text-nkz-text-primary">{t('review.auditTitle')}</h3>
          {(auditLoad.data ?? []).length === 0 ? (
            <p className="text-nkz-xs text-nkz-text-muted">{t('review.noAudit')}</p>
          ) : (
            (auditLoad.data ?? []).map((entry, idx) => (
              <Inline key={entry.id ?? idx} gap="inline" align="center" wrap>
                <Badge intent="default">{entry.action}</Badge>
                <span className="text-nkz-xs text-nkz-text-secondary">{formatDate(entry.at, lang)}</span>
              </Inline>
            ))
          )}
        </Stack>
      </Surface>
    </Stack>
  );
}
