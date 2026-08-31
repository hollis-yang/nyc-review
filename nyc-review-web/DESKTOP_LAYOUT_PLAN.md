# NYC Review desktop layout plan

Status: Phase 3 complete
Baseline: `b379b86` (`feat: add account security and check-in calendar`)
Phase 1 commit: `3f26310` (`feat(web): add desktop shell and home layout`)
Phase 2 commit: `52e39f2` (`feat(web): add desktop discovery layouts`)
Scope: the current 15 React page routes in `nyc-review-web/src/App.tsx`

## Goal and non-negotiable constraints

Create a desktop presentation for NYC Review without creating a second data or
business-logic implementation. The mobile presentation remains the default.
Desktop media queries and shared layout components may change placement,
spacing, width, scrolling, and interaction surfaces, but they must not change:

- routes, redirects, API calls, authorization rules, or data ordering;
- visible copy, internationalization keys, images, ratings, prices, addresses,
  reviews, vouchers, provenance, AI evidence, or approval states;
- loading, empty, error, submitting, success, signed-in, and signed-out states;
- the meaning of search, sort, infinite loading, like, follow, reply,
  translation, favorite, purchase, publish, map, and AI actions.

Content parity is defined by the current rendered UI and its reachable state
branches. Unused locale keys and dead CSS are not new desktop content.

## Current route inventory

Public pages:

- `/`
- `/login`
- `/register`
- `/forgot-password`
- `/shop-list`
- `/shop-detail/:id`
- `/shop-reviews/:id`
- `/blog-detail/:id`
- `/user/:id`
- `/map`
- `/ai`

Protected pages:

- `/blog-edit`
- `/profile`
- `/profile-edit`
- `/account-security`

`/login2` and the existing legacy `.html` redirects remain unchanged.

## Responsive foundation

- Below `768px`: preserve the current mobile layout.
- `768px` through `1023px`: centered, single-column tablet layout.
- `1024px` through `1279px`: compact desktop layout with an `80px` navigation
  rail.
- At `1280px` and above: expanded `216px` navigation rail and a 12-column
  content grid capped at `1280px`.
- At very wide viewports: cap the working canvas at `1440px` rather than
  stretching content indefinitely.
- Convert the existing bottom navigation to the desktop rail only on the seven
  pages that currently render `FootBar`: Home, Map, AI, My Profile, Profile
  Edit, Other Profile, and Account Security.
- Ordinary pages use one primary scroll surface. Independent scrolling is
  retained only where the feature requires it, such as the map, AI event log,
  suggestion lists, and modal result lists.

## Desktop page layouts

### Discovery

- Home: sticky search context bar, six-category adaptive row, and a note grid
  with three columns on compact desktop and four columns when space permits.
  Preserve note order and infinite loading.
- Shop list: persistent `240px` category panel, sticky sort controls, and one
  or two columns of the existing shop cards.
- Map: a vertical category rail on the left, with the map filling the remaining
  route viewport. Preserve mode, density, location, error, and popup behavior;
  do not add a shop-results list.

### Detail and social content

- Shop detail: 7:5 media/details split above an 8:4 reviews and
  hours/vouchers split. Preserve favorite, share, contact, navigation,
  purchase, review, reply, translation, and attribution behavior.
- Shop reviews: centered single reading column of about `860px`, retaining the
  recursive reply tree.
- Blog detail: an approximately `820px` article/comment column and, when space
  permits, a `320px` related-shop/engagement rail. Keep deep replies visible,
  allow action rows to wrap, and keep the comment composer attached only to
  the main column.
- Blog edit: approximately `760px` title/body editor plus a `320px` image and
  linked-shop panel. Present the current shop picker as a desktop dialog.

### AI and profiles

- AI workspace: centered intro/history/composer before a run; during a run,
  use an input/history rail and a work area for collaboration, candidates,
  selected-shop evidence, and approvals.
- My Profile: sticky `340px` profile/stat/activity column and a main panel for
  the selected one of nine sections: notes, followers, following, favorites,
  itineraries, vouchers, reminders, AI memory, and check-in.
- Check-in: a dedicated single-column calendar card with streak summary,
  month navigation, seven-column date grid, today action, and New York time
  note. Selecting the activity opens this panel; it does not check in directly.
- Other Profile: approximately `320px` profile rail plus the notes or mutual
  following content panel.

### Account and forms

- Profile Edit: a two-column settings layout capped near `960px`; Account
  Security stays a separate route rather than becoming an inline dialog.
- Account Security: full-width introduction followed by separate Recovery Key
  and Change Password cards. Stack them on compact desktop and place them side
  by side when enough width exists. Preserve configured/unconfigured status,
  validation, submitting states, and sign-out-after-password-change behavior.
- Login and Register: brand area and form area in a desktop two-column card.
  Keep the forgot-password link beside the password area and preserve agreement
  controls and redirect behavior.
- Forgot Password: no primary navigation; centered single-column form around
  `560px` with the current introduction, fields, rules, submission states, and
  return-to-login link. Do not add a wizard or promotional copy.

## Delivery phases

### Phase 1 — foundation and first meaningful preview

- Add shared desktop sizing and layout tokens.
- Add the responsive route shell and convert the existing `FootBar` into the
  desktop navigation rail at `1024px` and above.
- Complete the desktop Home layout: search context bar, category row, and
  three/four-column note grid.
- Preserve the current mobile Home layout and interactions.
- Compile and run the current static/unit contracts before handing off the
  first preview.

Completed in Phase 1 commit `3f26310`:

