import { sourceCrops } from '../api/fast';
import { useLoad } from './useLoad';

/** The crops the user can pick by name; `enabled` false when nothing on screen can edit a crop. */
export const useCrops = (enabled = true) => useLoad((s) => sourceCrops(s), [], enabled);
