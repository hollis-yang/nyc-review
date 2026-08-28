# P13.5 Frontend Visual Coverage Runbook

P13.5 is a frontend-only visual layer on top of the accepted P13 checkpoint
`nyc-real-v5-8b645404-m20260824`. It does not change merchant identity, MySQL,
Redis, Spring, Agent Service, Qdrant, RAG documents or evaluation inputs.

## Result and terminology

The two image metrics remain separate:

- **Merchant-specific photos:** 1,906/5,000 (38.12%). These are the existing
  P13 images matched to a merchant and this number is not inflated.
- **Photo-backed frontend visuals:** 5,000/5,000 (100%). The remaining 3,094
  shops receive a category/subcategory-matched contextual photo. A contextual
  photo is never represented as a photograph of that merchant.

The fixed contextual catalog currently contains 218 reusable Wikimedia Commons
thumbnails. Each carries source page, author, license and source hash metadata;
one contextual photo is assigned to no more than 15 missing-photo merchants.
Every shop also receives a deterministic SVG fallback derived from shop ID,
name and category, so a broken remote image never becomes the old default icon.

All 10,000 generated P13 notes resolve their visual in this order:

```text
valid user-uploaded note image
  → merchant-specific image when available
  → assigned contextual image
  → deterministic note cover
```

## Runtime integration

`MerchantVisual` and `NoteVisual` are the only merchant/note image fallback
components. They are used by shop lists and detail, Home notes, following and
profile notes, favorites, map popups, AI Guide results and note detail.

The compact assignment manifest is bundled with React. The browser does not
call Wikimedia/Openverse search APIs and does not make a per-shop metadata
request. Contextual thumbnails remain fixed remote Commons references because
Commons rejected automated bulk thumbnail downloads under its robot policy.
The final SVG fallback is generated locally without network access.

License attribution is available from Profile → Image credits and directly at
`/image-credits`. Inline merchant cards remain free of provenance labels.

## Acceptance

No database or RAG command is required. From the repository root:

```bash
cd nyc-review-web
npm run visual:audit
npm run build
```

The audit must report:

```text
shops:                                      5000
merchantSpecificShops:                     1906
photoBackedFrontendCoverage:               1
nonDefaultVisualCoverage:                  1
generatedNotes:                            10000
noteDefaultImageRate:                      0
maximumContextualReuseForMissingShops:     <= 15
runtimeSearchApiRequests:                  0
backendChangesRequired:                    false
```

Then inspect Home, one shop list, a missing-photo shop detail, a note detail,
Map shop popup, AI Guide results and Profile favorites/notes. Broken-image
fallback can be checked by temporarily blocking `upload.wikimedia.org`; cards
must switch to their deterministic covers rather than the default avatar icon.

## Optional catalog refresh

Catalog generation is intentionally not part of `npm run build`. A refresh
requires network access and rewrites only frontend assets and reports:

```bash
cd nyc-review-web
npm run visual:generate
npm run visual:audit
npm run build
```

Only Public Domain, CC0, CC BY and CC BY-SA images are accepted. NC, ND,
unknown-license, undersized, logo, icon, map, diagram and obvious unrelated
title matches are rejected. Commit the generated manifest, credits snapshot and
coverage report together so the accepted UI remains reproducible.
