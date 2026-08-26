import {
  P13_CONTEXTUAL_ASSET_URLS,
  P13_MERCHANT_PRIMARY_URLS,
  P13_MERCHANT_SPECIFIC_SHOP_IDS,
  P13_SHOP_VISUAL_ASSIGNMENTS,
} from '../generated/merchantVisualManifest';

export type VisualKind = 'merchant' | 'note';

export interface MerchantVisualIdentity {
  shopId?: number | null;
  name?: string | null;
  typeId?: number | null;
  images?: string | string[] | null;
  trustProvided?: boolean;
  kind?: VisualKind;
  seedId?: number | string | null;
}

const merchantSpecificShopIds = new Set<number>(P13_MERCHANT_SPECIFIC_SHOP_IDS);
const DEFAULT_IMAGE_MARKERS = [
  '/imgs/icons/default-icon.png',
  '/imgs/icons/icon1.jpg',
  '/imgs/blogs/blog1.jpg',
  'default-icon.png',
  'no-product',
  'no_image',
  'no-image',
  'placeholder',
  'hugedomains',
  'waitingroom',
  'og-default',
  'logo',
];

const PALETTES = [
  ['#ff6338', '#ff9b67', '#5f2618'],
  ['#c67838', '#f2c66d', '#573316'],
  ['#8f3f68', '#e796ad', '#4a1f36'],
  ['#326e83', '#6fc1cb', '#173c4a'],
  ['#43845b', '#8bc97f', '#1c4931'],
  ['#9a557e', '#e29ebd', '#4f2942'],
] as const;

const TYPE_LABELS = ['DINING', 'CAFE', 'NIGHT', 'EXPLORE', 'WELLNESS', 'BEAUTY'] as const;

export function splitVisualUrls(value?: string | string[] | null): string[] {
  const values = Array.isArray(value) ? value : String(value || '').split(',');
  return values.map((item) => item.trim()).filter(isUsableVisualUrl);
}

export function isUsableVisualUrl(value?: string | null): value is string {
  if (!value || !value.trim()) return false;
  const normalized = value.trim().toLowerCase();
  return !DEFAULT_IMAGE_MARKERS.some((marker) => normalized.includes(marker.toLowerCase()));
}

export function hasMerchantSpecificVisual(shopId?: number | null): boolean {
  return typeof shopId === 'number' && merchantSpecificShopIds.has(shopId);
}

function assignmentFor(shopId?: number | null): readonly [number, number] | undefined {
  if (typeof shopId !== 'number') return undefined;
  return P13_SHOP_VISUAL_ASSIGNMENTS[shopId];
}

function unique(values: Array<string | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}

export function buildMerchantVisualCandidates(identity: MerchantVisualIdentity): string[] {
  const shopId = typeof identity.shopId === 'number' ? identity.shopId : undefined;
  const assignment = assignmentFor(shopId);
  const exact = hasMerchantSpecificVisual(shopId);
  const provided = splitVisualUrls(identity.images);
  const acceptProvided = Boolean(identity.trustProvided || exact || !assignment);
  const contextual = assignment ? P13_CONTEXTUAL_ASSET_URLS[assignment[0]] : undefined;
  const typeId = identity.typeId || assignment?.[1] || 1;
  const primaryCandidate = shopId == null ? undefined : P13_MERCHANT_PRIMARY_URLS[shopId];
  const primary = isUsableVisualUrl(primaryCandidate) ? primaryCandidate : undefined;
  const procedural = proceduralVisualUrl({
    id: identity.seedId ?? shopId ?? identity.name ?? 'merchant',
    name: identity.name || 'NYC Local',
    typeId,
    kind: identity.kind || 'merchant',
  });

  return unique([
    ...(acceptProvided ? provided : []),
    exact ? primary : undefined,
    contextual,
    procedural,
  ]);
}

export function buildNoteVisualCandidates(input: {
  blogId: number;
  shopId?: number | null;
  shopName?: string | null;
  typeId?: number | null;
  images?: string | string[] | null;
  sourceType?: string | null;
}): string[] {
  const trustProvided = input.sourceType !== 'SYNTHETIC';
  const merchantCandidates = buildMerchantVisualCandidates({
    shopId: input.shopId,
    name: input.shopName || 'NYC Note',
    typeId: input.typeId,
    images: input.images,
    trustProvided,
    kind: 'note',
    seedId: input.blogId,
  });
  const noteCover = proceduralVisualUrl({
    id: `note:${input.blogId}`,
    name: input.shopName || 'NYC Note',
    typeId: input.typeId || assignmentFor(input.shopId)?.[1] || 1,
    kind: 'note',
  });
  return unique([...merchantCandidates, noteCover]);
}

function hashSeed(value: number | string): number {
  const text = String(value);
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function xml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return 'NY';
  return words.slice(0, 2).map((word) => word[0]).join('').toUpperCase();
}

export function proceduralVisualUrl(input: {
  id: number | string;
  name: string;
  typeId: number;
  kind: VisualKind;
}): string {
  const seed = hashSeed(input.id);
  const typeIndex = Math.max(0, Math.min(PALETTES.length - 1, (input.typeId || 1) - 1));
  const [start, end, ink] = PALETTES[typeIndex];
  const angle = 18 + (seed % 48);
  const circleX = 50 + (seed % 540);
  const circleY = 35 + ((seed >>> 5) % 250);
  const mark = xml(initials(input.name));
  const label = input.kind === 'note' ? 'NYC NOTE' : TYPE_LABELS[typeIndex];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 480">
    <defs>
      <linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="${start}"/><stop offset="1" stop-color="${end}"/></linearGradient>
      <pattern id="p" width="52" height="52" patternUnits="userSpaceOnUse" patternTransform="rotate(${angle})"><path d="M0 4h52" stroke="#fff" stroke-opacity=".14" stroke-width="8"/></pattern>
    </defs>
    <rect width="720" height="480" rx="28" fill="url(#g)"/>
    <rect width="720" height="480" rx="28" fill="url(#p)"/>
    <circle cx="${circleX}" cy="${circleY}" r="154" fill="#fff" fill-opacity=".12"/>
    <circle cx="${(circleX + 360) % 720}" cy="${(circleY + 245) % 480}" r="94" fill="${ink}" fill-opacity=".12"/>
    <path d="M72 348h576" stroke="#fff" stroke-opacity=".35" stroke-width="2"/>
    <text x="72" y="310" fill="#fff" font-family="Arial,Helvetica,sans-serif" font-size="132" font-weight="800" letter-spacing="-7">${mark}</text>
    <text x="75" y="394" fill="#fff" fill-opacity=".94" font-family="Arial,Helvetica,sans-serif" font-size="28" font-weight="700" letter-spacing="5">${label}</text>
    <text x="75" y="432" fill="#fff" fill-opacity=".72" font-family="Arial,Helvetica,sans-serif" font-size="18" letter-spacing="2">NEW YORK CITY</text>
  </svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}
