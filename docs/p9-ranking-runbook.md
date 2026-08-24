# P9.1 Shop Ranking Runbook

P9.1 fixes the semantics of the three shop-list rankings without changing the
active dataset or requiring a database migration.

## Ranking contract

| UI option | API value | Scope | Meaning |
| --- | --- | --- | --- |
| Near me (distance from you) | `distance` | Whole category | Redis GEO distance from the browser location, in meters |
| Times Sq. (fallback distance) | `distance` | Whole category | Explicit fallback origin `(-73.9855, 40.7580)` when browser location is unavailable or denied |
| Popularity | `popularity` | Whole category | Damped platform activity: review volume, blog likes, sold count, favorites and non-cancelled/non-refunded voucher orders |
| Rating | `rating` | Whole category | Resolved `tb_shop.score`; review count is the first tie-break and shop ID is the stable final tie-break |

Legacy API values `comments` and `score` remain accepted and map to
`popularity` and `rating`. A blank sort value remains compatible with distance
sorting.

Popularity is deliberately separate from the merchant rating. The current
formula is:

```text
20 × ln(1 + review count)
+ 10 × ln(1 + blog likes)
+  5 × ln(1 + sold count)
+  5 × favorite count
+  3 × valid voucher order count
```

Voucher orders in cancelled, refunding or refunded states (`4`, `5`, `6`) do
not contribute. The score is calculated at query time and is not presented as
a merchant-supplied or external fact.

## Backend checks

Use a valid category ID. The first two calls should return globally ranked
pages while still attaching the distance from the supplied origin:

```bash
curl -sS 'http://127.0.0.1:8081/shop/of/type?typeId=1&current=1&sortBy=popularity&sortOrder=desc&x=-73.9855&y=40.7580'

curl -sS 'http://127.0.0.1:8081/shop/of/type?typeId=1&current=1&sortBy=rating&sortOrder=desc&x=-73.9855&y=40.7580'
```

Distance ranking uses Redis GEO and supports both global nearest-first and
farthest-first pagination:

```bash
curl -sS 'http://127.0.0.1:8081/shop/of/type?typeId=1&current=1&sortBy=distance&sortOrder=asc&x=-73.9855&y=40.7580'
```

Invalid or incomplete coordinates fail before Redis or MySQL access:

```bash
curl -sS 'http://127.0.0.1:8081/shop/of/type?typeId=1&current=1&sortBy=distance&sortOrder=asc&x=-73.9855'
```

## Frontend checks

1. Open a category from Home and allow browser location access. The active
   option must read `Near me` / `距你` and returned cards must show
   their distance from that location.
2. Deny location access or test in a browser without geolocation. The option
   must explicitly read `Times Sq.` / `距时代广场`.
3. Select Popularity and Rating. Page 2 must continue the global order rather
   than re-sorting a distance-preselected page.
4. Switch English/Chinese in Profile and repeat the label check.

The browser location is requested with a five-minute cache hint but is not
written to MySQL, Redis, local storage or the user profile.
