import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import Button from './button.svelte';

/**
 * Regression coverage for v1.0.5 follow-up: the `<button>` branch must
 * forward arbitrary rest props (data-testid, name, value, formaction,
 * autofocus, ...) just like the `<a>` branch does. Before the fix only
 * `aria-label`/`title`/`type`/`onclick`/`disabled` were forwarded.
 */
describe('Button — rest-props forwarding', () => {
  afterEach(() => cleanup());

  it('button branch forwards data-testid, name, value, disabled, aria-label, title', () => {
    const { container } = render(Button, {
      props: {
        'data-testid': 'x',
        name: 'foo',
        value: 'bar',
        disabled: true,
        'aria-label': 'pick me',
        title: 'tooltip',
      } as Record<string, unknown>,
    });

    const btn = container.querySelector('button');
    expect(btn).not.toBeNull();
    expect(btn?.getAttribute('data-testid')).toBe('x');
    expect(btn?.getAttribute('name')).toBe('foo');
    expect(btn?.getAttribute('value')).toBe('bar');
    expect(btn?.hasAttribute('disabled')).toBe(true);
    expect(btn?.getAttribute('aria-label')).toBe('pick me');
    expect(btn?.getAttribute('title')).toBe('tooltip');
    // Default type is 'button'.
    expect(btn?.getAttribute('type')).toBe('button');
  });

  it('button branch keeps explicit type override when caller supplies one', () => {
    const { container } = render(Button, {
      props: {
        type: 'submit',
        'data-testid': 'submit-btn',
      } as Record<string, unknown>,
    });
    const btn = container.querySelector('button');
    expect(btn?.getAttribute('type')).toBe('submit');
    expect(btn?.getAttribute('data-testid')).toBe('submit-btn');
  });

  it('anchor branch forwards data-testid + href + rel/target', () => {
    const { container } = render(Button, {
      props: {
        href: '/path',
        'data-testid': 'y',
        rel: 'noopener',
        target: '_blank',
        'aria-label': 'go',
      } as Record<string, unknown>,
    });
    const a = container.querySelector('a');
    expect(a).not.toBeNull();
    expect(container.querySelector('button')).toBeNull();
    expect(a?.getAttribute('href')).toBe('/path');
    expect(a?.getAttribute('data-testid')).toBe('y');
    expect(a?.getAttribute('rel')).toBe('noopener');
    expect(a?.getAttribute('target')).toBe('_blank');
    expect(a?.getAttribute('aria-label')).toBe('go');
  });
});
