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
