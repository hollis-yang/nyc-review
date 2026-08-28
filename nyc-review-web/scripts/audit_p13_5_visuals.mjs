#!/usr/bin/env node

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const dataset = resolve(root, '../data/generated/nyc-real-p13-full');
const readJson = (path) => JSON.parse(readFileSync(path, 'utf8'));
const shops = readJson(resolve(dataset, 'shops.json'));
const blogs = readJson(resolve(dataset, 'blogs.json'));
const images = readJson(resolve(dataset, 'shop_images.json'));
const credits = readJson(resolve(root, 'public/merchant-visuals/credits.json'));
const manifestSource = readFileSync(resolve(root, 'src/generated/merchantVisualManifest.ts'), 'utf8');

function parseGeneratedJson(name) {
  const expression = new RegExp(`${name}[^=]*= ([^;]+);`);
  const match = manifestSource.match(expression);
  if (!match) throw new Error(`Missing generated constant ${name}`);
  return JSON.parse(match[1].replace(/ as const$/, ''));
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const exactIds = new Set(parseGeneratedJson('P13_MERCHANT_SPECIFIC_SHOP_IDS'));
const assetUrls = parseGeneratedJson('P13_CONTEXTUAL_ASSET_URLS');
const assignments = parseGeneratedJson('P13_SHOP_VISUAL_ASSIGNMENTS');
const exactFromDataset = new Set(
  images
    .filter((image) => image.imageType === 'MERCHANT_SPECIFIC' && image.availabilityStatus === 'AVAILABLE')
    .map((image) => image.shopId),
);

assert(shops.length === 5000, `Expected 5,000 P13 shops, received ${shops.length}`);
assert(exactIds.size === exactFromDataset.size, 'Generated exact-image IDs do not match the P13 dataset');
assert(exactIds.size >= 1906, `Merchant-specific coverage regressed to ${exactIds.size}`);
assert(assetUrls.length === credits.assets.length, 'Credits and contextual URL counts differ');
assert(assetUrls.length >= 207, `Only ${assetUrls.length} contextual assets; at least 207 are required for max reuse 15`);

const allowedLicense = /^(CC0|CC BY|CC-BY|Public domain|PDM)/;
for (const asset of credits.assets) {
  assert(asset.sourceName === 'Wikimedia Commons', `Unexpected image source: ${asset.sourceName}`);
  assert(asset.sourceUrl && asset.licenseUrl && asset.attribution, `Incomplete credit for ${asset.title}`);
  assert(allowedLicense.test(asset.licenseName), `Unsupported license ${asset.licenseName}`);
  assert(!/[-/]n[cd](?:[-/]|$)/i.test(`${asset.licenseName} ${asset.licenseUrl}`), `Restricted license ${asset.licenseName}`);
}

const missingReuse = new Map();
for (const shop of shops) {
  const assignment = assignments[String(shop.id)];
  assert(Array.isArray(assignment), `Missing frontend visual assignment for shop ${shop.id}`);
  assert(assetUrls[assignment[0]], `Invalid contextual asset index for shop ${shop.id}`);
  assert(assignment[1] === shop.typeId, `Type mismatch for shop ${shop.id}`);
  if (!exactIds.has(shop.id)) {
    missingReuse.set(assignment[0], (missingReuse.get(assignment[0]) || 0) + 1);
  }
}

const maximumReuse = Math.max(...missingReuse.values());
assert(maximumReuse <= 15, `A contextual image is assigned to ${maximumReuse} missing-image shops`);

const generatedBlogs = blogs.filter((blog) => blog.sourceType === 'SYNTHETIC');
for (const blog of generatedBlogs) {
  assert(assignments[String(blog.shopId)], `Generated note ${blog.id} has no merchant visual fallback`);
}

const allowedAvatarDefaults = {
  'src/components/ShopCard/index.tsx': 0,
  'src/components/BlogCard/index.tsx': 1,
  'src/components/FeedCard/index.tsx': 1,
  'src/components/ImageSwiper/index.tsx': 0,
  'src/pages/ShopDetail/index.tsx': 0,
  'src/pages/BlogDetail/index.tsx': 3,
  'src/pages/Map/index.tsx': 0,
  'src/pages/AiWorkspace/index.tsx': 0,
  'src/pages/MyProfile/index.tsx': 1,
  'src/pages/OtherProfile/index.tsx': 2,
};
for (const [entry, allowedCount] of Object.entries(allowedAvatarDefaults)) {
  const source = readFileSync(resolve(root, entry), 'utf8');
  const defaultCount = source.match(/\/imgs\/icons\/default-icon\.png/g)?.length || 0;
  assert(defaultCount <= allowedCount, `Direct merchant/note default-image fallback remains in ${entry}`);
}

assert(!manifestSource.includes('/w/api.php'), 'Runtime manifest must not call the Wikimedia search API');

const report = {
  status: 'ok',
  shops: shops.length,
  merchantSpecificShops: exactIds.size,
  merchantSpecificCoverage: exactIds.size / shops.length,
  contextualPhotoShops: shops.length - exactIds.size,
  photoBackedFrontendCoverage: 1,
  nonDefaultVisualCoverage: 1,
  generatedNotes: generatedBlogs.length,
  noteDefaultImageRate: 0,
  contextualAssets: assetUrls.length,
  maximumContextualReuseForMissingShops: maximumReuse,
  runtimeSearchApiRequests: 0,
  backendChangesRequired: false,
};

console.log(JSON.stringify(report, null, 2));
