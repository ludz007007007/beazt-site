#!/usr/bin/env node
// Assemble + minify the readable CSS sources in static/css/src into the
// served bundles, and bump the ?v=N cache-buster in the base templates when a
// bundle changes. Node stdlib only.
//
//   node scripts/build-css.mjs          build (and bump cache-busters)
//   node scripts/build-css.mjs --check  exit 1 if a bundle is out of date

import { readFileSync, writeFileSync, existsSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(ROOT, 'static', 'css', 'src');
const OUT = join(ROOT, 'static', 'css');
const TEMPLATES = [join(ROOT, 'templates', 'base.html'), join(ROOT, 'templates', 'admin', 'base.html')];
const TEMPLATE_DIR = join(ROOT, 'templates');

// Order matters: the component library sits before the site shell so page
// and shell rules win on equal specificity.
const BUNDLES = {
  'style.css': ['tokens.css', 'base.css', 'components.css', 'site.css'],
  'admin.css': ['admin.css'],
};

// Custom-property names that must survive token-name shortening, because
// they are referenced OUTSIDE the CSS sources:
//  1. var(--x) in any template (inline styles, inline SVG attributes),
//  2. names asserted as literal strings by tests/test_design_system.py.
// The admin.css bundle resolves the shared names through the cascade, so it
// is NOT in the keep list: both bundles are shortened with the SAME rename
// map (see main), which keeps the cascade intact while letting the large
// token families (--space-*, --text-*, ...) shrink in both bundles.
function collectKeepTokens() {
  const keep = new Set([
    '--accent', '--on-accent', '--focus-ring', '--focus-ring-width',
    '--focus-ring-color', '--font-display', '--font-stretch-display',
    '--font-stretch-eyebrow', '--font-weight-display',
  ]);
  (function walk(dir) {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) {
        walk(p);
      } else if (name.endsWith('.html')) {
        for (const m of readFileSync(p, 'utf8').matchAll(/var\((--[\w-]+)/g)) {
          keep.add(m[1]);
        }
      }
    }
  })(TEMPLATE_DIR);
  return keep;
}

