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

/** What one line of the receipt is, read from how the POS laid it out.
 *
 * The POS builds receipts for a fixed-width font: columns lined up with runs
 * of spaces, rules made of dashes, titles centred with leading spaces. A Thai
 * font is not fixed-width — its spaces are narrow and its letters vary — so
 * drawn as written, a 32-character line covered barely sixty per cent of the
 * paper and sat against the left edge. Reading the layout back lets each part
 * be drawn where it was meant to be: rules edge to edge, prices against the
 * right edge, titles in the middle.
 *
 *   {kind: 'blank'} · {kind: 'rule', style: 'dash'|'solid'}
 *   {kind: 'center', text} · {kind: 'cells', cells: [...]} · {kind: 'text', text}
 */
export function readLine(raw) {
  const line = String(raw).replace(/\s+$/, '');
  if (!line.trim()) return {kind: 'blank'};
  if (/^\s*-{6,}\s*$/.test(line)) return {kind: 'rule', style: 'dash'};
  if (/^\s*[=_]{6,}\s*$/.test(line)) return {kind: 'rule', style: 'solid'};
  const cells = line.trim().split(/\s{2,}/);
  if (cells.length >= 2) return {kind: 'cells', cells};
  if (/^\s{2,}/.test(line)) return {kind: 'center', text: line.trim()};
  return {kind: 'text', text: line};
}

/** Draw the receipt and hand back the dots. Browsers only: it needs a canvas. */
export function drawReceipt(text, {fontSize = 24, lineHeight = 32, pad = 4} = {}) {
  const canvas = document.createElement('canvas');
  canvas.width = PAPER_DOTS;
  const measure = canvas.getContext('2d', {willReadFrequently: true});
  const font = `${fontSize}px "Noto Sans Thai", "Sarabun", "Tahoma", sans-serif`;
  measure.font = font;
  const width = text => measure.measureText(text).width;
  const left = pad;
  const right = PAPER_DOTS - pad;
  const room = right - left;
  const gap = Math.round(fontSize * 0.6);

  /* Lay every line out first, so the canvas can be made exactly tall enough.
     Each entry is one printed row: what to draw, and where. */
  const rows = [];
  for (const raw of String(text).replace(/\r/g, '').split('\n')) {
    const line = readLine(raw);
    if (line.kind === 'blank') { rows.push([]); continue; }
    if (line.kind === 'rule') { rows.push([{rule: line.style}]); continue; }
    if (line.kind === 'center') {
      for (const piece of wrapLine(line.text, t => width(t) <= room)) {
        rows.push([{text: piece, x: left + (room - width(piece)) / 2}]);
      }
      continue;
    }
    if (line.kind === 'text') {
      for (const piece of wrapLine(line.text, t => width(t) <= room)) rows.push([{text: piece, x: left}]);
      continue;
    }
    /* Columns: the last against the right edge; with three or more, the one
       before it (the quantity) right-aligned in a column of its own; whatever
       is left is the name, wrapped in the room that remains. */
    const cells = line.cells;
    const last = cells[cells.length - 1];
    const middle = cells.length >= 3 ? cells[cells.length - 2] : null;
    const name = cells.slice(0, middle ? -2 : -1).join('  ');
    const lastWidth = width(last);
    const middleEnd = right - Math.max(lastWidth, width('฿0,000.00')) - gap;
    const nameRoom = (middle ? middleEnd - width(middle) : right - lastWidth) - gap - left;
    if (nameRoom < room * 0.3) {
      // Too crowded to keep the columns: fall back to plain wrapped text.
      for (const piece of wrapLine(raw.trim(), t => width(t) <= room)) rows.push([{text: piece, x: left}]);
      continue;
    }
    const names = wrapLine(name, t => width(t) <= nameRoom);
    names.forEach((piece, index) => {
      const row = [{text: piece, x: left}];
      if (index === 0) {
        if (middle) row.push({text: middle, x: middleEnd - width(middle)});
        row.push({text: last, x: right - lastWidth});
      }
      rows.push(row);
    });
  }

  canvas.height = Math.max(lineHeight, rows.length * lineHeight + 2 * pad);
  const draw = canvas.getContext('2d', {willReadFrequently: true});
  draw.fillStyle = '#fff';
  draw.fillRect(0, 0, canvas.width, canvas.height);
  draw.fillStyle = '#000';
  draw.strokeStyle = '#000';
  draw.textBaseline = 'top';
  draw.font = font;
  rows.forEach((row, index) => {
    const top = pad + index * lineHeight;
    for (const part of row) {
      if (part.rule) {
        const y = Math.round(top + lineHeight / 2) + 0.5;
        draw.lineWidth = 2;
        draw.setLineDash(part.rule === 'dash' ? [8, 6] : []);
        draw.beginPath();
        draw.moveTo(left, y);
        draw.lineTo(right, y);
        draw.stroke();
        draw.setLineDash([]);
      } else {
        draw.fillText(part.text, Math.round(part.x), top);
      }
    }
  });

  const pixels = draw.getImageData(0, 0, canvas.width, canvas.height).data;
  const ink = (x, y) => pixels[(y * canvas.width + x) * 4] < 160;
  return escStar(canvas.width, canvas.height, ink);
}
