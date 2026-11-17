// Regions and scenarios offered by the scenario control. Ids match the demo dataset (product.md).
export interface RegionOption {
  id: string;
  scenarios: string[];
}
export const REGIONS: RegionOption[] = [{ id: 'pk-sindh', scenarios: ['demo-sindh-2022'] }];
export const DEFAULT_REGION = 'pk-sindh';
export const DEFAULT_SCENARIO = 'demo-sindh-2022';
