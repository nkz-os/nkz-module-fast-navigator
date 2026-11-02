import { sourceOrganicProducts } from '../api/fast';
import { useLoad } from './useLoad';

/** The MAPA product suggestions; only fetched while the sheet can be edited. */
export const useOrganicProducts = (enabled = true) => useLoad((s) => sourceOrganicProducts(s), [], enabled);
