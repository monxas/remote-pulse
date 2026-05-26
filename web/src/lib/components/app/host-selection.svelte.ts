/**
 * Multi-select state container for the Fleet table.
 *
 * Thin compatibility wrapper around the generic `createSelection`
 * helper in `./selection.svelte.ts`. Kept as a separate module so the
 * existing Fleet + HostTable imports (and the v1.0.9 e2e suite that
 * targets `select-all-hosts` / `select-host-*`) keep working without
 * churn. New tables (Users, Groups, …) should depend on the generic
 * helper directly.
 */

import { createSelection, type ISelection, type SelectAllState } from './selection.svelte';

export type { SelectAllState };

// Re-export the pure helper from the generic module for back-compat
// with the existing `host-selection.test.ts` suite.
export { computeSelectAllState } from './selection.svelte';

export type IHostSelection = ISelection<string>;

export function createHostSelection(): IHostSelection {
  return createSelection<string>();
}
