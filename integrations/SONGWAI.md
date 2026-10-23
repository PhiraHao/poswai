# Songwai order handoff

Songwai (songwai.online) pushes its delivery and self-pickup orders into the
POS WAI kitchen, so a shop that already runs POS WAI does not have to watch two
screens. Songwai's Telegram card still goes out for every order — this is an
extra channel, not a replacement.

`songwai-poswai-bridge.js` in this folder is the original single-restaurant
sketch, kept for reference. The implementation that actually runs lives in
Songwai's repository at `lib/poswaiBridge.js`, is wired into
`routes/orders.js`, and is covered by `scripts/test-poswai-bridge.js`.

## What crosses the wire

Only `menu_id` and `qty`, plus the customer name, phone, fulfillment mode and
the Songwai order ID. **Prices and menu text are never synced** — the shop owner
sets them separately on each side (owner's decision, 23 Oct 2026). POS WAI
resolves each `menu_id` through `songwai_menu_map` into its own catalog item and
charges its own price. `payment_status` is only ever `paid` once Songwai has
verified the money; a chosen payment method alone stays `pending`.

## One secret, one link per shop

POS WAI runs many shops, each with its own SQLite database, selected by the
`?shop=<slug>` query parameter. The integration therefore has two levels:

| Setting | Where | Scope |
| --- | --- | --- |
| `SONGWAI_WEBHOOK_SECRET` | POS WAI env | whole server |
| `SONGWAI_POSWAI_SECRET` | Songwai env | whole server (must equal the above, ≥32 chars) |
| Songwai restaurant ID | POS WAI, per shop, in `songwai_link` | one shop |
| POS WAI shop slug | Songwai, per restaurant, in `restaurants.poswai_shop` | one shop |

`SONGWAI_RESTAURANT_ID` is still read, but only as a fallback for the `main`
shop, so the pilot shop keeps working without being re-linked.

### POS WAI side (the shop owner)

In the online-orders screen, above the Songwai menu pairing list, enter the
shop's own restaurant number in Songwai and press **ผูกร้าน**. That writes
`songwai_link` in this shop's database, and the Songwai menu then loads so each
item can be paired with a POS WAI item. Re-linking to a different restaurant
deletes the old pairings, because those menu IDs belonged to the old restaurant
and would otherwise send the wrong dish to the pass.

API equivalents, for a manager or owner session:

```
GET  /api/integrations/songwai/link?branch_id=1
PUT  /api/integrations/songwai/link   {"branch_id": 1, "restaurant_id": 101}
```

`GET` also reports `secret_ready`, so a shop can see that the server-wide
secret is missing instead of waiting for orders that never arrive.

### Songwai side (ZZAX Studio admin)

In the admin shop form, tick **ส่งออเดอร์เข้าครัว POS WAI** and fill in the POS
WAI shop slug (`a-z`, `0-9`, `-`, up to 40 characters). Leaving it blank targets
POS WAI's `main` shop. The slug is stored lowercase and validated on write; a
malformed slug stops the bridge for that restaurant rather than guessing.

## Why the slug is signed

The bridge sends the slug both in the URL and inside the signed JSON body, and
POS WAI rejects the order when the two disagree. Without that, anyone who
captured a signed order had five minutes to replay it into another shop's
kitchen by changing `?shop=`.

A mismatch between the order's `restaurant_id` and the shop's linked restaurant
is a `403`, which the bridge treats as permanent and stops retrying — it means a
configuration mistake, not a transient failure. An unmapped menu item is a
`409`, which keeps retrying, so pairing the item later lets the order through on
its own. An order is acknowledged only after POS WAI returns HTTP 200, and
repeated attempts keep the same Songwai order ID, which POS WAI treats as
idempotent.

## LINE alert

When a Songwai order lands, POS WAI queues a LINE push to every active staff
member of that shop who has a `line_user_id` and whose role is owner, manager,
kitchen or cashier. The message is queued inside the same transaction as the
order, so a LINE outage cannot lose it, and `_line_outbox_worker` retries every
minute. The queue key is `online-order:<order_no>` per recipient, so a repeated
delivery of the same Songwai order never pushes twice.

## Go-live checklist

1. Set the shared secret on both services (≥32 characters, never in browser code).
2. Enter real menu, BOM and stock in POS WAI and activate the items.
3. Link the shop to its Songwai restaurant, then pair every menu item.
4. Add `line_user_id` for the staff who should be notified.
5. Turn the restaurant on in Songwai's admin form with the right slug.
6. Send one real order end to end before leaving preview mode.

Songwai creates rider, self-pickup and postal orders; postal orders never reach
the kitchen. The bridge does not invent partner API access for GrabFood,
LINE MAN, ShopeeFood or TikTok Shop.
