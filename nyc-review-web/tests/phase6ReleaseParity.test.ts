import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

import {
  buildAuthEntryUrl,
  currentRouteTarget,
  safeAuthRedirect,
} from '../src/utils/authRedirect.ts';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

function flattenLocale(value: Record<string, unknown>, prefix = ''): Map<string, unknown> {
  const result = new Map<string, unknown>();
  for (const [key, item] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      for (const [nestedKey, nestedValue] of flattenLocale(item as Record<string, unknown>, path)) {
        result.set(nestedKey, nestedValue);
      }
    } else {
      result.set(path, item);
    }
  }
  return result;
}

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

test('authentication redirects stay internal and preserve the requested route', () => {
  assert.equal(safeAuthRedirect('/profile?section=checkin#today'), '/profile?section=checkin#today');
  assert.equal(safeAuthRedirect('/blog-edit?draft=1'), '/blog-edit?draft=1');
  assert.equal(safeAuthRedirect('https://example.com/steal'), '/');
  assert.equal(safeAuthRedirect('//example.com/steal'), '/');
  assert.equal(safeAuthRedirect('/\\example.com/steal'), '/');
  assert.equal(safeAuthRedirect('/..//example.com/steal'), '/');
  assert.equal(safeAuthRedirect('/%2e%2e//example.com/steal'), '/');
  assert.equal(safeAuthRedirect('/login?redirect=%2Fprofile'), '/');
  assert.equal(safeAuthRedirect('/REGISTER/'), '/');
  assert.equal(safeAuthRedirect('/login2'), '/');
  assert.equal(safeAuthRedirect('/login.html'), '/');
  assert.equal(safeAuthRedirect('/login2.html'), '/');
  assert.equal(safeAuthRedirect(' /profile'), '/');
  assert.equal(safeAuthRedirect(null), '/');

  const target = currentRouteTarget({
    pathname: '/profile',
    search: '?section=notes',
    hash: '#latest',
  });
  assert.equal(target, '/profile?section=notes#latest');
  assert.equal(
    buildAuthEntryUrl('/login', target, { passwordReset: '1' }),
    '/login?redirect=%2Fprofile%3Fsection%3Dnotes%23latest&passwordReset=1',
  );
  assert.equal(buildAuthEntryUrl('/login', target, { redirect: '//example.com' }),
    '/login?redirect=%2Fprofile%3Fsection%3Dnotes%23latest');
});

test('protected, expired-session, registration, and recovery flows share redirect handling', () => {
  const protectedRoute = readSource('../src/components/ProtectedRoute/index.tsx');
  const client = readSource('../src/api/client.ts');
  const login = readSource('../src/pages/Login/index.tsx');
  const register = readSource('../src/pages/Register/index.tsx');
  const forgot = readSource('../src/pages/ForgotPassword/index.tsx');
  const account = readSource('../src/pages/AccountSecurity/index.tsx');

  assert.match(protectedRoute, /useLocation\(\)/);
  assert.match(protectedRoute, /buildAuthEntryUrl\('\/login', currentRouteTarget\(location\)\)/);
  assert.match(client, /buildAuthEntryUrl\('\/login', currentRouteTarget\(window\.location\)\)/);
  assert.match(login, /safeAuthRedirect\(searchParams\.get\('redirect'\)\)/);
  assert.match(login, /buildAuthEntryUrl\('\/forgot-password', redirect\)/);
  assert.match(register, /safeAuthRedirect\(searchParams\.get\('redirect'\)\)/);
  assert.match(forgot, /buildAuthEntryUrl\('\/login', redirect, \{ passwordReset: '1' \}\)/);
  assert.match(account, /buildAuthEntryUrl\('\/login', '\/account-security', \{ passwordChanged: '1' \}\)/);
});

