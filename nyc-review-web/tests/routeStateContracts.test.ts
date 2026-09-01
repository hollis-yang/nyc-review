import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { resolveLegacyRedirect } from '../src/components/legacyRedirectTarget.ts';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

test('legacy detail links resolve valid ids and safely reject missing or invalid ids', () => {
  assert.equal(resolveLegacyRedirect('/shop-detail.html', '?id=42'), '/shop-detail/42');
  assert.equal(resolveLegacyRedirect('/blog-detail.html', '?id=9001'), '/blog-detail/9001');
  assert.equal(resolveLegacyRedirect('/other-info.html', '?id=7'), '/user/7');

  for (const search of ['', '?id=', '?id=0', '?id=-1', '?id=abc', '?id=1%2Fedit']) {
    assert.equal(resolveLegacyRedirect('/shop-detail.html', search), '/shop-list');
    assert.equal(resolveLegacyRedirect('/blog-detail.html', search), '/');
    assert.equal(resolveLegacyRedirect('/other-info.html', search), '/');
  }

  assert.equal(resolveLegacyRedirect('/shop-list.html'), '/shop-list');
  assert.equal(resolveLegacyRedirect('/shop-list.html', '?type=2&name=Cafes%20%26%20Desserts'), '/shop-list?type=2&name=Cafes+%26+Desserts');
  assert.equal(resolveLegacyRedirect('/unknown.html', '?id=42'), '/');
});

test('unknown routes render a localized recovery surface', () => {
  const app = readSource('../src/App.tsx');
  const styles = readSource('../src/App.module.css');

  assert.match(app, /function RouteFallback\(\)/);
  assert.match(app, /routeFallback\.title/);
  assert.match(app, /routeFallback\.description/);
  assert.match(app, /routeFallback\.home/);
  assert.match(app, /<Link className=\{styles\.routeFallbackAction\} to="\/">/);
  assert.match(app, /<Route path="\*" element=\{<RouteFallback \/>\} \/>/);
  assert.match(styles, /\.routeFallback\s*\{[^}]*min-height:\s*100%;/s);
  assert.match(styles, /\.routeFallbackAction:focus-visible/);
});

test('shop list uses an all-categories title when no search or category is selected', () => {
  const page = readSource('../src/pages/ShopList/index.tsx');

  assert.match(page, /const listTitle = searchQuery[\s\S]*?: typeName[\s\S]*?: t\('shopList\.allCategories'\);/);
  assert.match(page, /<div className=\{styles\.title\}>\s*\{listTitle\}\s*<\/div>/);
});

test('shop reviews expose independent loading, initial error, empty, and pagination retry states', () => {
  const page = readSource('../src/pages/ShopReviews/index.tsx');
  const styles = readSource('../src/pages/ShopReviews/ShopReviews.module.css');

  assert.match(page, /type ReviewLoadError = 'initial' \| 'pagination' \| null/);
  assert.match(page, /const loadInitialReviews = useCallback\(async \(\) =>/);
  assert.match(page, /sequence !== requestSequence\.current/);
  assert.match(page, /setLoadError\('initial'\)/);
  assert.match(page, /setLoadError\('pagination'\)/);
  assert.match(page, /catch \(error\) \{\s*if \(sequence === requestSequence\.current\) setLoadError\('pagination'\);\s*throw error;/s);
  assert.match(page, /loadError === 'initial'[\s\S]*?shopReviews\.loadFailed[\s\S]*?onClick=\{loadInitialReviews\}/);
  assert.match(page, /!loading && loadError === null && reviews\.length === 0[\s\S]*?shopReviews\.empty[\s\S]*?shopReviews\.emptyHint/);
  assert.match(page, /loadError === 'pagination' && reviews\.length > 0[\s\S]*?shopReviews\.moreFailed[\s\S]*?onClick=\{loadReviews\}/);
  assert.match(page, /!hasMore && loadError === null && reviews\.length > 0/);
  assert.match(styles, /\.statePanel\s*\{/);
  assert.match(styles, /\.retryButton:focus-visible/);
  assert.match(styles, /\.paginationError\s*\{/);
});

test('new route states have matching English and Chinese translations', () => {
  const en = JSON.parse(readSource('../src/i18n/locales/en.json'));
  const zh = JSON.parse(readSource('../src/i18n/locales/zh-CN.json'));
  const paths = [
    ['routeFallback', 'title'],
    ['routeFallback', 'description'],
    ['routeFallback', 'home'],
    ['shopReviews', 'loadFailed'],
    ['shopReviews', 'retry'],
    ['shopReviews', 'empty'],
    ['shopReviews', 'emptyHint'],
    ['shopReviews', 'moreFailed'],
  ];

  for (const [group, key] of paths) {
    assert.equal(typeof en[group][key], 'string', `Missing English key: ${group}.${key}`);
    assert.equal(typeof zh[group][key], 'string', `Missing Chinese key: ${group}.${key}`);
    assert.ok(en[group][key].length > 0);
    assert.ok(zh[group][key].length > 0);
  }
});
