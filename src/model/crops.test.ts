import { describe, expect, it } from 'vitest';
import { cropDisplayName, filterCrops, FALLOW, hasCoefficients, type SourceCrop } from './crops';

const CROPS: SourceCrop[] = [
  { eppo: 'HORVX', names: { es: 'Cebada', en: 'Barley', eu: 'Garagar' }, has_coefficients: true },
  { eppo: 'TRZAX', names: { es: 'Trigo blando', en: 'Common wheat' }, has_coefficients: true },
  { eppo: 'TRZDU', names: { es: 'Trigo duro', en: 'Durum wheat' }, has_coefficients: true },
  { eppo: 'VICFX', names: { es: 'Haba', en: 'Faba bean' }, has_coefficients: false },
];

describe('cropDisplayName', () => {
  it('uses the user language, then English, then Spanish, then the code', () => {
    expect(cropDisplayName(CROPS[0], 'eu')).toBe('Garagar');
    expect(cropDisplayName(CROPS[1], 'fr')).toBe('Common wheat');
    expect(cropDisplayName({ eppo: 'XXXXX', names: { es: 'Algo' }, has_coefficients: true }, 'fr')).toBe('Algo');
    expect(cropDisplayName({ eppo: 'XXXXX', names: {}, has_coefficients: true }, 'fr')).toBe('XXXXX');
  });
});

describe('filterCrops', () => {
  it('finds by name in any language, ignoring case and accents', () => {
    expect(filterCrops(CROPS, 'TRIGO', 'es').map((c) => c.eppo)).toEqual(['TRZAX', 'TRZDU']);
    expect(filterCrops(CROPS, 'barl', 'es').map((c) => c.eppo)).toEqual(['HORVX']);
    expect(filterCrops(CROPS, 'hába', 'es').map((c) => c.eppo)).toEqual(['VICFX']);
  });
  it('names that start with the text come first, and the empty text lists the first ones', () => {
    expect(filterCrops(CROPS, 'duro', 'es').map((c) => c.eppo)).toEqual(['TRZDU']);
    expect(filterCrops(CROPS, '', 'es', 2).map((c) => c.eppo)).toEqual(['HORVX', 'TRZAX']);
  });
  it('also matches the EPPO code', () => {
    expect(filterCrops(CROPS, 'trzax', 'es').map((c) => c.eppo)).toEqual(['TRZAX']);
  });
});

describe('hasCoefficients', () => {
  it('is false for a crop flagged without them and for a code that is not in the list', () => {
    expect(hasCoefficients(CROPS, 'TRZAX')).toBe(true);
    expect(hasCoefficients(CROPS, 'VICFX')).toBe(false);
    expect(hasCoefficients(CROPS, 'CIEAR')).toBe(false);
  });
  it('fallow needs none', () => { expect(hasCoefficients(CROPS, FALLOW)).toBe(true); });
});
