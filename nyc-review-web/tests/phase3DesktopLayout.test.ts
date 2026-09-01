import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
);

function assertInOrder(source: string, tokens: string[]) {
  let cursor = -1;
  for (const token of tokens) {
    const next = source.indexOf(token, cursor + 1);
    assert.notEqual(next, -1, `Missing ordered token: ${token}`);
    assert.ok(next > cursor, `Out-of-order token: ${token}`);
    cursor = next;
  }
}

test('shop detail preserves its commerce and review contract in two desktop grids', () => {
  const page = readSource('../src/pages/ShopDetail/index.tsx');
  const voucher = readSource('../src/components/VoucherCard/index.tsx');
  const styles = readSource('../src/pages/ShopDetail/ShopDetail.module.css');
  const voucherStyles = readSource('../src/components/VoucherCard/VoucherCard.module.css');

  for (const call of ['getShopById', 'getVoucherList', 'getShopReviews']) {
    assert.match(page, new RegExp(`${call}\\(`));
  }
  for (const field of [
    'shop.name',
    'shop.score',
    'displayReviewCount',
    'shop.avgPrice',
    'shop.address',
    'shop.openHours',
    'shop.phone',
    'shop.website',
    'shop.reservationUrl',
  ]) {
    assert.match(page, new RegExp(field.replace('.', '\\.')));
  }
  assert.match(page, /imageAssets\.map/);
  assert.match(page, /vouchers\.map/);
  assert.match(page, /reviews\.slice\(0, 3\)\.map/);
  assert.match(page, /<ReviewThread/);
  assert.match(page, /id="write-shop-review"/);
  assert.match(page, /favoriteShop\(routeId\)/);
  assert.match(page, /unfavoriteShop\(routeId\)/);
  assert.match(page, /seckillVoucher\(voucherId\)/);
  assert.match(page, /const seckillRequestsRef = useRef\(new Set<number>\(\)\)/);
  assert.match(page, /if \(seckillRequestsRef\.current\.has\(voucherId\)\) return;/);
  assert.match(page, /seckillRequestsRef\.current\.add\(voucherId\)/);
  assert.match(page, /finally \{\s*seckillRequestsRef\.current\.delete\(voucherId\);\s*\}/s);
  assert.match(voucher, /onSeckill: \(id: number\) => Promise<void> \| void/);
  assert.match(voucher, /const actionLockRef = useRef\(false\)/);
  assert.match(voucher, /const \[actionPending, setActionPending\] = useState\(false\)/);
  assert.match(voucher, /if \(actionLockRef\.current\) return;/);
  assert.match(voucher, /await onSeckill\(v\.id\)/);
  assert.match(voucher, /finally \{\s*actionLockRef\.current = false;\s*setActionPending\(false\);\s*\}/s);
  assert.equal(voucher.match(/<button/g)?.length, 2);
  assert.equal(voucher.match(/disabled=\{disabled\}/g)?.length, 2);
  assert.equal(voucher.match(/aria-busy=\{actionPending\}/g)?.length, 2);
  assert.match(page, /createShopReview\(\{ shopId: Number\(routeId\), rating: reviewRating/);
  assert.match(page, /const reviewSubmittingRef = useRef<number \| null>\(null\)/);
  assert.match(page, /if \(reviewSubmittingRef\.current === generation\) return/);
  assert.match(page, /reviewSubmittingRef\.current = generation/);
  assert.match(page, /routeGenerationRef\.current !== generation \|\| activeShopIdRef\.current !== routeId/);
  assert.match(page, /Promise\.allSettled\(\[/);
  assert.match(page, /t\('shopDetail\.reviewRefreshFailed'\)/);
  assert.match(page, /<button\s+type="button"\s+className=\{styles\.reviewSubmit\}/s);
  assert.match(page, /disabled=\{reviewSubmitting \|\| !reviewContent\.trim\(\)\}/);
  assert.match(page, /if \(reviewSubmittingRef\.current === generation\) reviewSubmittingRef\.current = null/);
  assert.match(page, /const \[shopLoadFailed, setShopLoadFailed\] = useState\(false\)/);
  assert.match(page, /const \[vouchersLoadFailed, setVouchersLoadFailed\] = useState\(false\)/);
  assert.match(page, /const \[reviewsLoadFailed, setReviewsLoadFailed\] = useState\(false\)/);
  assert.doesNotMatch(page, /Promise\.all\(\[\s*getShopById/);
  assert.match(page, /maps\.apple\.com\/\?q=/);
  assert.match(page, /\{shop\.phone &&/);
  assert.match(page, /\{shop\.website &&/);
  assert.match(page, /\{shop\.reservationUrl &&/);
  assert.match(page, /styles\.lowerGrid/);
  assert.match(page, /styles\.supportColumn/);
  assert.match(page, /styles\.conversationColumn/);
  assertInOrder(page, [
    'styles.shopImages',
    'styles.quickFacts',
    'styles.shopAddress',
    'styles.openTime',
    'styles.voucherSection',
    'styles.comments',
    'id="write-shop-review"',
  ]);
  assert.match(styles, /\.lowerGrid,[\s\S]*?\.conversationColumn\s*\{[^}]*display:\s*contents;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.infoBox\s*\{[^}]*grid-template-columns:\s*minmax\(0, 7fr\) minmax\(320px, 5fr\)/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.lowerGrid\s*\{[^}]*grid-template-columns:\s*minmax\(0, 2fr\) minmax\(300px, 1fr\)/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.shopImages\s*\{[^}]*overflow-x:\s*auto;/s);
  assert.match(voucherStyles, /@media \(min-width: 1024px\)[\s\S]*?overflow-wrap:\s*anywhere;/s);
  assert.match(voucherStyles, /\.btn:disabled\s*\{[^}]*cursor:\s*not-allowed;[^}]*opacity:\s*0\.72;/s);
});

test('shop reviews remains one reading column with safe responsive continuation', () => {
  const page = readSource('../src/pages/ShopReviews/index.tsx');
  const styles = readSource('../src/pages/ShopReviews/ShopReviews.module.css');

  assert.match(page, /getShopById\(id\)/);
  assert.match(page, /getShopReviews\(id, 1\)/);
  assert.match(page, /reviews\.map/);
  assert.match(page, /onReplyCreated=\{refreshVisibleReviews\}/);
  assert.match(page, /t\('shopReviews\.title'/);
  assert.match(page, /shopReviews\.loading/);
  assert.match(page, /shopReviews\.end/);
  assert.match(page, /loadingRef\.current/);
  assert.match(page, /requestSequence\.current/);
  assert.match(page, /Clear the previous route's rows/);
  assert.match(page, /resolvedShopName && resolvedShopName\.shopId === id/);
  assert.match(page, /underfillAttemptLength\.current === reviews\.length/);
  assert.match(page, /matchMedia\('\(min-width: 1024px\)'\)\.matches/);
  assert.match(page, /catch \{[\s\S]*?underfillAttemptLength\.current = null;/s);
  assert.match(page, /new ResizeObserver\(fillUnderfilledViewport\)/);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.scroll\s*\{[^}]*width:\s*min\(860px,/s);
  assert.doesNotMatch(styles, /@media \(min-width: 1024px\)[\s\S]*?\.scroll\s*\{[^}]*grid-template-columns:/s);
});

test('review thread retains recursive actions and caps deep desktop indentation', () => {
  const thread = readSource('../src/components/ReviewThread/index.tsx');
  const styles = readSource('../src/components/ReviewThread/ReviewThread.module.css');

  assert.match(thread, /translateReview\(review\.id/);
  assert.match(thread, /toggleShopReviewLike\(review\.id\)/);
  assert.match(thread, /parentId:\s*review\.id/);
  assert.match(thread, /shopId && depth < 2/);
  assert.match(thread, /\(review\.children \?\? \[\]\)\.map/);
  assert.match(thread, /nestingDepth=\{visualDepth \+ 1\}/);
  assert.match(thread, /compact \? styles\.compact/);
  assert.match(thread, /await onReplyCreated\?\.\(\);[\s\S]*?Toast\.show\(\{ icon: 'success'/s);
  assert.match(styles, /\.children\s*\{[^}]*margin-left:\s*28px;/s);
  assert.match(styles, /@media \(max-width: 390px\)/);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.footer\s*\{[^}]*flex-wrap:\s*wrap;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.compact \.content\s*\{[^}]*font-size:\s*13px;/s);
  assert.match(styles, /\.thread\[data-depth='2'\] > \.children\s*\{[^}]*margin-left:\s*0;[^}]*border-left:\s*0;/s);
});

test('blog detail uses a wide side rail without moving the mobile content order', () => {
  const page = readSource('../src/pages/BlogDetail/index.tsx');
  const styles = readSource('../src/pages/BlogDetail/BlogDetail.module.css');
  const swiperStyles = readSource('../src/components/ImageSwiper/ImageSwiper.module.css');

  assert.match(page, /styles\.detailLayout/);
  assert.match(page, /styles\.sideRail/);
  assert.match(page, /styles\.bottomFrame/);
  assert.match(page, /comments\.map\(\(c\) => renderComment\(c, 0\)\)/);
  assert.match(page, /c\.children\.map\(\(child\) => renderComment\(child, depth \+ 1\)\)/);
  assert.match(page, /parentId = replyTo\.parentId > 0 \? replyTo\.parentId : replyTo\.id/);
  assert.match(page, /answerId = replyTo\.id/);
  assert.match(page, /isChinese &&/);
  assert.match(page, /currentUser && currentUser\.id === blog\.userId/);
  assert.match(page, /followingLikes\.map/);
  assert.match(page, /const nextFollowed = !followed/);
  assert.match(page, /follow\(blog\.userId, nextFollowed\)/);
  assert.match(page, /if \(!blog \|\| !id\) return/);
  assert.match(page, /if \(followLockRef\.current === generation\) return/);
  assert.match(page, /if \(likeLockRef\.current === generation\) return/);
  assert.match(page, /commentTranslationLocksRef\.current\.get\(comment\.id\) === generation/);
  assert.match(page, /const routeGenerationRef = useRef\(0\)/);
  assert.match(page, /setError\(null\)/);
  assert.match(page, /likeBlog\(blog\.id\)/);
  assert.match(page, /navigator\.share/);
  assert.match(page, /deleteBlog\(blog\.id\)/);
  assert.match(page, /createBlogComment\(\{ blogId: Number\(routeId\), content: commentText\.trim\(\) \}\)/);
  assert.match(page, /deleteBlogComment\(c\.id\)/);
  assert.match(page, /onKeyDown=\{\(e\) => \{ if \(e\.key === 'Enter'\) handleCommentSubmit\(\); \}\}/);
  assertInOrder(page, [
    'styles.imageCard',
    'styles.contentCard',
    'styles.shopBasic',
    'styles.zanBox',
    'styles.comments',
    'styles.bottomFrame',
  ]);
  assert.match(styles, /\.detailLayout,[\s\S]*?\.bottomFrame\s*\{[^}]*display:\s*contents;/s);
  assert.match(styles, /@media \(min-width: 1024px\)[\s\S]*?\.detailLayout\s*\{[^}]*width:\s*min\(820px,/s);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*?\.detailLayout\s*\{[^}]*grid-template-columns:\s*minmax\(0, 820px\) minmax\(280px, 320px\)/s);
  assert.match(styles, /@media \(min-width: 1280px\)[\s\S]*?\.bottomSticky\s*\{[^}]*grid-column:\s*1;/s);
  assert.match(styles, /\.commentActionGroup\s*\{[^}]*flex-wrap:\s*wrap;/s);
  assert.match(swiperStyles, /@media \(min-width: 1024px\)[\s\S]*?height:\s*clamp\(360px, 42vw, 480px\)/s);
});