- responsive route shell and shared desktop sizing tokens;
- compact and expanded desktop modes for the existing primary navigation;
- desktop Home search, six-category row, and three/four-column note grid;
- underfilled-grid continuation for the existing infinite feed;
- static desktop layout contracts covering all routes, navigation actions,
  mobile layout invariants, and desktop grid invariants;
- production build, lint, 12 tests, and bilingual frontend contracts passing.

The existing `visual:audit` failure for repeated direct default-avatar fallback
references in `MyProfile/index.tsx` remains a recorded pre-Phase-1 baseline
issue; Phase 1 does not modify that file.

### Phase 2 — discovery surfaces

- Adapt shared note and shop cards.
- Implement Shop List and Map desktop layouts.

Completed in Phase 2:

- retained the Phase 1 desktop note-card grid and added a bounded `136x108px`
  desktop media column plus keyboard-native link semantics to the shared shop
  card, without adding or removing merchant fields;
- converted Shop List to a persistent `240px` category panel and a one/two
  column result grid while preserving the mobile category dropdown, sorting,
  geolocation fallback, loading, and empty states;
- retained the result list as the pagination scroll owner, added underfilled
  viewport continuation, and canceled/ignored superseded requests so rapid
  category or sort changes cannot mix result sets;
- converted Map to a `240px` desktop filter rail (`264px` on wide screens) and
  a separate map canvas, keeping all category, viewport URL, cluster, marker,
  popup, loading, error, empty, density, and locate behaviors;
- added Leaflet size invalidation when the responsive canvas changes and
  enlarged only the desktop popup presentation;
- added three discovery-specific desktop contracts; 15 static/unit tests,
  lint, production build, and bilingual frontend contracts pass.

The existing `visual:audit` failure for `MyProfile/index.tsx` is unchanged from
the Phase 1 baseline and remains outside this phase's discovery-surface scope.

### Phase 3 — detail and conversation surfaces

- Implement Shop Detail, Shop Reviews, Blog Detail, and the deep-comment tree.

Completed in Phase 3:

- converted Shop Detail to a `7:5` media/details grid above an `8:4`
  reviews/support grid while retaining every image, favorite/share/contact,
  navigation, hours, voucher, review, reply, translation, and purchase path;
- kept the merchant gallery horizontally reachable for arbitrary image counts
  and aligned the existing review composer with the desktop conversation card;
- centered Shop Reviews in an approximately `860px` reading column, added
  desktop-only underfilled-viewport continuation, and protected pagination and
  reply refreshes from stale result overwrites;
- enlarged non-compact and compact desktop review threads, allowed action rows
  to wrap, and capped visual indentation for deep descendants without changing
  the existing reply-depth rule or mobile recursion behavior;
- kept Blog Detail single-column at compact desktop widths and introduced the
  `820px` article/comments column plus `320px` sticky shop/engagement rail at
  `1280px`, with the existing composer and action bar aligned only to the main
  column;
- used `display: contents` for the new mobile wrappers so the existing mobile
  order remains image/details, support/engagement, comments, and composer;
- added four Phase 3 layout/content contracts; 19 static/unit tests, lint,
  production build, and bilingual frontend contracts pass.

The existing `visual:audit` failure for `MyProfile/index.tsx` remains the same
pre-Phase-1 baseline and is not part of the Phase 3 detail/conversation scope.

### Post-Phase 3 stabilization — Home feed and desktop navigation

- made Home's failed and empty first-load states visible and retryable instead
  of leaving a permanently blank desktop feed;
- de-duplicated adjacent hot-blog pages by note ID while preserving the first
  occurrence and existing ordering;
- stabilized the desktop feed's flex/grid scroll boundary with explicit minimum
  sizing and one clipped route viewport;
- replaced the desktop-only circular create control with the same navigation-row
  treatment as Home, Map, AI Guide, and Profile, using a note-edit icon and the
  existing localized label;
- retained the current circular plus action in the mobile bottom navigation.

### Phase 4 — profile and security surfaces

- Implement My Profile, the check-in calendar, Other Profile, Profile Edit,
  Account Security, Login, Register, and Forgot Password.

### Phase 5 — creation and AI surfaces

- Implement Blog Edit and AI Workspace desktop layouts and dialog behavior.

### Phase 6 — parity and release validation

- Complete bilingual, authentication, state, interaction, responsive, and
  build validation across all routes.

## Validation matrix

Viewport coverage:

- Mobile regression: `390x844`, `430x932`.
- Desktop: `1024x768`, `1280x800`, `1440x900`, `1920x1080`.
- Breakpoint-sensitive checks around the existing `390`, `480`, `640`, `700`,
  and `720px` rules plus the new `1024` and `1280px` desktop rules.

Feature coverage:

- English and Chinese.
- Signed-out and signed-in navigation.
- Loading, empty, error, submitting, and success states.
- Recovery key configured/unconfigured, validation failures, password reset,
  password change, forced sign-out, and return-login messages.
- Check-in loading/error, signed/unsigned today, month navigation, 28–31 day
  grids, checked/today markers, and New York date note.
- Comment depth 0, 1, and greater than 1 with long names/content and concurrent
  reply, AI translation, and delete actions.

Quality gates:

- `npm run lint`
- `npm test`
- `npm run build`
- `python3 -B scripts/quality/frontend_contracts.py`
- `npm run visual:audit` after resolving or explicitly updating its pre-existing
  My Profile default-avatar baseline
- mobile/desktop semantic-content parity checks and final responsive review
