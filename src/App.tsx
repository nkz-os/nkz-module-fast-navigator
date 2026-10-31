/** Main page, lazily loaded by Module.tsx and rendered standalone by `pnpm dev`. */
import React from 'react';
import './i18n';
import { FastApp } from './components/FastApp';

const App: React.FC = () => <FastApp />;

export default App;
