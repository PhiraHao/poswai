/* The arithmetic behind a printed receipt, checked without a printer.
 *
 *   node --test print-app/test
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  PAPER_DOTS, STRIP_ROWS, chunks, escStar, join, layout, wrapLine,
} from '../www/escpos.js';

/* A stand-in for the real measuring: every character is one unit wide. */
const widthOf = limit => piece => piece.length <= limit;

test('a broken line never starts with a vowel or tone mark', () => {
  // Thai marks sit on the letter before them and have no width of their own.
  // Breaking between a letter and its mark leaves the mark stranded at the
  // start of the next line, stacked on nothing — which is what the shop's
  // first printed bill did to "โต๊ะ: 1 | วันที่: ...".
  const line = 'โต๊ะ: 1 | วันที่: 18/10/2569 13:52:17 ' + 'ผัดกะเพราหมูสับ'.repeat(4);
  const pieces = wrapLine(line, widthOf(18));
  assert.ok(pieces.length > 1, 'nothing was broken, so nothing was tested');
  for (const piece of pieces) {
    assert.ok(!'ัิีึืฺุู็่้๊๋์ํ๎'
      .includes(piece[0]), `a mark starts a line: ${piece}`);
  }
  assert.equal(pieces.join('').replace(/\s/g, ''), line.replace(/\s/g, ''),
    'letters went missing in the break');
});

test('a line with spaces breaks at a space', () => {
  const pieces = wrapLine('TAX ID: 0505566001234 (VAT Included)', widthOf(26));
  assert.deepEqual(pieces, ['TAX ID: 0505566001234 (VAT', 'Included)']);
});

test('lines that fit are left exactly as they are', () => {
  const lines = layout('หนึ่ง\n\nสอง', widthOf(40));
  assert.deepEqual(lines, ['หนึ่ง', '', 'สอง']);
});

test('the picture goes out as 24-dot strips', () => {
  // One tall image put a band of noise through the middle of this shop's
  // receipts, in a place that moved with every copy — so it looked like a
  // text problem right up until the identical line below printed clean.
  const height = STRIP_ROWS * 3 + 5;
  const data = escStar(PAPER_DOTS, height, (x, y) => x === y);
  const marker = [0x1b, 0x2a, 33];
  let strips = 0;
  for (let at = 0; at + 2 < data.length; at++) {
    if (data[at] === marker[0] && data[at + 1] === marker[1] && data[at + 2] === marker[2]) strips++;
  }
  assert.equal(strips, 4, 'one strip per 24 rows, and one for the remainder');
  assert.deepEqual([...data.subarray(0, 5)], [0x1b, 0x40, 0x1b, 0x33, STRIP_ROWS],
    'the printer is not reset, or the strips would stack with a seam');
  assert.ok(data.length > PAPER_DOTS * 3 * 4, 'the dots themselves are missing');
});

test('a dot that is black comes out as a set bit, in the right place', () => {
  // Wrong bit order or a missed inversion prints a page of noise, and no
  // amount of staring at the code shows it.
  const data = escStar(8, 1, (x, y) => x === 0 && y === 0);
  const start = 5 + 5;                       // reset + line spacing, then header
  assert.equal(data[start], 0x80, 'the top-left dot is not the top bit');
  assert.equal(data[start + 1], 0, 'something else was inked');
});

test('the slip ends with enough paper to tear', () => {
  const data = escStar(8, 1, () => false);
  const tail = [...data.subarray(data.length - 9)];
  assert.deepEqual(tail, [0x1b, 0x32, 0x0a, 0x0a, 0x0a, 0x0a, 0x1d, 0x56, 0x00],
    'line spacing is left changed, or there is no room to tear it off');
});

test('the bytes go out in pieces a Bluetooth link will accept', () => {
  const bytes = new Uint8Array(500).fill(7);
  const pieces = chunks(bytes, 180);
  assert.deepEqual(pieces.map(piece => piece.length), [180, 180, 140]);
  assert.deepEqual([...join(pieces)], [...bytes], 'the bytes changed on the way out');
});
