/** The agricultural campaign in course: the year starts on 1 September (month index 8). */
export function currentCampaign(today: Date): number {
  return today.getMonth() >= 8 ? today.getFullYear() + 1 : today.getFullYear();
}

/** The campaign shown: the one in the URL, else the one in course. */
export function resolveCampaign(fromUrl: number | null, today: Date): number {
  return fromUrl ?? currentCampaign(today);
}

/** Campaigns offered by the selector: three before the current one and the next. */
export function campaignChoices(center: number, today: Date): number[] {
  const now = currentCampaign(today);
  const set = new Set<number>([center]);
  for (let c = now - 3; c <= now + 1; c += 1) set.add(c);
  return [...set].sort((a, b) => b - a);
}
