import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

test('responsive app shell preserves every current route', () => {
  const app = readSource('../src/App.tsx');
  const shellStyles = readSource('../src/App.module.css');
  const routes = [...app.matchAll(/<Route path="([^"]+)"/g)].map((match) => match[1]);

  assert.deepEqual(routes, [
    '/',
    '/login',
    '/register',
    '/forgot-password',
    '/login2',
    '/shop-list',
    '/shop-detail/:id',
    '/shop-reviews/:id',
    '/blog-detail/:id',
    '/blog-edit',
    '/profile',
    '/profile-edit',
    '/account-security',
    '/user/:id',
    '/map',
    '/ai',
    '/index.html',
    '/login.html',
    '/login2.html',
    '/info.html',
    '/info-edit.html',
    '/blog-edit.html',
    '/shop-detail.html',
    '/blog-detail.html',
    '/shop-list.html',
    '/other-info.html',
  ]);
  assert.match(app, /function AppRoutes\(\)/);
  assert.match(app, /pathname\.replace\(\/\\\/\+\$\//);
  assert.match(shellStyles, /@media \(min-width: 1024px\)/);
  assert.match(shellStyles, /\.withPrimaryNavigation\s*\{[^}]*padding-left:\s*var\(--desktop-nav-compact-width\)/s);
});

test('primary navigation keeps the five existing actions and gains a desktop rail', () => {
  const navigation = readSource('../src/components/FootBar/index.tsx');
  const styles = readSource('../src/components/FootBar/FootBar.module.css');

  assert.equal((navigation.match(/onClick=\{\(\) => toPage\(/g) ?? []).length, 5);
  for (const key of ['home', 'map', 'create', 'ai', 'profile']) {
    assert.match(navigation, new RegExp(`nav\\.${key}`));
  }
  for (const destination of ['/', '/map', '/blog-edit', '/ai', '/profile']) {
    assert.match(navigation, new RegExp(`navigate\\('${destination.replace('/', '\\/')}'\\)`));
  }
  assert.match(styles, /\.foot\s*\{[^}]*height:\s*var\(--footer-height\)/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.foot\s*\{[^}]*position:\s*fixed;[^}]*flex-direction:\s*column;/s);
  assert.match(styles, /@media \(min-width: 1280px\)/);
});

test('home retains its mobile contract and defines the desktop grid contract', () => {
  const home = readSource('../src/pages/Home/index.tsx');
  const homeStyles = readSource('../src/pages/Home/Home.module.css');
  const cardStyles = readSource('../src/components/BlogCard/BlogCard.module.css');

  assert.match(home, /types\.map/);
  assert.match(home, /blogs\.map/);
  assert.match(home, /onScroll=\{handleScroll\}/);
  assert.match(home, /onLikeUpdate=\{handleLikeUpdate\}/);
  assert.match(home, /new ResizeObserver/);
  assert.match(homeStyles, /\.typeList\s*\{[^}]*grid-template-columns:\s*repeat\(3,/s);
  assert.match(cardStyles, /\.box\s*\{[^}]*width:\s*48%;/s);
  assert.match(homeStyles, /@media \(min-width: 1024px\)[\s\S]*?grid-template-columns:\s*repeat\(6,/s);
  assert.match(homeStyles, /@media \(min-width: 1024px\)[\s\S]*?\.blogList\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(3,/s);
  assert.match(homeStyles, /@media \(min-width: 1200px\)[\s\S]*?grid-template-columns:\s*repeat\(4,/s);
  assert.match(homeStyles, /\.loading\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;/s);
  assert.match(cardStyles, /@media \(min-width: 1024px\)[\s\S]*?\.box\s*\{[^}]*width:\s*100%;/s);
});
