/**
 * Webhook integration templates (v1.0.15).
 *
 * Quick-fill data + pure apply logic for the "New webhook" modal on
 * /webhooks. Each template carries a placeholder URL matching the
 * upstream's URL grammar plus a sensible default event-filter selection
 * for that platform. Click the chip → the modal fills the *empty*
 * fields only (never clobbers in-progress operator typing).
 *
 * Extracted from `+page.svelte` so the apply contract is unit-testable
 * without a Svelte component harness.
 */

export type IntegrationKey = 'discord' | 'slack' | 'n8n';

export interface IntegrationTemplate {
  key: IntegrationKey;
  label: string;
  /** Placeholder URL — must be edited by the operator before submit. */
  url: string;
  /** Suggested human-readable name; only applied if name is empty. */
  name: string;
  /** Default event-filter selection — overrides the empty form's
   * `['*']` only when the operator hasn't already picked anything. */
  events: string[];
}

export const INTEGRATION_TEMPLATES: ReadonlyArray<IntegrationTemplate> = [
  {
    key: 'discord',
    label: 'Discord',
    url: 'https://discord.com/api/webhooks/{ID}/{TOKEN}',
    name: 'Discord — alerts',
    events: ['command.', 'host.'],
  },
  {
    key: 'slack',
    label: 'Slack',
    // Placeholder must obviously be a placeholder — GitHub's secret
    // scanner flags the {Txxx}/{Bxxx}/{token} pattern even when every
    // segment is literal zeros/X's. We use curly-brace placeholders
    // matching the convention from the Slack docs themselves so the
    // operator knows exactly what to replace.
    url: 'https://hooks.slack.com/services/{TEAM_ID}/{BOT_ID}/{TOKEN}',
    name: 'Slack — alerts',
    events: ['command.', 'host.', 'approval.'],
  },
  {
    key: 'n8n',
    label: 'n8n',
    url: 'https://n8n.example.com/webhook/remote-pulse',
    name: 'n8n bridge',
    events: ['*'],
  },
];

export interface WebhookFormFields {
  name: string;
  url: string;
  events: string[];
}

/**
 * Compute the *patched* form state after applying ``template`` to
 * ``current``. Non-destructive: any field the operator has already
 * customised survives.
 *
 * Field rules:
 *   - ``url``: only overwritten when ``current.url`` is blank (trimmed).
 *   - ``name``: same — only overwritten when blank.
 *   - ``events``: overwritten only when the current array is the empty-
 *     form default ``['*']``. Anything else (including ``[]``) is
 *     considered "operator has touched events" and left alone.
 *
 * Returns a fresh object — never mutates ``current``.
 */
export function applyTemplate(
  template: IntegrationTemplate,
  current: Readonly<WebhookFormFields>,
): WebhookFormFields {
  const url = current.url.trim() ? current.url : template.url;
  const name = current.name.trim() ? current.name : template.name;
  const isDefaultEvents = current.events.length === 1 && current.events[0] === '*';
  const events = isDefaultEvents ? [...template.events] : current.events;
  return { url, name, events };
}
