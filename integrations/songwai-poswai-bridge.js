'use strict';

// Install in the Songwai Node service. The caller enqueues inside its existing
// order transaction; the worker sends only after that transaction commits.
const { createHmac } = require('node:crypto');

const DEFAULT_ENDPOINT = 'https://poswai.zzaxstudio.com/api/integrations/songwai/orders';

function signedHeaders(secret, body, timestamp = Math.floor(Date.now() / 1000)) {
  const stamp = String(timestamp);
  const digest = createHmac('sha256', secret).update(`${stamp}.${body}`).digest('hex');
  return {
    'Content-Type': 'application/json',
    'X-Songwai-Timestamp': stamp,
    'X-Songwai-Signature': `sha256=${digest}`,
  };
}

function createBridge(db, options = {}) {
  const secret = options.secret || process.env.SONGWAI_POSWAI_SECRET || '';
  const endpoint = options.endpoint || DEFAULT_ENDPOINT;
  const restaurantId = Number(options.restaurantId || 37);
  const fetchImpl = options.fetch || globalThis.fetch;
  const enabled = secret.length >= 32 && restaurantId === 37;
  if (!enabled) {
    return { enabled: false, enqueue: () => false, flush: async () => ({ sent: 0, pending: 0 }) };
  }
  if (endpoint !== DEFAULT_ENDPOINT && !options.allowTestEndpoint) {
    throw new Error('Songwai POS WAI endpoint must use the official HTTPS hostname');
  }
  db.exec(`CREATE TABLE IF NOT EXISTS poswai_order_outbox (
    order_id INTEGER PRIMARY KEY,
    body TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    delivered_at INTEGER,
    last_error TEXT
  )`);
  const insert = db.prepare('INSERT OR IGNORE INTO poswai_order_outbox(order_id,body) VALUES(?,?)');
  const pending = db.prepare('SELECT order_id,body,attempts FROM poswai_order_outbox WHERE delivered_at IS NULL AND next_attempt_at<=? ORDER BY order_id LIMIT 20');
  const delivered = db.prepare('UPDATE poswai_order_outbox SET delivered_at=?,last_error=NULL WHERE order_id=?');
  const retry = db.prepare('UPDATE poswai_order_outbox SET attempts=attempts+1,next_attempt_at=?,last_error=? WHERE order_id=?');
  let running = false;

  function enqueue(order) {
    if (Number(order.restaurant_id) !== restaurantId || !['rider', 'pickup'].includes(order.delivery_mode)) return false;
    if (!Number.isInteger(order.order_id) || order.order_id < 1 || !Array.isArray(order.items) || !order.items.length) {
      throw new Error('Invalid Songwai order for POS WAI');
    }
    const body = JSON.stringify({
      order_id: order.order_id,
      restaurant_id: restaurantId,
      user_id: order.user_id || null,
      delivery_mode: order.delivery_mode,
      customer_name: String(order.customer_name || '').slice(0, 100),
      contact_phone: String(order.contact_phone || '').slice(0, 30),
      payment_status: order.payment_status === 'paid' ? 'paid' : 'pending',
      items: order.items.map(item => ({ menu_id: Number(item.menu_id), qty: Number(item.qty) })),
    });
    insert.run(order.order_id, body);
    return true;
  }

  async function flush() {
    if (running) return { sent: 0, pending: 0 };
    running = true;
    let sent = 0;
    try {
      const rows = pending.all(Math.floor(Date.now() / 1000));
      for (const row of rows) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 8000);
        try {
          const response = await fetchImpl(endpoint, {
            method: 'POST', headers: signedHeaders(secret, row.body),
            body: row.body, signal: controller.signal,
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          delivered.run(Math.floor(Date.now() / 1000), row.order_id);
          sent++;
        } catch (error) {
          const wait = Math.min(3600, 15 * 2 ** Math.min(row.attempts, 8));
          retry.run(Math.floor(Date.now() / 1000) + wait, String(error.message).slice(0, 100), row.order_id);
        } finally { clearTimeout(timer); }
      }
      return { sent, pending: rows.length - sent };
    } finally { running = false; }
  }
  const interval = setInterval(() => { flush().catch(() => {}); }, 30000);
  interval.unref?.();
  return { enabled: true, enqueue, flush, stop: () => clearInterval(interval) };
}

module.exports = { createBridge, signedHeaders };
