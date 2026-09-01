import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

function composeService(source: string, serviceName: string): string {
  const lines = source.split('\n');
  const start = lines.findIndex((line) => line === `  ${serviceName}:`);
  assert.notEqual(start, -1, `Missing Compose service: ${serviceName}`);

  const nextService = lines.findIndex(
    (line, index) => index > start && /^ {2}[a-z][a-z0-9-]*:$/.test(line),
  );
  return lines.slice(start, nextService === -1 ? undefined : nextService).join('\n');
}

test('local and production stacks expose the same persistent upload volume to Nginx', () => {
  const localCompose = readSource('../../compose.local.yml');
  const productionCompose = readSource('../../compose.production.yml');

  for (const compose of [localCompose, productionCompose]) {
    const spring = composeService(compose, 'spring');
    const web = composeService(compose, 'web');

    assert.match(spring, /NYC_REVIEW_IMAGE_UPLOAD_DIR:\s*\/data\/uploads/);
    assert.match(spring, /- (?:nyc-review-uploads|uploads):\/data\/uploads/);
    assert.match(web, /- (?:nyc-review-uploads|uploads):\/data\/imgs:ro/);
    assert.doesNotMatch(web, /:\/usr\/share\/nginx\/html\/imgs(?::ro)?/);
  }
});

test('Nginx preserves bundled images before resolving uploaded public paths under /data/imgs', () => {
  const nginx = readSource('../nginx.conf');
  const staticImages = nginx.slice(
    nginx.indexOf('location /imgs/'),
    nginx.indexOf('location @uploaded_image'),
  );
  const uploadedImages = nginx.slice(nginx.indexOf('location @uploaded_image'));

  assert.match(staticImages, /root \/usr\/share\/nginx\/html;/);
  assert.match(staticImages, /try_files \$uri @uploaded_image;/);
  assert.match(uploadedImages, /root \/data;/);
  assert.match(uploadedImages, /try_files \$uri =404;/);
});

test('Spring stores the same relative blog path that the public /imgs fallback serves', () => {
  const storage = readSource('../../src/main/java/com/nycreview/service/ImageStorageService.java');

  assert.match(storage, /root\.resolve\("blogs"\)\.resolve\(userId\.toString\(\)\)/);
  assert.match(storage, /Files\.copy\(inputStream, target\)/);
  assert.match(storage, /return "\/imgs\/blogs\/" \+ userId \+ "\/" \+ fileName;/);
});

test('desktop top filters remain fully reachable without hidden horizontal scrolling', () => {
  const mapStyles = readSource('../src/pages/Map/Map.module.css');
  const editorStyles = readSource('../src/pages/BlogEdit/BlogEdit.module.css');
  const mapDesktop = mapStyles.slice(
    mapStyles.indexOf('@media (min-width: 1024px)'),
    mapStyles.indexOf('@media (min-width: 1440px)'),
  );
  const editorDesktop = editorStyles.slice(
    editorStyles.indexOf('@media (min-width: 1024px)'),
    editorStyles.length,
  );

  assert.match(mapDesktop, /\.filterScroller\s*\{[^}]*display:\s*grid;/s);
  assert.match(mapDesktop, /grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(108px,\s*1fr\)\)/);
  assert.match(mapDesktop, /\.filterScroller\s*\{[^}]*overflow:\s*visible;/s);
  assert.doesNotMatch(mapDesktop, /\.filterScroller\s*\{[^}]*overflow-x:\s*auto;/s);
  assert.match(mapDesktop, /\.filterChip\s*\{[^}]*min-width:\s*0;[^}]*box-sizing:\s*border-box;[^}]*white-space:\s*normal;/s);
  assert.match(mapDesktop, /\.modeBadge\s*\{[^}]*top:\s*112px;/s);
  assert.match(mapDesktop, /\.emptyBadge\s*\{[^}]*top:\s*148px;/s);
  assert.match(editorDesktop, /\.categoryList\s*\{[^}]*flex-wrap:\s*wrap;[^}]*overflow-x:\s*visible;/s);
  assert.match(editorDesktop, /\.inlineShopPicker\s*\{[^}]*display:\s*flex;[^}]*overflow:\s*hidden;/s);
  assert.match(editorDesktop, /\.mask,\s*\.shopDialog\s*\{\s*display:\s*none;/s);
});

test('profile edit uses navigation-aware desktop overlays with mouse-wheel pickers', () => {
  const page = readSource('../src/pages/ProfileEdit/index.tsx');
  const styles = readSource('../src/pages/ProfileEdit/ProfileEdit.module.css');

  assert.match(page, /const pageRef = useRef<HTMLDivElement>\(null\)/);
  assert.match(page, /<div ref=\{pageRef\} className=\{styles\.container\}>/);
  assert.equal(page.match(/getContainer=\{getPopupContainer\}/g)?.length, 5);
  assert.equal(page.match(/\n\s+mouseWheel\n/g)?.length, 4);
  assert.match(page, /bodyClassName=\{styles\.editPopupBody\}/);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.container \.editPopupBody,[\s\S]*?left:\s*calc\(50% \+ 40px\);[\s\S]*?width:\s*min\(560px,/s);
  assert.match(styles, /\.container \.editPopupBody,[\s\S]*?translate:\s*-50% 0;/s);
  assert.doesNotMatch(styles, /\.container \.editPopupBody,[\s\S]*?transform:\s*translateX/s);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*?left:\s*calc\(50% \+ 108px\);[\s\S]*?width:\s*min\(560px,/s);
});

test('long headers, owner actions and transient states stay centered and bounded', () => {
  const home = readSource('../src/pages/Home/Home.module.css');
  const shopDetail = readSource('../src/pages/ShopDetail/ShopDetail.module.css');
  const shopReviews = readSource('../src/pages/ShopReviews/ShopReviews.module.css');
  const blogDetail = readSource('../src/pages/BlogDetail/BlogDetail.module.css');
  const otherProfile = readSource('../src/pages/OtherProfile/OtherProfile.module.css');
  const base = (source: string) => source.slice(0, source.indexOf('@media'));

  assert.match(base(home), /\.loading\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0;[^}]*box-sizing:\s*border-box;/s);
  for (const source of [shopDetail, shopReviews]) {
    assert.match(base(source), /\.title\s*\{[^}]*min-width:\s*0;[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis;[^}]*white-space:\s*nowrap;/s);
  }
  assert.match(base(shopDetail), /\.backBtn\s*\{[^}]*align-items:\s*center;[^}]*justify-content:\s*center;/s);
  assert.match(base(shopDetail), /\.share\s*\{[^}]*display:\s*flex;[^}]*align-items:\s*center;[^}]*justify-content:\s*center;/s);
  assert.match(base(blogDetail), /\.title\s*\{[^}]*position:\s*absolute;[^}]*left:\s*50%;[^}]*transform:\s*translateX\(-50%\);/s);
  assert.match(base(blogDetail), /\.loadingFull\s*\{[^}]*flex:\s*1;[^}]*min-height:\s*0;/s);
  assert.match(base(otherProfile), /\.loadingFull\s*\{[^}]*flex:\s*1;[^}]*min-height:\s*0;/s);
});
