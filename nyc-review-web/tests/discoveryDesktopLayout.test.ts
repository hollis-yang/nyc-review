import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

test('shop list preserves filters and states while defining the desktop result grid', () => {
  const shopList = readSource('../src/pages/ShopList/index.tsx');
  const styles = readSource('../src/pages/ShopList/ShopList.module.css');

  for (const field of ['distance', 'popularity', 'rating']) {
    assert.match(shopList, new RegExp(`field: '${field}'`));
  }
  assert.match(shopList, /types\.map/);
  assert.match(shopList, /handleTypeChange/);
  assert.match(shopList, /onScroll=\{handleScroll\}/);
  assert.match(shopList, /shops\.length === 0/);
  assert.match(shopList, /shopList\.locating/);
  assert.match(shopList, /shopList\.noResults/);
  assert.match(shopList, /shopList\.loading/);
  assert.match(shopList, /requestAbortController\.current\?\.abort\(\)/);
  assert.match(shopList, /sequence !== requestSequence\.current/);
  assert.match(shopList, /underfillAttemptLength\.current === shops\.length/);
  assert.match(shopList, /new ResizeObserver\(fillUnderfilledViewport\)/);
  assert.match(styles, /\.categoryGrid\s*\{[^}]*grid-template-columns:\s*repeat\(3,/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?grid-template-columns:\s*240px minmax\(0, 1fr\)/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.categoryPanel[\s\S]*?display:\s*block;/s);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*?grid-template-columns:\s*repeat\(2,/s);
  assert.match(styles, /\.loading,[\s\S]*?\.emptySearch\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;/s);
});

test('shop card keeps every existing display field and gains bounded desktop media', () => {
  const shopCard = readSource('../src/components/ShopCard/index.tsx');
  const styles = readSource('../src/components/ShopCard/ShopCard.module.css');

  for (const field of [
    'shop.name',
    'shop.score',
    'displayReviewCount',
    'shop.area',
    'shop.distance',
    'shop.avgPrice',
    'shop.address',
  ]) {
    assert.match(shopCard, new RegExp(field.replace('.', '\\.')));
  }
  assert.match(shopCard, /shopCard\.ratingUnavailable/);
  assert.match(shopCard, /shopCard\.priceUnavailable/);
  assert.match(shopCard, /<Link[\s\S]*?to=\{`\/shop-detail\/\$\{shop\.id\}`\}/s);
  assert.match(styles, /\.img\s*\{[^}]*width:\s*30%;/s);
  assert.match(styles, /\.img img\s*\{[^}]*height:\s*80px;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.img\s*\{[^}]*width:\s*136px;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.img img\s*\{[^}]*height:\s*108px;/s);
});

test('map keeps filters, viewport states and popups with a desktop top filter bar', () => {
  const mapPage = readSource('../src/pages/Map/index.tsx');
  const styles = readSource('../src/pages/Map/Map.module.css');

  assert.match(mapPage, /role="group"/);
  assert.match(mapPage, /aria-pressed=/);
  assert.match(mapPage, /selectAllTypes/);
  assert.match(mapPage, /toggleType/);
  assert.match(mapPage, /next\.set\('types', selectedTypeKey\)/);
  assert.match(mapPage, /getMapViewport\(\{/);
  assert.match(mapPage, /typeIds,/);
  assert.match(mapPage, /styles\.loadingOverlay/);
  assert.match(mapPage, /styles\.errorOverlay/);
  assert.match(mapPage, /styles\.emptyBadge/);
  assert.match(mapPage, /styles\.densityNotice/);
  assert.match(mapPage, /shop\.name/);
  assert.match(mapPage, /shop\.avgPrice/);
  assert.match(mapPage, /shop\.neighborhood \|\| shop\.area/);
  assert.match(mapPage, /function MapResizeObserver/);
  assert.match(mapPage, /map\.invalidateSize\(\{ pan: false, animate: false \}\)/);
  assert.match(styles, /\.filterScroller\s*\{[^}]*display:\s*flex;[^}]*overflow-x:\s*auto;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.mapCanvas\s*\{[^}]*width:\s*100%;[^}]*height:\s*100%;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.filterPanel\s*\{[^}]*position:\s*absolute;[^}]*top:\s*16px;[^}]*left:\s*50%;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.filterScroller\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(108px,\s*1fr\)\);[^}]*overflow:\s*visible;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.filterChip\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0;[^}]*box-sizing:\s*border-box;[^}]*white-space:\s*normal;/s);
  assert.doesNotMatch(styles, /@media \(min-width: 1024px\)[\s\S]*?\.mapWrap\s*\{[^}]*grid-template-columns:/s);
  assert.match(styles, /@media \(min-width: 1440px\)[\s\S]*?\.filterPanel\s*\{[^}]*width:\s*min\(1040px,/s);
});
