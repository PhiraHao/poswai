/* Turning a receipt into something a 58mm thermal printer will print.

   Thai is drawn as a picture rather than sent as letters: the cheap printers
   carry a Chinese character set and whatever Thai code page the factory felt
   like, and this shop's printer turned out to have no Thai at all — every code
   page from 20 to 255 printed the digits and swallowed the Thai. A bitmap of
   real letters comes out right on all of them.

   Everything here except the drawing is plain arithmetic, so it runs and is
   tested under node as well as in the app. */

export const PAPER_DOTS = 384;        // 58mm paper at 203 dpi
export const STRIP_ROWS = 24;         // one ESC * strip

/* A Thai vowel or tone mark sits on the letter before it and has no width of
   its own. Starting a line with one leaves it stacked on nothing, which is how
   a bill came out of the printer with marks scattered across the table line. */
const THAI_MARKS = new Set([
  'ั', 'ิ', 'ี', 'ึ', 'ื', 'ุ', 'ู', 'ฺ',
  '็', '่', '้', '๊', '๋', '์', 'ํ', '๎',
]);

/** Break a too-long line at spaces, and inside a word only between letters. */
export function wrapLine(line, fits) {
  const pieces = [];
  let current = '';
  for (const word of line.split(/(\s+)/)) {
    if (!word) continue;
    if (fits(current + word)) { current += word; continue; }
    if (current.trim()) { pieces.push(current.trimEnd()); current = ''; }
    if (!word.trim()) continue;
    for (const char of word) {
      if (current && !THAI_MARKS.has(char) && !fits(current + char)) {
        pieces.push(current);
        current = '';
      }
      current += char;
    }
  }
  if (current.trim()) pieces.push(current.trimEnd());
  return pieces.length ? pieces : [''];
}

/** Every line of the receipt, already broken to fit the paper. */
export function layout(text, fits) {
  const lines = [];
  for (const raw of String(text).replace(/\r/g, '').split('\n')) {
    if (!raw.trim() || fits(raw)) lines.push(raw);
    else lines.push(...wrapLine(raw, fits));
  }
  return lines;
}

/** The picture, as ESC * strips.
 *
 * `ink(x, y)` says whether that dot is black. ESC 3 24 makes one line feed
 * exactly one strip tall so the strips stack with no seam, and ESC 2 puts the
 * usual spacing back for whatever prints next.
 *
 * The newer raster command (GS v 0) printed a band of noise through the middle
 * of this shop's receipts, in a place that moved with every copy; this older
 * command prints the same page clean.
 */
export function escStar(width, height, ink) {
  const strips = [];
  for (let top = 0; top < height; top += STRIP_ROWS) {
    const out = new Uint8Array(5 + width * 3 + 1);
    out.set([0x1b, 0x2a, 33, width & 0xff, width >> 8], 0);
    for (let x = 0; x < width; x++) {
      for (let part = 0; part < 3; part++) {
        let value = 0;
        for (let bit = 0; bit < 8; bit++) {
          const y = top + part * 8 + bit;
          // A set bit burns a dot.
          if (y < height && ink(x, y)) value |= 0x80 >> bit;
        }
        out[5 + x * 3 + part] = value;
      }
    }
    out[out.length - 1] = 0x0a;
    strips.push(out);
  }
  return join([
    new Uint8Array([0x1b, 0x40, 0x1b, 0x33, STRIP_ROWS]),
    ...strips,
    new Uint8Array([0x1b, 0x32, 0x0a, 0x0a, 0x0a, 0x0a, 0x1d, 0x56, 0x00]),
  ]);
}

export function join(parts) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of parts) { out.set(part, at); at += part.length; }
  return out;
}

/** Bluetooth Low Energy carries a few hundred bytes per write at best.
 *
 * A receipt is twenty thousand, so it goes out in pieces; the printer treats
 * the stream as one long command, so the pieces may fall anywhere. */
export function chunks(bytes, size = 180) {
  const pieces = [];
  for (let at = 0; at < bytes.length; at += size) {
    pieces.push(bytes.subarray(at, Math.min(at + size, bytes.length)));
  }
  return pieces;
}

/** Draw the receipt and hand back the dots. Browsers only: it needs a canvas. */
export function drawReceipt(text, {fontSize = 22, lineHeight = 29, pad = 6} = {}) {
  const canvas = document.createElement('canvas');
  canvas.width = PAPER_DOTS;
  const context = canvas.getContext('2d', {willReadFrequently: true});
  const font = `${fontSize}px "Noto Sans Thai", "Sarabun", "Tahoma", sans-serif`;
  context.font = font;
  const room = PAPER_DOTS - 2 * pad;
  const lines = layout(text, piece => context.measureText(piece).width <= room);

  canvas.height = Math.max(lineHeight, lines.length * lineHeight + 2 * pad);
  const draw = canvas.getContext('2d', {willReadFrequently: true});
  draw.fillStyle = '#fff';
  draw.fillRect(0, 0, canvas.width, canvas.height);
  draw.fillStyle = '#000';
  draw.textBaseline = 'top';
  draw.font = font;
  lines.forEach((line, index) => draw.fillText(line, pad, pad + index * lineHeight));

  const pixels = draw.getImageData(0, 0, canvas.width, canvas.height).data;
  const ink = (x, y) => pixels[(y * canvas.width + x) * 4] < 160;
  return escStar(canvas.width, canvas.height, ink);
}
