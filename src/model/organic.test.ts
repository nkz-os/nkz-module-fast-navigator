/// <reference types="vite/client" />
import { describe, expect, it } from 'vitest';
import backendSrc from '../../backend/app/inputs/organic.py?raw';
import { isOrganicMaterial, ORGANIC_MATERIALS } from './organic';

describe('organic materials', () => {
  it('are exactly the five the backend validates', () => {
    const line = /\nMATERIALS\s*=\s*\(([^)]*)\)/.exec(backendSrc);
    const backend = [...(line?.[1] ?? '').matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort();
    expect([...ORGANIC_MATERIALS].sort()).toEqual(backend);
  });
  it('recognises only those', () => {
    expect(isOrganicMaterial('slurry')).toBe(true);
    expect(isOrganicMaterial('estiércol')).toBe(false);
    expect(isOrganicMaterial('')).toBe(false);
  });
});
