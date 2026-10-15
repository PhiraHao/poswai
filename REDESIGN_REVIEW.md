# POS WAI redesign review — 2026-10-15

## Direction
Full yellow SongWai sidebar, white working surfaces, consistent line icons, Thai typography, shorter labels and progressive disclosure. Food uses local SVG icons as requested; photography is deferred.

## Page audit and changes
| Page | Main issue | Implemented |
|---|---|---|
| Ordering | Too many badges, controls and descriptions | Compact icon grid, short names, search/categories, cart quantity controls; secondary services/member fields collapsed |
| Kitchen | Dense cards, incorrect sample drink station | Summary counts, station lanes, clearer tickets; item station falls back to menu definition |
| Cashier | Shift/setup tools compete with payment | Table plan and payment split; shift, table setup and printing in disclosures |
| Inventory | All workflows mixed together | Ingredient/recipe/movement tabs, search, aligned table; selected recipe shown correctly |
| Members | Membership and delivery compete | Separate member and delivery tabs, search, channel cards |
| Staff | Long form and administrative details | Team/leave/commission/history tabs, compact team table, leave details on demand |
| Reports | Excessive explanatory text | Overview/menu/service tabs, three KPIs, concise charts; corrected margin label |

## Responsive checks
Browser viewport review: desktop, 1024×768 tablet landscape and 390×844 mobile. All seven pages inspected. Mobile uses bottom navigation and two-column catalog; tablet uses compact sidebar; desktop uses full yellow sidebar. Wide analytical tables scroll inside their panel. Fixed mobile catalog overflow and desktop header alignment. Physical-device testing remains outstanding.

## Functional checks
Menu filters and modifier selection; cart add and quantity total (65→130); inventory search and selected tea recipe; member search; staff tabs; report tabs. No browser console errors observed. Python compilation and JavaScript syntax checks passed. Static routes and PWA asset responses checked. Preview API write guard remains enabled; this review does not certify live payments or LINE production operation.

## Assets and offline
SVG food/drink/dessert icons are local. Noto Sans Thai font license included in assets/OFL.txt. Worker v14 caches redesign scripts/styles/fonts/icons. Preview remains read-only for server-side transactions.
