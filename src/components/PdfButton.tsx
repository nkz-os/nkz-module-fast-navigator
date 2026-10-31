import React, { useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button } from '@nekazari/ui-kit';
import { fetchPlanPdf } from '../api/fast';
import { ErrorBanner } from './ErrorBanner';

/** Downloads the plan PDF. One request at a time: rendering it can take tens of seconds. */
export function PdfButton({ planId, lang, initialBusy = false }: { planId: string; lang: 'es' | 'en'; initialBusy?: boolean }) {
  const { t } = useTranslation('fast-navigator');
  const [busy, setBusy] = useState(initialBusy);
  const [error, setError] = useState<unknown>(null);
  const running = useRef(false);

  const download = async () => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      const { filename, blob } = await fetchPlanPdf(planId, lang);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e);
    } finally {
      running.current = false;
      setBusy(false);
    }
  };

  return (
    <span className="inline-flex flex-col gap-nkz-tight">
      <Button size="sm" variant="secondary" loading={busy} aria-busy={busy} onClick={download}>
        {t(busy ? 'pdf.busy' : 'pdf.button')}
      </Button>
      {error != null && <ErrorBanner error={error} onRetry={download} />}
    </span>
  );
}
