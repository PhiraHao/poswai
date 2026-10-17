# Songwai order handoff for restaurant 37

The companion `songwai-poswai-bridge.js` runs in Songwai's Node service. It is
disabled unless `SONGWAI_POSWAI_SECRET` has at least 32 characters. Use the
same value as POS WAI's `SONGWAI_WEBHOOK_SECRET`. Never put it in browser code.

Copy the module to Songwai's `lib/poswaiBridge.js`. In `routes/orders.js`, after
loading `db`, create the bridge once:

```js
const { createBridge } = require('../lib/poswaiBridge');
const poswaiBridge = createBridge(db);
```

Inside the existing `POST /api/order` SQLite transaction, after inserting the
normalized `order_items` and before `COMMIT`, enqueue only restaurant 37:

```js
if (Number(restaurant_id) === 37) {
  poswaiBridge.enqueue({
    order_id: Number(orderId), restaurant_id: 37, user_id: Number(user_id) || null,
    delivery_mode: deliveryMode, customer_name: recipName || '',
    contact_phone: resolvedContact || '', payment_status: 'pending',
    items: items.map(i => ({ menu_id: Number(i.id), qty: Number(i.qty) })),
  });
}
```

After `COMMIT`, call `poswaiBridge.flush().catch(() => {})`; the background
timer also retries failed deliveries. The queue must use Songwai's persistent
SQLite database. An order is acknowledged only after POS WAI returns HTTP 200.
Repeated attempts keep the same Songwai order ID and are idempotent in POS WAI.
Do not set `payment_status: 'paid'` merely because a payment method was selected;
send a separate verified payment event or confirm it at the POS cashier.

Before enabling the secret, enter real POS WAI menu/BOM/stock and activate the
eight mapped items, deploy both services, verify a signed order end to end, and
turn off POS WAI preview mode only after the full checkout has passed. Songwai
currently creates rider and postal orders; customer self pickup is handled by
POS WAI's LINE LIFF flow until Songwai's checkout has a pickup choice and
server validation for it. The bridge does not invent partner API access for
GrabFood, LINE MAN, ShopeeFood, or TikTok Shop.