test('every literal translation key used by the frontend exists in both locales', () => {
  const english = flattenLocale(JSON.parse(readSource('../src/i18n/locales/en.json')));
  const chinese = flattenLocale(JSON.parse(readSource('../src/i18n/locales/zh-CN.json')));
  assert.deepEqual([...english.keys()].sort(), [...chinese.keys()].sort());

  const sourceRoot = new URL('../src/', import.meta.url).pathname;
  const literalCall = /\b(?:t|tt)\(\s*(['"`])([^'"`\n]+)\1/g;
  const used = new Set<string>();
  for (const file of sourceFiles(sourceRoot)) {
    const source = readFileSync(file, 'utf8');
    for (const match of source.matchAll(literalCall)) {
      if (!match[2].includes('${')) used.add(match[2]);
    }
  }

  const missingEnglish = [...used].filter((key) => !english.has(key));
  const missingChinese = [...used].filter((key) => !chinese.has(key));
  assert.deepEqual(missingEnglish, []);
  assert.deepEqual(missingChinese, []);
  assert.ok(used.size >= 300, `Expected broad bilingual coverage, found ${used.size} literal keys`);

  const placeholders = (value: unknown) => new Set(
    [...String(value).matchAll(/{{\s*([\w.-]+)/g)].map((match) => match[1]),
  );
  for (const [key, englishValue] of english) {
    assert.deepEqual(
      [...placeholders(englishValue)].sort(),
      [...placeholders(chinese.get(key))].sort(),
      `Interpolation placeholders differ for ${key}`,
    );
  }

  const i18n = readSource('../src/i18n/index.ts');
  assert.match(i18n, /syncDocumentLanguage\(initialLanguage\)/);
  assert.match(i18n, /i18n\.on\('languageChanged', syncDocumentLanguage\)/);
});

test('dynamic AI translation families cover every typed runtime value', () => {
  const english = flattenLocale(JSON.parse(readSource('../src/i18n/locales/en.json')));
  const chinese = flattenLocale(JSON.parse(readSource('../src/i18n/locales/zh-CN.json')));
  const dynamicKeys = [
    ...['created', 'planning', 'tool_running', 'waiting_confirmation', 'completed', 'failed', 'cancelled']
      .map((status) => `aiGuide.runStatus.${status}`),
    ...['Supervisor', 'Discovery', 'Evidence', 'Itinerary', 'Verifier']
      .map((agent) => `aiGuide.agents.${agent}`),
    ...['constraints', 'plan', 'search', 'evidence', 'itinerary', 'verify', 'finalize']
      .map((stage) => `aiGuide.workflowStages.${stage}`),
    ...['waiting', 'running', 'completed']
      .map((status) => `aiGuide.workflowStatus.${status}`),
    ...[
      'runCreated', 'runRecovered', 'modelStarted', 'modelCompleted', 'agentCompleted',
      'waitingConfirmation', 'runCompleted', 'runFailed', 'runCancelled', 'actionApproved',
      'actionStarted', 'actionCompleted', 'actionFailed', 'actionRejected',
    ].map((event) => `aiGuide.events.${event}`),
    ...['favorite_shop', 'save_itinerary', 'claim_standard_voucher', 'create_seckill_reminder']
      .flatMap((action) => [
        `agentActions.${action}.title`,
        `agentActions.${action}.description`,
      ]),
    ...['proposed', 'approved', 'executing', 'completed', 'rejected', 'failed']
      .map((status) => `agentActions.status.${status}`),
  ];

  for (const key of dynamicKeys) {
    assert.equal(typeof english.get(key), 'string', `Missing English dynamic key: ${key}`);
    assert.equal(typeof chinese.get(key), 'string', `Missing Chinese dynamic key: ${key}`);
  }
});

test('all fifteen current routes retain a desktop presentation contract', () => {
  const app = readSource('../src/App.tsx');
  const routes = [
    ['/', '../src/pages/Home/Home.module.css'],
    ['/login', '../src/pages/Login/Login.module.css'],
    ['/register', '../src/pages/Login/Login.module.css'],
    ['/forgot-password', '../src/pages/AccountSecurity/SecurityForm.module.css'],
    ['/shop-list', '../src/pages/ShopList/ShopList.module.css'],
    ['/shop-detail/:id', '../src/pages/ShopDetail/ShopDetail.module.css'],
    ['/shop-reviews/:id', '../src/pages/ShopReviews/ShopReviews.module.css'],
    ['/blog-detail/:id', '../src/pages/BlogDetail/BlogDetail.module.css'],
    ['/blog-edit', '../src/pages/BlogEdit/BlogEdit.module.css'],
    ['/profile', '../src/pages/MyProfile/MyProfile.module.css'],
    ['/profile-edit', '../src/pages/ProfileEdit/ProfileEdit.module.css'],
    ['/account-security', '../src/pages/AccountSecurity/SecurityForm.module.css'],
    ['/user/:id', '../src/pages/OtherProfile/OtherProfile.module.css'],
    ['/map', '../src/pages/Map/Map.module.css'],
    ['/ai', '../src/pages/AiWorkspace/AiWorkspace.module.css'],
  ] as const;

  assert.equal(routes.length, 15);
  for (const [route, stylesheet] of routes) {
    assert.ok(app.includes(`<Route path="${route}"`), `Missing route ${route}`);
    assert.match(readSource(stylesheet), /@media \(min-width: 1024px\)/, `${route} lacks desktop CSS`);
  }

  const appStyles = readSource('../src/App.module.css');
  const navigationStyles = readSource('../src/components/FootBar/FootBar.module.css');
  assert.match(appStyles, /@media \(min-width: 1024px\)[\s\S]*?var\(--desktop-nav-compact-width\)/);
  assert.match(appStyles, /@media \(min-width: 1280px\)[\s\S]*?var\(--desktop-nav-expanded-width\)/);
  assert.match(navigationStyles, /@media \(min-width: 1024px\)/);
  assert.match(navigationStyles, /@media \(min-width: 1280px\)/);
});

test('desktop navigation, modal surfaces, and toasts have a strict layer order', () => {
  const variables = readSource('../src/styles/variables.css');
  const globalStyles = readSource('../src/styles/global.css');
  const navigation = readSource('../src/components/FootBar/FootBar.module.css');
  const value = (name: string) => Number(
    variables.match(new RegExp(`--${name}:\\s*(\\d+)`))?.[1] ?? Number.NaN,
  );

  assert.ok(value('z-context') < value('z-map-controls'));
  assert.ok(value('z-map-controls') < value('z-primary-navigation'));
  assert.ok(value('z-primary-navigation') < value('z-modal-mask'));
  assert.ok(value('z-modal-mask') < value('z-modal-content'));
  assert.ok(value('z-modal-content') < value('z-toast'));
  for (const variable of [
    '--adm-mask-z-index: var(--z-modal-mask)',
    '--adm-popup-z-index: var(--z-modal-mask)',
    '--adm-dialog-z-index: var(--z-modal-content)',
    '--adm-center-popup-z-index: var(--z-modal-content)',
    '--adm-modal-z-index: var(--z-modal-content)',
  ]) {
    assert.ok(variables.includes(variable), `Missing modal override ${variable}`);
  }
  assert.match(globalStyles, /\.adm-mask\.adm-toast-mask\s*\{[^}]*--z-index:\s*var\(--z-toast\)/s);
  assert.match(navigation, /z-index:\s*var\(--z-primary-navigation\)/);
});

test('search and geolocation fallbacks cannot publish stale or false location state', () => {
  const home = readSource('../src/pages/Home/index.tsx');
  const map = readSource('../src/pages/Map/index.tsx');

  assert.match(home, /searchAbortRef\.current\?\.abort\(\)/);
  assert.match(home, /const requestId = \+\+searchRequestRef\.current/);
  assert.match(home, /getShopsByName\(value\.trim\(\), 1, controller\.signal\)/);
  assert.match(home, /requestId !== searchRequestRef\.current/);
  assert.match(home, /searchRequestRef\.current \+= 1/);

  const fallback = map.slice(map.indexOf('const fallbackToNyc'), map.indexOf("if (!('geolocation' in navigator))"));
  assert.match(fallback, /setUserPos\(null\)/);
  assert.doesNotMatch(fallback, /setUserPos\(NYC_CENTER\)/);
  assert.match(fallback, /tt\('map\.locationFailed'\)/);
});

test('shared note likes are single-flight and keep a successful local toggle if refresh fails', () => {
  const likeButton = readSource('../src/components/LikeButton/index.tsx');

  assert.match(likeButton, /if \(actionLockRef\.current\) return/);
  assert.match(likeButton, /actionLockRef\.current = true/);
  assert.match(likeButton, /await likeBlog\(blogId\)/);
  assert.match(likeButton, /onLikeUpdate\(Math\.max\(0, liked \+ \(isLike \? -1 : 1\)\), !isLike\)/);
  assert.match(likeButton, /disabled=\{actionPending\}/);
  assert.match(likeButton, /finally \{[\s\S]*?actionLockRef\.current = false/s);
});
