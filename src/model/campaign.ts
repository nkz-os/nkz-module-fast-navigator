/** The agricultural campaign in course: the year starts on 1 September (month index 8). */
export function currentCampaign(today: Date): number {
  return today.getMonth() >= 8 ? today.getFullYear() + 1 : today.getFullYear();
}
