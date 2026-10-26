const { test, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

require.extensions['.ts'] = (module, filename) => {
  module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
  } }).outputText, filename);
};
const { initialiseTheme, themeSnapshot, setTheme, subscribeTheme } = require('../src/theme.ts');
const KEY = 'pitch-insights.theme.v1';
let saved;

beforeEach(() => {
  saved = new Map();
  global.document = { documentElement: { dataset: {}, style: {} } };
  global.window = Object.assign(new EventTarget(), { localStorage: {
    getItem: (key) => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, value),
  }, matchMedia: () => ({ matches: true }) });
});

test('a first visit defaults to light even when the device prefers dark', () => {
  initialiseTheme();
  assert.equal(themeSnapshot(), 'light');
  assert.equal(document.documentElement.style.colorScheme, 'light');
});

test('a saved dark choice is restored and a new choice notifies this document', () => {
  saved.set(KEY, 'dark');
  initialiseTheme();
  assert.equal(themeSnapshot(), 'dark');
  let notified = 0;
  const unsubscribe = subscribeTheme(() => notified++);
  setTheme('light');
  assert.equal(saved.get(KEY), 'light');
  assert.equal(themeSnapshot(), 'light');
  assert.equal(notified, 1);
  unsubscribe();
});

test('blocked storage still allows changing the theme for this visit', () => {
  Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } });
  initialiseTheme();
  assert.equal(themeSnapshot(), 'light');
  setTheme('dark');
  assert.equal(themeSnapshot(), 'dark');
});

test('storage changes from another pane update appearance, and clearing storage restores light', () => {
  initialiseTheme();
  let notified = 0;
  const unsubscribe = subscribeTheme(() => notified++);
  saved.set(KEY, 'dark');
  window.dispatchEvent(Object.assign(new Event('storage'), { key: KEY }));
  assert.equal(themeSnapshot(), 'dark');
  saved.clear();
  window.dispatchEvent(Object.assign(new Event('storage'), { key: null }));
  assert.equal(themeSnapshot(), 'light');
  assert.equal(notified, 2);
  unsubscribe();
  saved.set(KEY, 'dark');
  window.dispatchEvent(Object.assign(new Event('storage'), { key: KEY }));
  assert.equal(themeSnapshot(), 'light');
});

test('unrelated or invalid saved preferences do not turn dark mode on', () => {
  saved.set(KEY, 'invalid');
  initialiseTheme();
  let notified = 0;
  const unsubscribe = subscribeTheme(() => notified++);
  window.dispatchEvent(Object.assign(new Event('storage'), { key: 'profile' }));
  assert.equal(themeSnapshot(), 'light');
  assert.equal(notified, 0);
  unsubscribe();
});
