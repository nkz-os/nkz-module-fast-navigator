/** Main page, lazily loaded by moduleEntry.ts and rendered standalone by `pnpm dev`. */
import React from 'react';
import './i18n';
import { EmptyState } from '@nekazari/ui-kit';

const App: React.FC = () => <EmptyState title="FaST" />;

export default App;
