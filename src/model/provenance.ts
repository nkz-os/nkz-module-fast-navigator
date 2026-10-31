import type { CycleView, Sourced } from '../api/types';

export type BadgeIntent = 'default' | 'positive' | 'warning' | 'negative' | 'info';
export type ChipSymbol = '●' | '▤' | '◐' | '⚑' | '≈' | '✕' | '○';

export interface Chip {
  symbol: ChipSymbol;
  key: string;
  intent: BadgeIntent;
  tooltip: { key: string; params: Record<string, string> };
}

const text = (v: unknown) => (typeof v === 'string' ? v : '');

/** The provenance chip of a value (design §3). `cycle` marks a crop that comes from a planned cycle. */
export function chipFor(s: Sourced | null | undefined, cycle?: CycleView | null): Chip {
  const p = s?.provenance ?? 'missing';
  const source = text(s?.source);
  if (p === 'missing' || s == null) {
    return { symbol: '✕', key: 'provenance.missing', intent: 'negative', tooltip: { key: 'provenance.tip.missing', params: { owner: source } } };
  }
  if (p === 'measured' && cycle?.start.provenance === 'planned') {
    return { symbol: '○', key: 'provenance.plannedBioorch', intent: 'default', tooltip: { key: 'provenance.tip.planned', params: {} } };
  }
  if (p === 'measured') {
    return { symbol: '●', key: 'provenance.measured', intent: 'positive', tooltip: { key: 'provenance.tip.measured', params: { source } } };
  }
  if (p.startsWith('table:')) {
    return { symbol: '▤', key: 'provenance.table', intent: 'default', tooltip: { key: 'provenance.tip.table', params: { id: p.slice(6) } } };
  }
  if (p === 'declared') {
    return { symbol: '◐', key: 'provenance.declared', intent: 'default', tooltip: { key: 'provenance.tip.declared', params: {} } };
  }
  if (p === 'entered') {
    return { symbol: '⚑', key: 'provenance.entered', intent: 'info', tooltip: { key: 'provenance.tip.entered', params: { note: text(s.note), source } } };
  }
  if (p === 'estimated') {
    return { symbol: '≈', key: 'provenance.estimated', intent: 'warning', tooltip: { key: 'provenance.tip.estimated', params: {} } };
  }
  return { symbol: '○', key: 'provenance.unknown', intent: 'default', tooltip: { key: 'provenance.tip.declared', params: { provenance: p } } };
}
