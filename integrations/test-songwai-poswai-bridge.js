'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { createHmac } = require('node:crypto');
const { createBridge, signedHeaders } = require('./songwai-poswai-bridge');

function fakeDb() {
  const rows = new Map();
  return {
    rows,
    exec() {},
    prepare(sql) {
      if (sql.startsWith('INSERT')) return { run(id, body) { if (!rows.has(id)) rows.set(id, { order_id:id, body, attempts:0, next_attempt_at:0, delivered_at:null }); } };
      if (sql.startsWith('SELECT')) return { all(now) { return [...rows.values()].filter(row => !row.delivered_at && row.next_attempt_at <= now); } };
      if (sql.includes('SET delivered_at')) return { run(now, id) { rows.get(id).delivered_at = now; } };
      return { run(next, error, id) { Object.assign(rows.get(id), { attempts:rows.get(id).attempts+1, next_attempt_at:next, last_error:error }); } };
    },
  };
}

test('signature matches POS WAI HMAC contract', () => {
  const body = '{"order_id":123}';
  const headers = signedHeaders('s'.repeat(40), body, 123456);
  const expected = createHmac('sha256', 's'.repeat(40)).update('123456.' + body).digest('hex');
  assert.equal(headers['X-Songwai-Signature'], 'sha256=' + expected);
});

test('disabled bridge does not queue orders', () => {
  const bridge = createBridge(fakeDb(), { secret:'' });
  assert.equal(bridge.enabled, false);
  assert.equal(bridge.enqueue({ order_id:1 }), false);
});

test('durable queue retries and never duplicates same order ID', async () => {
  const db = fakeDb();
  let calls = 0;
  const bridge = createBridge(db, { secret:'s'.repeat(40), allowTestEndpoint:true,
    endpoint:'https://example.test/order', fetch:async (_url, options) => {
      calls++;
      assert.equal(JSON.parse(options.body).restaurant_id, 37);
      return { ok:true, status:200 };
    } });
  const order = { order_id:123, restaurant_id:37, delivery_mode:'rider', items:[{ menu_id:480, qty:2 }] };
  assert.equal(bridge.enqueue(order), true);
  assert.equal(bridge.enqueue(order), true);
  assert.equal(db.rows.size, 1);
  assert.equal((await bridge.flush()).sent, 1);
  assert.equal((await bridge.flush()).sent, 0);
  assert.equal(calls, 1);
  bridge.stop();
});

test('failed delivery remains queued with backoff', async () => {
  const db = fakeDb();
  const bridge = createBridge(db, { secret:'s'.repeat(40), allowTestEndpoint:true,
    endpoint:'https://example.test/order', fetch:async () => ({ ok:false, status:503 }) });
  bridge.enqueue({ order_id:124, restaurant_id:37, delivery_mode:'pickup', items:[{ menu_id:481, qty:1 }] });
  assert.equal((await bridge.flush()).sent, 0);
  assert.equal(db.rows.get(124).attempts, 1);
  assert.equal(db.rows.get(124).delivered_at, null);
  assert.ok(db.rows.get(124).next_attempt_at > Math.floor(Date.now() / 1000));
  bridge.stop();
});
