/* The bridge between the POS WAI pages and the phone they now live on.
 *
 * In the browser these pages are served by the shop's server, so "/api/orders"
 * means that server and the session rides along in a cookie. In the app the very
 * same pages are files inside the app: "/api/orders" would mean the app itself,
 * and no cookie survives a cross-origin trip (iOS refuses one outright).
 *
 * This file closes that gap before any page script runs. It must load first.
 * Nothing else in the POS had to be rewritten for the app; that is the point.
 */
(() => {
  'use strict';

  // Before the first paint: app-shell.css styles only what carries this class,
  // so the web, which never loads this file, is never touched by it.
  document.documentElement.classList.add('poswai-app');
  /* App Store review asks things of the iPhone app that Play does not (no shop
     sign-up in the app, Sign in with Apple beside LINE and Google); those rules
     sit under html.poswai-ios so Android and the web keep working as they do. */
  if (window.Capacitor?.getPlatform?.() === 'ios') document.documentElement.classList.add('poswai-ios');

  const DEFAULT_SERVER = 'https://poswai.zzaxstudio.com';
  // Paths that mean the shop's server rather than a file this app ships.
  const REMOTE = ['/api/', '/menu-photos/', '/t/'];
  // The one endpoint whose answer is about the session itself.
  const SESSION_PATH = '/api/auth/session';
  const STORE = {
    server: 'poswai.app.server',
    staff: 'poswai.app.session',
    owner: 'poswai.app.owner',
    shop: 'poswai.app.shop',
  };

  /* localStorage, not the Preferences plugin: the first request happens before
     any async read could finish, and this origin belongs to the app alone. */
  const read = (key) => {
    try { return localStorage.getItem(key) || ''; } catch { return ''; }
  };
  const write = (key, value) => {
    try { value ? localStorage.setItem(key, value) : localStorage.removeItem(key); } catch { /* private mode */ }
  };

  const plugin = (name) => window.Capacitor?.Plugins?.[name];
  const native = () => Boolean(window.Capacitor?.isNativePlatform?.());
  const server = () => (read(STORE.server) || DEFAULT_SERVER).replace(/\/+$/, '');

  const app = {
    get server() { return server(); },
    get shop() { return read(STORE.shop); },
    get staffToken() { return read(STORE.staff); },
    get ownerToken() { return read(STORE.owner); },
  };

  // ------------------------------------------------------------------ the keys
  app.signedIn = () => Boolean(read(STORE.staff));

  app.keepStaff = (token) => {
    write(STORE.staff, token || '');
    // A new person at the till: the remembered "who is signed in" was someone else.
    app.forgetCache?.('/api/auth/session');
    app.forgetCache?.('/api/staff/me');
    app.forgetCache?.('/api/permissions');
  };
  app.keepOwner = (token) => write(STORE.owner, token || '');
  app.keepShop = (slug) => write(STORE.shop, slug || '');

  app.forget = () => {
    write(STORE.staff, '');
    write(STORE.owner, '');
    // A signed-out till must not answer "who is signed in" from memory.
    app.forgetCache?.();
  };

  /* Which shop this phone is working in. Every request says so, because the app
     has no cookie for the server to remember it by. */
  app.useShop = (slug) => {
    if (slug && slug !== app.shop) app.keepShop(slug);
  };

  // --------------------------------------------------------------- the requests
  const remote = (path) => REMOTE.some((prefix) => path.startsWith(prefix));

  /** Where a path the pages ask for actually lives. */
  app.resolve = (path) => {
    if (typeof path !== 'string' || !path.startsWith('/')) return path;
    if (!remote(path)) return path;                 // a file this app ships
    const url = new URL(server() + path);
    if (app.shop && !url.searchParams.has('shop')) url.searchParams.set('shop', app.shop);
    return url.toString();
  };

  const headers = (given) => {
    const sent = new Headers(given || {});
    sent.set('x-poswai-app', '1');
    if (app.staffToken) sent.set('x-poswai-session', app.staffToken);
    if (app.ownerToken) sent.set('x-poswai-owner', app.ownerToken);
    return sent;
  };

  const plainFetch = window.fetch.bind(window);

  /* Menu photos arrive in the data as rooted paths ("/menu-photos/shop/x.jpg")
     and go straight into an <img>. In the app that would ask the app itself
     for the photo — and the page's own fallback swaps in a placeholder the
     instant that fails, so a photo is never seen. Pointing those paths at the
     server as the data arrives fixes every place that shows one at once. */
  const PHOTO_PATH = /"\/(menu-photos\/)/g;
  const pointAtServer = async (reply) => {
    if (!(reply.headers.get('content-type') || '').includes('application/json')) return reply;
    const text = await reply.text();
    const fixed = text.includes('"/menu-photos/') ? text.replace(PHOTO_PATH, `"${server()}/$1`) : text;
    return new Response(fixed, {status: reply.status, statusText: reply.statusText, headers: reply.headers});
  };

  /* ---- the last answer, for when the shop's internet drops ----------------
     A till must open and keep selling with no connection. What it needs to
     show — the menu, the tables, the bills still open, who is signed in — is
     kept from the last time the server answered, and handed back when it
     cannot. Writes are not cached here: index.html queues those itself and
     sends them when the line comes back. */
  const CACHED = ['/api/config', '/api/auth/session', '/api/owner/session', '/api/menu', '/api/tables',
    '/api/orders', '/api/shop/settings', '/api/permissions', '/api/staff/me', '/api/kds'];
  const CACHE_PREFIX = 'poswai.app.cache:';
  const CACHE_LIMIT = 400 * 1024;     // a menu with photos is a few kB of text; reports are not cached
  const cacheKey = (path) => `${CACHE_PREFIX}${app.shop}:${path}`;
  const cacheable = (path, init) => (!init?.method || init.method.toUpperCase() === 'GET')
    && CACHED.some((prefix) => path === prefix || path.startsWith(`${prefix}?`) || path.startsWith(`${prefix}/`));

  const remembered = (path) => {
    const text = read(cacheKey(path));
    if (!text) return null;
    return new Response(text, {status: 200, headers: {'content-type': 'application/json', 'x-poswai-offline': '1'}});
  };
  const keep = async (path, reply) => {
    if (!reply.ok) return reply;
    const text = await reply.clone().text();
    if (text.length <= CACHE_LIMIT) write(cacheKey(path), text);
    return reply;
  };

  /** Drop remembered answers: all of them, or those for one path. */
  app.forgetCache = (path) => {
    try {
      for (const key of Object.keys(localStorage)) {
        if (!key.startsWith(CACHE_PREFIX)) continue;
        if (!path || key.split(':').slice(2).join(':').startsWith(path)) localStorage.removeItem(key);
      }
    } catch { /* */ }
  };

  /** Bills just paid on the server leave the remembered list of open bills. */
  app.dropClosedOrders = (orderNos) => {
    try {
      for (const key of Object.keys(localStorage)) {
        if (!key.startsWith(`${CACHE_PREFIX}${app.shop}:/api/orders?`)) continue;
        const body = JSON.parse(localStorage.getItem(key));
        if (!Array.isArray(body?.orders)) continue;
        body.orders = body.orders.filter((order) => !orderNos.includes(order.order_no));
        localStorage.setItem(key, JSON.stringify(body));
      }
    } catch { /* the next fresh answer replaces it anyway */ }
  };

  window.fetch = (input, init) => {
    const path = typeof input === 'string' ? input : input?.url;
    if (typeof path !== 'string' || !path.startsWith('/')) return plainFetch(input, init);
    const target = app.resolve(path);
    if (target === path) return plainFetch(input, init);   // local file, untouched
    const sent = {...(init || {}), headers: headers(init?.headers)};
    // No cookie to send and none to receive: the token in the header is the session.
    sent.credentials = 'omit';
    const offlineCopy = cacheable(path, init);
    // No connection at all: answer at once from what was kept, rather than wait to fail.
    if (offlineCopy && !navigator.onLine) {
      const copy = remembered(path);
      if (copy) return Promise.resolve(copy);
    }
    return plainFetch(target, sent).then(pointAtServer)
      .then((reply) => (offlineCopy ? keep(path, reply) : reply))
      .catch((error) => {
        // A network that is up but goes nowhere (shop Wi-Fi with no line out).
        const copy = offlineCopy && remembered(path);
        if (copy) return copy;
        /* No line out: say so in the shop's language. Pages print the message
           as they got it, and "Failed to fetch" means nothing at a till. */
        if (!navigator.onLine || /Failed to fetch|NetworkError|Load failed/i.test(String(error))) {
          throw Object.assign(new Error('ไม่มีอินเทอร์เน็ต · ส่วนนี้จะโหลดเมื่อต่อเน็ตอีกครั้ง'), {cause: error, offline: true});
        }
        throw error;
      })
      .then((reply) => {
      /* A session the server has closed is gone here too, or the app would keep
         showing a shop it can no longer read. Only the session endpoint speaks
         for the session, though: plenty of others answer 401 for reasons of
         their own — a customer's table order, a till reading something its role
         may not — and a shop must never be signed out because one of those
         said no. */
      if (reply.status === 401 && path.startsWith(SESSION_PATH) && app.staffToken) {
        app.onSignedOut?.();
      }
      // Signing out drops the token and the remembered answers with it.
      if (reply.ok && path.startsWith('/api/auth/logout')) app.forget();
      return reply;
    });
  };

  /* Menu photos come from the server with a rooted path, and the pages put that
     path straight into an <img>. Rather than hunt down every such place, let the
     one that fails ask the server instead. Local images never reach this. */
  document.addEventListener('error', (event) => {
    const image = event.target;
    if (!(image instanceof HTMLImageElement)) return;
    const source = image.getAttribute('src') || '';
    if (!source.startsWith('/') || !remote(source) || image.dataset.poswaiRetried) return;
    image.dataset.poswaiRetried = '1';
    image.src = app.resolve(source);
  }, true);

  // ------------------------------------------------------------ the sign-in hop
  const AUTH_LINK = 'poswai://auth';
  let waiting = null;

  /** Where a page wanted to navigate. Returns true when the app took it over. */
  app.go = (url) => {
    // Apple signs in with the phone's own sheet, not a browser tab.
    if (/^\/api\/(owner|staff)\/auth\/apple\/start/.test(url || '')) { app.appleSignIn(url); return true; }
    const owner = /^\/api\/owner\/auth\/([a-z]+)\/start/.exec(url || '');
    if (owner) { app.signInWith(owner[1]); return true; }
    // A member of staff with their own LINE or Google: the same tab-and-back hop.
    const staff = /^\/api\/staff\/auth\/[a-z]+\/start/.exec(url || '');
    if (staff) { app.openSignIn(url); return true; }
    const shop = /^\/\?shop=([^&]+)/.exec(url || '');
    if (shop) { app.enterShop(decodeURIComponent(shop[1])); return true; }
    if (url === '/') { app.reopen(); return true; }
    return false;
  };

  /* Google refuses a sign-in inside an app's own web view, and is right to: the
     page could read what is typed there. A real browser tab is the arrangement
     it does permit, and the server sends the finished session back to us over
     poswai://auth — a link only this app answers. */
  app.signInWith = (channel) => app.openSignIn(`/api/owner/auth/${channel}/start`);

  /** Open any of the server's sign-in starts in a real browser tab, marked as the app's. */
  app.openSignIn = async (path) => {
    const browser = plugin('Browser');
    const url = new URL(server() + path);
    url.searchParams.set('app', '1');
    if (app.shop && !url.searchParams.has('shop')) url.searchParams.set('shop', app.shop);
    if (!browser) { window.open(url.toString(), '_blank'); return; }
    waiting = path;
    await browser.open({url: url.toString(), presentationStyle: 'popover'});
  };

  const finishSignIn = (url) => {
    let handed;
    try { handed = new URL(url); } catch { return; }
    const got = handed.searchParams;
    plugin('Browser')?.close().catch(() => {});
    waiting = null;
    const failed = got.get('error');
    if (failed) { app.onSignInFailed?.(failed); return; }
    /* A staff sign-in: the page already knows how to say every outcome when
       it opens with ?staff= or ?staff_error=, so it is reopened with that. */
    if (got.has('staff') || got.has('staff_error')) {
      if (got.get('session')) app.keepStaff(got.get('session'));
      if (got.get('shop')) app.useShop(got.get('shop'));
      const outcome = got.has('staff') ? `staff=${got.get('staff')}` : `staff_error=${got.get('staff_error')}`;
      app.reopen(outcome);
      return;
    }
    const token = got.get('owner');
    if (!token) return;
    app.keepOwner(token);
    app.onSignedIn?.({outcome: got.get('outcome') || 'choose', shop: got.get('shop') || ''});
  };

  app.ios = () => window.Capacitor?.getPlatform?.() === 'ios';
  /** Sign in with Apple is offered only where Apple's own sheet exists. */
  app.appleReady = () => app.ios() && Boolean(plugin('AppleSignIn'));

  /* Sign in with Apple, start to finish inside the app. The server writes the
     state and nonce exactly as for LINE and Google; Apple's sheet signs a token
     carrying the nonce; the server checks it and answers with the same
     poswai://auth link a browser sign-in comes back with, so finishSignIn
     handles all of them. Starting with fetch, not a browser tab, is also what
     lets the session this app holds ride along when an account is being linked. */
  app.appleSignIn = async (path) => {
    const apple = plugin('AppleSignIn');
    if (!apple) { app.onSignInFailed?.('provider_unknown'); return; }
    try {
      const started = await fetch(path, {cache: 'no-store'});
      const handshake = await started.json().catch(() => ({}));
      if (!started.ok) throw new Error(handshake.detail || 'provider');
      const signed = await apple.authorize({nonce: handshake.nonce});
      const done = await fetch('/api/auth/apple/native', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({state: handshake.state, identity_token: signed.identityToken,
          name: [signed.givenName, signed.familyName].filter(Boolean).join(' ')}),
      });
      const result = await done.json().catch(() => ({}));
      if (!done.ok || !result.link) throw new Error(result.detail || 'provider');
      finishSignIn(result.link);
    } catch (error) {
      // Closing Apple's sheet is a choice, not a failure worth explaining.
      app.onSignInFailed?.(/cancel/i.test(String(error?.code || error?.message)) ? 'closed' : 'provider');
    }
  };

  plugin('App')?.addListener('appUrlOpen', ({url}) => {
    if (typeof url === 'string' && url.startsWith(AUTH_LINK)) finishSignIn(url);
  });

  /* The tab was closed without finishing. Say so rather than leave a spinner. */
  plugin('Browser')?.addListener('browserFinished', () => {
    if (waiting) { waiting = null; app.onSignInFailed?.('closed'); }
  });

  // -------------------------------------------------------------- opening a shop
  /* In the browser this is a page load on the shop's own address. Here the page
     is already loaded, so remember the shop and start it over. */
  app.enterShop = (slug) => {
    app.useShop(slug);
    app.reopen();
  };

  app.reopen = (query = '') => { window.location.replace(`index.html${query ? `?${query}` : ''}`); };

  /* A till that dims mid-order and asks for the phone's own code is a till the
     queue is waiting on. The screen stays up while this app is in front, and is
     released the moment it is not, so it never holds the phone awake in a pocket. */
  const awake = plugin('KeepAwake');
  if (awake) {
    awake.keepAwake().catch(() => {});
    plugin('App')?.addListener('appStateChange', ({isActive}) => {
      (isActive ? awake.keepAwake() : awake.allowSleep()).catch(() => {});
    });
  }

  app.native = native;
  window.POSWAI_APP = app;
})();
