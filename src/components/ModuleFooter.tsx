import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button, Spinner, Stack } from '@nekazari/ui-kit';
import { fetchAttributions } from '../api/fast';
import { useLoad } from '../hooks/useLoad';
import { ErrorBanner } from './ErrorBanner';

const REPO = 'https://github.com/nkz-os/nkz-module-fast-navigator';

/** Attribution the platform and the data licences require, on every landing screen. */
export function ModuleFooter() {
  const { t } = useTranslation('fast-navigator');
  const [open, setOpen] = useState(false);
  const data = useLoad((s) => fetchAttributions(s), [], open);
  return (
    <footer className="pt-nkz-stack mt-nkz-stack border-t border-nkz-border">
      <Stack gap="tight">
        <p className="text-nkz-xs text-nkz-text-muted">
          {t('footer.attribution')}{' · '}
          <a href={REPO} target="_blank" rel="noopener noreferrer" className="underline">{t('footer.source')}</a>
        </p>
        <p className="text-nkz-xs text-nkz-text-muted">{t('footer.credit')}</p>
        <div>
          <Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {t(open ? 'footer.sourcesClose' : 'footer.sourcesOpen')}
          </Button>
        </div>
        {open && data.loading && <Spinner size="sm" />}
        {open && !data.loading && data.error != null && <ErrorBanner error={data.error} onRetry={data.retry} />}
        {open && data.data && (
          <Stack gap="tight">
            {data.data.attributions.map((a) => (
              <p key={a.source_id} className="text-nkz-xs text-nkz-text-muted">
                {a.text}
                {a.url && <>{' '}<a href={a.url} target="_blank" rel="noopener noreferrer" className="underline">{t('footer.link')}</a></>}
                {a.licence_url && <>{' '}<a href={a.licence_url} target="_blank" rel="noopener noreferrer" className="underline">{t('footer.licence')}</a></>}
              </p>
            ))}
            <p className="text-nkz-xs text-nkz-text-muted">{t('footer.sourcesNote')}</p>
          </Stack>
        )}
      </Stack>
    </footer>
  );
}