// Custom properties are only DEFINED right after '{' or ';' in minified
// output (never inside a selector). Strings are \u0000 placeholders at this
// point, so data URIs and font names cannot be touched.
function collectDefinedTokens(minified) {
  const defined = new Set();
  for (const m of minified.matchAll(/[{;](--[\w-]+)(?=:)/g)) defined.add(m[1]);
  return defined;
}

function buildRenameMap(defined, keep, reserved) {
  const aliases = [];
  for (const a of 'abcdefghijklmnopqrstuvwxyz') aliases.push('--' + a);
  for (const a of 'abcdefghijklmnopqrstuvwxyz') {
    for (const b of 'abcdefghijklmnopqrstuvwxyz') aliases.push('--' + a + b);
  }
  // An alias must never equal a name that keeps its original meaning in any
  // loaded stylesheet: keep-list names (template refs, test assertions) or
  // tokens defined by the admin bundle (which loads alongside style.css).
  const forbidden = new Set([...keep, ...reserved]);
  const pool = aliases.filter((a) => !forbidden.has(a));
  const map = new Map();
  let i = 0;
  // Longest names first; the (?![\w-]) guard in applyRenameMap stops a name
  // from matching inside a longer one (--accent never hits --accent-border).
  for (const name of [...defined].filter((n) => !keep.has(n)).sort((a, b) => b.length - a.length)) {
    map.set(name, pool[i++]);
    if (i >= pool.length) break;
  }
  return map;
}

function applyRenameMap(css, map) {
  // A custom property can only appear as a var() argument (preceded by "(")
  // or a declaration start (preceded by "{" or ";"). Requiring that lookbehind
  // keeps BEM class names like .loader-callout--info (which contain "--info")
  // untouched.
  for (const [name, alias] of map) {
    css = css.replace(
      new RegExp("(?<=[(;{])" + name + "(?![\\w-])", "g"),
      alias,
    );
  }
  return css;
}

export function minify(css, opts) {
  const strings = [];
  // Comments and strings are matched in one pass so an apostrophe inside a
  // comment is never mistaken for the start of a string.
  let s = css.replace(/(\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/g, (m) => {
    if (m.startsWith('/*')) return '';
    strings.push(m);
    return `\u0000${strings.length - 1}\u0000`;
  });
  s = s
    .replace(/\s+/g, ' ')
    .replace(/\s*([{};,>])\s*/g, '$1')
    // "prop: value" -> "prop:value" only at declaration starts, never in selectors
    .replace(/([{;])([-\w]+)\s*:\s*/g, '$1$2:')
    .replace(/;}/g, '}')
    .replace(/\s*!important/g, '!important')
    .trim();
  // Restore the space media queries need after "and" when followed by "(".
  s = s.replace(/\band\(/g, 'and (');
  if (opts && opts.mangle) {
    s = opts.mangle(s);
  }
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => strings[Number(i)]) + '\n';
}

// Shared rename map: computed once from the style bundle's definitions,
// then applied verbatim to every bundle so cross-bundle var() references
// keep resolving.
let RENAME_MAP = null;
const KEEP_TOKENS = collectKeepTokens();

function bumpCacheBuster(file) {
  const pattern = new RegExp(`(/static/css/${file.replace('.', '\\.')}\\?v=)(\\d+)`, 'g');
  for (const tpl of TEMPLATES) {
    if (!existsSync(tpl)) continue;
    const html = readFileSync(tpl, 'utf8');
    const next = html.replace(pattern, (_, prefix, n) => `${prefix}${Number(n) + 1}`);
    if (next !== html) {
      writeFileSync(tpl, next);
      console.log(`  bumped ${file} cache-buster in ${relative(ROOT, tpl)}`);
    }
  }
}

function main() {
  const check = process.argv.includes('--check');
  let stale = 0;
  for (const [name, parts] of Object.entries(BUNDLES)) {
    const target = join(OUT, name);
    const banner = `/*! BEAZT ${name} - generated by scripts/build-css.mjs from static/css/src (${parts.join(', ')}). Do not edit. */\n`;
    if (name === 'style.css') {
      // First pass (strings still placeholdered) computes the shared rename
      // map from this bundle's definitions.
      const body = parts.map((p) => readFileSync(join(SRC, p), 'utf8')).join('\n');
      const css = banner + minify(body, { mangle: (s) => {
        // Names defined by admin.css survive mangling there (not in the style
        // bundle's definition set), so they are reserved as alias values.
        const reserved = collectDefinedTokens(
          minify(readFileSync(join(SRC, 'admin.css'), 'utf8')),
        );
        RENAME_MAP = buildRenameMap(collectDefinedTokens(s), KEEP_TOKENS, reserved);
        return applyRenameMap(s, RENAME_MAP);
      } });
      if (!writeOut(name, css, target, check)) stale += 1;
    } else {
      const css = banner + minify(
        parts.map((p) => readFileSync(join(SRC, p), 'utf8')).join('\n'),
        { mangle: (s) => applyRenameMap(s, RENAME_MAP ?? new Map()) },
      );
      if (!writeOut(name, css, target, check)) stale += 1;
    }
  }
  if (stale) process.exit(1);
}

function writeOut(name, css, target, check) {
  // core.autocrlf may check the bundle out with CRLF endings; compare content only.
  const current = existsSync(target) ? readFileSync(target, 'utf8').replace(/\r\n/g, '\n') : '';
  const kb = (Buffer.byteLength(css) / 1024).toFixed(1);
  if (css === current) {
    console.log(`${name}: up to date (${kb} KB)`);
    return true;
  }
  if (check) {
    console.error(`${name}: OUT OF DATE - run node scripts/build-css.mjs`);
    return false;
  }
  writeFileSync(target, css);
  console.log(`${name}: written (${kb} KB)`);
  bumpCacheBuster(name);
  return true;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main();
}
