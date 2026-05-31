import { describe, it, expect } from 'vitest';
import {
  INTEGRATION_TEMPLATES,
  applyTemplate,
  type IntegrationTemplate,
} from './integration-templates';

const discord = INTEGRATION_TEMPLATES.find((t) => t.key === 'discord')!;
const slack = INTEGRATION_TEMPLATES.find((t) => t.key === 'slack')!;
const n8n = INTEGRATION_TEMPLATES.find((t) => t.key === 'n8n')!;

describe('INTEGRATION_TEMPLATES', () => {
  it('exposes the three documented integrations in stable order', () => {
    expect(INTEGRATION_TEMPLATES.map((t) => t.key)).toEqual(['discord', 'slack', 'n8n']);
  });

  it('every template ships a placeholder URL that requires editing', () => {
    // The placeholders are *deliberately* fake so the operator catches
    // a submit-without-editing as a 422 from the backend.
    for (const t of INTEGRATION_TEMPLATES) {
      expect(t.url).toMatch(/^https:\/\//);
    }
    // Discord and Slack ship variable placeholders the operator must
    // replace — we pin those so a future rename doesn't silently break
    // the "Quick fill is a helper, not a finished URL" UX.
    expect(discord.url).toContain('{ID}');
    expect(discord.url).toContain('{TOKEN}');
    expect(slack.url).toContain('{TEAM_ID}');
    expect(slack.url).toContain('{TOKEN}');
  });

  it('Discord defaults to command + host events (the high-signal set)', () => {
    expect(discord.events).toEqual(['command.', 'host.']);
  });

  it('Slack adds approvals to the default set', () => {
    expect(slack.events).toEqual(['command.', 'host.', 'approval.']);
  });

  it('n8n defaults to the wildcard so workflows can filter downstream', () => {
    expect(n8n.events).toEqual(['*']);
  });
});

describe('applyTemplate', () => {
  const empty = { name: '', url: '', events: ['*'] };

  it('fills every field on an empty form', () => {
    const next = applyTemplate(discord, empty);
    expect(next.name).toBe(discord.name);
    expect(next.url).toBe(discord.url);
    expect(next.events).toEqual(discord.events);
  });

  it('keeps an operator-typed name when applying a template', () => {
    const next = applyTemplate(discord, {
      ...empty,
      name: 'My team Discord',
    });
    expect(next.name).toBe('My team Discord');
    // URL and events should still be filled because they were empty.
    expect(next.url).toBe(discord.url);
    expect(next.events).toEqual(discord.events);
  });

  it('keeps an operator-typed URL even when only whitespace was trimmed', () => {
    // Trailing space is treated as "still typed" — we only consider the
    // empty/whitespace-only string as "untouched".
    const next = applyTemplate(slack, {
      ...empty,
      url: 'https://hooks.slack.com/services/T123/B456/abc ',
    });
    expect(next.url).toBe('https://hooks.slack.com/services/T123/B456/abc ');
  });

  it('treats whitespace-only fields as empty (and overwrites them)', () => {
    const next = applyTemplate(slack, { ...empty, name: '   ', url: '\t' });
    expect(next.name).toBe(slack.name);
    expect(next.url).toBe(slack.url);
  });

  it('does not overwrite a non-default events selection', () => {
    // Operator already picked specific filters → template events must
    // not clobber them, even if the operator's list is otherwise
    // shorter or different.
    const next = applyTemplate(discord, {
      ...empty,
      events: ['audit.'],
    });
    expect(next.events).toEqual(['audit.']);
  });

  it('treats the empty form `[*]` as "untouched" and overwrites it', () => {
    // The empty form default is `['*']`. Anything else (including
    // an empty array) means the operator has touched the events.
    const next = applyTemplate(slack, { ...empty, events: ['*'] });
    expect(next.events).toEqual(slack.events);
  });

  it('does not mutate the input form state', () => {
    const before: { name: string; url: string; events: string[] } = {
      name: '',
      url: '',
      events: ['*'],
    };
    const snapshot = { ...before, events: [...before.events] };
    applyTemplate(n8n, before);
    expect(before).toEqual(snapshot);
  });

  it('returns a fresh events array (no aliasing with the template)', () => {
    const next = applyTemplate(discord, empty);
    next.events.push('mutated');
    expect(discord.events).toEqual(['command.', 'host.']);
  });
});

describe('applyTemplate type smoke', () => {
  it('accepts a custom-built template object', () => {
    // The signature is `(template, current) => next` — useful for
    // future user-defined templates if we ever wire them up.
    const custom: IntegrationTemplate = {
      key: 'n8n',
      label: 'Internal',
      url: 'https://example.test/hook',
      name: 'Internal hook',
      events: ['settings.'],
    };
    const next = applyTemplate(custom, { name: '', url: '', events: ['*'] });
    expect(next.url).toBe('https://example.test/hook');
    expect(next.events).toEqual(['settings.']);
  });
});
