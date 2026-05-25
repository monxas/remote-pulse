import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';
import svelteConfig from './svelte.config.js';

/** @type {import('eslint').Linter.Config[]} */
export default [
  js.configs.recommended,
  ...ts.configs.recommended,
  ...svelte.configs['flat/recommended'],
  prettier,
  ...svelte.configs['flat/prettier'],
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
  },
  {
    files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
    languageOptions: {
      parserOptions: {
        parser: ts.parser,
        svelteConfig,
      },
    },
  },
  {
    // UserMenu links to `/auth/logout`, served by FastAPI rather than the
    // SvelteKit router. The svelte/no-navigation-without-resolve rule can't
    // tell that apart from a stale internal route, so we silence it here.
    // Every offending link in this file is paired with `data-sveltekit-reload`
    // so the browser does a full-page navigation, which is the correct
    // behaviour for the cross-app logout.
    files: ['src/lib/components/app/UserMenu.svelte'],
    rules: {
      'svelte/no-navigation-without-resolve': 'off',
    },
  },
  {
    // Generic Button primitive accepts any URL string (callers resolve
    // route IDs themselves, or pass full external URLs like /auth/login).
    // The rule can't see through the prop, so we silence it on the
    // component definition only.
    files: ['src/lib/components/ui/button/button.svelte'],
    rules: {
      'svelte/no-navigation-without-resolve': 'off',
    },
  },
  {
    // NavBar stores pre-resolved ResolvedPathname strings in a const array
    // (so we only call `resolve()` once at module init). The rule wants a
    // direct `resolve()` call at the JSX site, which we cannot do without
    // duplicating the resolve table.
    files: ['src/lib/components/app/NavBar.svelte'],
    rules: {
      'svelte/no-navigation-without-resolve': 'off',
    },
  },
  {
    ignores: [
      'build/',
      '.svelte-kit/',
      'dist/',
      'node_modules/',
      'package/',
      'playwright-report/',
      'test-results/',
    ],
  },
];
