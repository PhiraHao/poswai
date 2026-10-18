/* Assemble the app's own copy of the POS WAI pages.
 *
 * The app ships the screens and asks the server only for data. That is the whole
 * difference between this and the shell that came before it: there is no page to
 * wait for, so the till opens the moment it is tapped and keeps working when the
 * shop's internet does not.
 *
 * One source of truth: every file here is copied from the web app next door, so
 * a fix made for the web reaches the app on the next build. Run `npm run build`.
 */
import {cp, mkdir, readFile, rm, writeFile} from 'node:fs/promises';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, '..');
const out = join(here, 'www');

/* Files the page needs but does not name in a tag the scan below can see. */
const LOOSE = ['manifest.json', 'icons.svg', 'icon-192.png', 'icon-512.png',
  'privacy.html', 'terms.html'];
// Proven against the shop's own POS58, so it is used as it stands.
const PRINTING = ['escpos.js', 'ble.js'];

/** Every stylesheet and script the page actually asks for, in its own words.
 *
 * Read from the page rather than listed here: a list gets out of step with the
 * page the moment someone adds a screen, and the way that fails — one missing
 * file in a till that has already opened — is the worst kind.
 */
function referenced(html) {
  const found = new Set();
  for (const [, path] of html.matchAll(/(?:href|src)="(\/[\w./-]+\.(?:css|js))(?:\?[^"]*)?"/g)) {
    if (!path.startsWith('/assets/')) found.add(path.slice(1));   // assets copy wholesale
  }
  return [...found];
}

/** The page, with the three things a served page assumes put right. */
async function page() {
  let html = await readFile(join(web, 'index.html'), 'utf8');

  // The app ships its files, so the cache-busting query a server needs is noise
  // here — and a filename with a query is one more thing to get wrong.
  html = html.replace(/(href|src)="(\/[\w./-]+)\?v=\d+"/g, '$1="$2"');

  /* A service worker caches what a server sent. These files came with the app,
     so it would add nothing but a second, staler copy of them. */
  html = html.replace('if ("serviceWorker" in navigator) {', 'if (false) {');

  // First script on the page: everything after it assumes the bridge is there.
  const bridge = '  <script src="/app-bridge.js"></script>\n';
  const head = html.indexOf('  <link rel="stylesheet" href="/ui.css">');
  if (head < 0) throw new Error('index.html changed shape: no stylesheet block to anchor to');
  html = html.slice(0, head) + bridge + html.slice(head);
  return html;
}

const html = await page();

await rm(out, {recursive: true, force: true});
await mkdir(out, {recursive: true});
await mkdir(join(out, 'print'), {recursive: true});

await writeFile(join(out, 'index.html'), html, 'utf8');
await cp(join(here, 'src', 'app-bridge.js'), join(out, 'app-bridge.js'));
await cp(join(web, 'assets'), join(out, 'assets'), {recursive: true});

// The policy pages carry their own stylesheet, and the app links to them from
// its sign-up form, so scan them the same way rather than naming the file here.
const legal = await Promise.all(LOOSE.filter((name) => name.endsWith('.html'))
  .map((name) => readFile(join(web, name), 'utf8')));

const copies = [
  ...referenced(html + legal.join('')).filter((name) => name !== 'app-bridge.js')
    .map((name) => [join(web, name), name]),
  ...LOOSE.map((name) => [join(web, name), name]),
  // Under print/, the path the pages already import them by on the web.
  ...PRINTING.map((name) => [join(web, 'print-app', 'www', name), join('print', name)]),
];
/* The server answers /privacy and /terms as routes of their own; the app has
   the two files, so the links the pages carry point at them instead. */
const asFile = (text) => text.replace(/(["'`])\/(privacy|terms)\1/g, '$1/$2.html$1');

for (const [from, name] of copies) {
  if (name.endsWith('.js') || name.endsWith('.html')) {
    await writeFile(join(out, name), asFile(await readFile(from, 'utf8')), 'utf8');
  } else {
    await cp(from, join(out, name));
  }
}

console.log(`www: ${copies.length + 2} files + assets`);
