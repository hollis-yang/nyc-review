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
  assert.match(navigation, /function CreateNoteIcon/);
  assert.match(navigation, /styles\.createMobileIcon/);
  assert.match(navigation, /styles\.createDesktopIcon/);
  assert.match(navigation, /styles\.createText[^\n]*nav\.create/);
  assert.match(styles, /\.createDesktopIcon,\s*\.createText\s*\{\s*display:\s*none;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.createMobileIcon\s*\{\s*display:\s*none;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.createDesktopIcon\s*\{[^}]*display:\s*flex;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.createText\s*\{\s*display:\s*block;/s);
  assert.doesNotMatch(styles, /\.createBox\s*\{/);
});

test('home retains its mobile contract and defines the desktop grid contract', () => {
  const home = readSource('../src/pages/Home/index.tsx');
  const homeStyles = readSource('../src/pages/Home/Home.module.css');
  const cardStyles = readSource('../src/components/BlogCard/BlogCard.module.css');

  assert.match(home, /types\.map/);
  assert.match(home, /blogs\.map/);
  assert.match(home, /onScroll=\{handleScroll\}/);
  assert.match(home, /onLikeUpdate=\{handleLikeUpdate\}/);
  assert.match(home, /const \[loadError, setLoadError\]/);
  assert.match(home, /const \[paginationPaused, setPaginationPaused\]/);
  assert.match(home, /setLoadError\(true\)/);
  assert.match(home, /loadedBlogIdsRef = useRef<Set<number>>\(new Set\(\)\)/);
  assert.match(home, /takeUnseenById\(enriched, loadedBlogIdsRef\.current\)/);
  assert.match(home, /uniqueBlogs\.length === 0/);
  assert.match(home, /setPaginationPaused\(true\)/);
  assert.match(home, /hasMore &&\s*!loadError &&\s*!paginationPaused/s);
  assert.match(home, /home\.loadFailed/);
  assert.match(home, /home\.retry/);
  assert.match(home, /home\.noNewNotes/);
  assert.match(home, /home\.continue/);
  assert.match(home, /home\.empty/);
  assert.match(home, /el\.scrollHeight > el\.clientHeight \+ 1/);
  assert.match(home, /underfillAttemptPage\.current === current/);
  assert.match(home, /if \(loadingRef\.current \|\| !hasMore\) return;\s*underfillAttemptPage\.current = current;\s*loadingRef\.current = true;/s);
  assert.match(home, /new ResizeObserver\(fillUnderfilledViewport\)/);
  assert.match(home, /const DESKTOP_INITIAL_BLOG_COUNT = 12/);
  assert.match(home, /window\.matchMedia\('\(min-width: 1024px\)'\)\.matches/);
  assert.match(home, /blogs\.length < DESKTOP_INITIAL_BLOG_COUNT/);
  assert.match(home, /!needsDesktopInitialPrefetch && el\.scrollHeight > el\.clientHeight \+ 1/);
  assert.match(homeStyles, /\.typeList\s*\{[^}]*grid-template-columns:\s*repeat\(3,/s);
  assert.match(cardStyles, /\.box\s*\{[^}]*width:\s*48%;/s);
  assert.match(homeStyles, /@media \(min-width: 1024px\)[\s\S]*?grid-template-columns:\s*repeat\(6,/s);
  assert.match(homeStyles, /@media \(min-width: 1024px\)[\s\S]*?\.blogList\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(3,/s);
  assert.match(homeStyles, /@media \(min-width: 1024px\)[\s\S]*?\.container\s*\{[^}]*overflow:\s*hidden;/s);
  assert.match(homeStyles, /@media \(min-width: 1024px\)[\s\S]*?\.blogList\s*\{[^}]*min-height:\s*0;/s);
  assert.match(homeStyles, /@media \(min-width: 1200px\)[\s\S]*?grid-template-columns:\s*repeat\(4,/s);
  assert.match(homeStyles, /@media \(min-width: 1024px\)[\s\S]*?\.blogList\s*\{[^}]*scrollbar-width:\s*thin;[^}]*scrollbar-color:/s);
  assert.match(homeStyles, /\.blogList::-webkit-scrollbar-thumb\s*\{[^}]*border-radius:\s*999px;/s);
  assert.match(homeStyles, /\.loading\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;/s);
  assert.match(cardStyles, /@media \(min-width: 1024px\)[\s\S]*?\.box\s*\{[^}]*width:\s*100%;/s);
  assert.match(cardStyles, /\.box\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;/s);
  assert.match(cardStyles, /\.title\s*\{[^}]*flex:\s*1 1 auto;/s);
  assert.match(cardStyles, /@media \(min-width: 1024px\)[\s\S]*?\.foot\s*\{[^}]*margin-top:\s*auto;/s);
});

test('blog editor keeps primary navigation on desktop without adding a mobile footer', () => {
  const app = readSource('../src/App.tsx');
  const editor = readSource('../src/pages/BlogEdit/index.tsx');
  const editorStyles = readSource('../src/pages/BlogEdit/BlogEdit.module.css');
  const navigationList = app.match(/const routesWithPrimaryNavigation = \[([\s\S]*?)\];/)?.[1] ?? '';

  assert.match(navigationList, /'\/blog-edit'/);
  assert.match(editor, /styles\.desktopNavigation/);
  assert.match(editor, /<FootBar activeBtn=\{0\}/);
  assert.match(editorStyles, /\.desktopNavigation\s*\{\s*display:\s*none;/s);
  assert.match(editorStyles, /@media \(min-width: 1024px\)[\s\S]*?\.desktopNavigation\s*\{\s*display:\s*block;/s);
});
