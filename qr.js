/* A QR encoder the shop can bet money on.

   The previous one drew something that looked like a QR code and that no
   reader could decode: the finder patterns were right, so a camera found the
   symbol and then gave up. Nobody noticed because nobody had yet scanned a
   PromptPay code to pay for anything.

   This one follows ISO/IEC 18004: byte mode, error correction level M,
   versions 1 to 10, Reed-Solomon over GF(256), the block interleaving that
   versions 4 and up require, all eight masks scored by the standard's own
   penalty rules, and BCH-coded format and version information.

   window.poswaiQr.modules(text) -> boolean[size][size], true meaning dark. */
(() => {
  'use strict';

  /* ---- GF(256), the field the error correction is computed in ---------- */
  const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  for (let i = 0, x = 1; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;          // the primitive polynomial QR uses
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  const mul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]];

  /* The generator polynomial for n error correction codewords. */
  const generator = n => {
    let poly = [1];
    for (let i = 0; i < n; i++) {
      const next = new Array(poly.length + 1).fill(0);
      for (let j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];
        next[j + 1] ^= mul(poly[j], EXP[i]);
      }
      poly = next;
    }
    return poly;
  };

  const remainder = (data, ecCount) => {
    const poly = generator(ecCount);
    const out = new Array(data.length + ecCount).fill(0);
    data.forEach((value, i) => { out[i] = value; });
    for (let i = 0; i < data.length; i++) {
      const factor = out[i];
      if (!factor) continue;
      for (let j = 0; j < poly.length; j++) out[i + j] ^= mul(poly[j], factor);
    }
    return out.slice(data.length);
  };

  /* ---- what each version holds at error correction level M -------------
     [data codewords in total, EC codewords per block, number of blocks].
     Where the blocks are uneven the longer ones come last, as the standard
     requires; the split below derives that from these three numbers. */
  const VERSIONS = [
    null,
    [16, 10, 1], [28, 16, 1], [44, 26, 1], [64, 18, 2], [86, 24, 2],
    [108, 16, 4], [124, 18, 4], [154, 22, 4], [182, 22, 5], [216, 26, 5],
  ];
  const ALIGN = [
    null, [], [6, 18], [6, 22], [6, 26], [6, 30],
    [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50],
  ];
  const MAX_VERSION = 10;

  const sizeOf = version => 17 + 4 * version;

  /* ---- the bit stream --------------------------------------------------- */
  const toBytes = text => {
    const bytes = new TextEncoder().encode(text);
    if (!bytes.length) throw new Error('ไม่มีข้อความให้ทำเป็น QR');
    return bytes;
  };

  const pickVersion = byteCount => {
    for (let version = 1; version <= MAX_VERSION; version++) {
      // mode indicator (4) + character count (8 for versions 1-9, 16 for 10)
      const countBits = version < 10 ? 8 : 16;
      const needed = Math.ceil((4 + countBits + byteCount * 8) / 8);
      if (needed <= VERSIONS[version][0]) return version;
    }
    throw new Error('ข้อความยาวเกินกว่าจะทำเป็น QR ได้');
  };

  const codewordsFor = (bytes, version) => {
    const [dataTotal] = VERSIONS[version];
    const countBits = version < 10 ? 8 : 16;
    const bits = [];
    const push = (value, length) => {
      for (let i = length - 1; i >= 0; i--) bits.push((value >> i) & 1);
    };
    push(0b0100, 4);                 // byte mode
    push(bytes.length, countBits);
    for (const byte of bytes) push(byte, 8);
    // Terminator, up to four zeroes, then pad to a whole codeword.
    for (let i = 0; i < 4 && bits.length < dataTotal * 8; i++) bits.push(0);
    while (bits.length % 8) bits.push(0);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) {
      let byte = 0;
      for (let j = 0; j < 8; j++) byte = (byte << 1) | bits[i + j];
      data.push(byte);
    }
    for (let pad = 0; data.length < dataTotal; pad++) data.push(pad % 2 ? 0x11 : 0xec);
    return data;
  };

  /* Split into blocks, add error correction to each, then interleave both
     the data and the EC codewords. Versions 4 and up have more than one
     block, and a reader expects them interleaved exactly this way. */
  const interleave = (data, version) => {
    const [dataTotal, ecPerBlock, blockCount] = VERSIONS[version];
    const shortLength = Math.floor(dataTotal / blockCount);
    const longCount = dataTotal % blockCount;      // these carry one byte more
    const blocks = [];
    let offset = 0;
    for (let i = 0; i < blockCount; i++) {
      const length = shortLength + (i >= blockCount - longCount ? 1 : 0);
      const block = data.slice(offset, offset + length);
      offset += length;
      blocks.push({data: block, ec: remainder(block, ecPerBlock)});
    }
    const out = [];
    for (let i = 0; i < shortLength + 1; i++) {
      for (const block of blocks) if (i < block.data.length) out.push(block.data[i]);
    }
    for (let i = 0; i < ecPerBlock; i++) {
      for (const block of blocks) out.push(block.ec[i]);
    }
    return out;
  };

  /* ---- the symbol ------------------------------------------------------- */
  const blankMatrix = size => ({
    modules: Array.from({length: size}, () => new Array(size).fill(false)),
    reserved: Array.from({length: size}, () => new Array(size).fill(false)),
  });

  const placeFunctionPatterns = (grid, version) => {
    const size = sizeOf(version);
    const set = (row, col, dark) => {
      if (row < 0 || col < 0 || row >= size || col >= size) return;
      grid.modules[row][col] = dark;
      grid.reserved[row][col] = true;
    };
    // Finders, with their separators.
    for (const [baseRow, baseCol] of [[0, 0], [0, size - 7], [size - 7, 0]]) {
      for (let r = -1; r <= 7; r++) {
        for (let c = -1; c <= 7; c++) {
          const ring = Math.max(Math.abs(r - 3), Math.abs(c - 3));
          const inside = r >= 0 && r <= 6 && c >= 0 && c <= 6;
          set(baseRow + r, baseCol + c, inside && ring !== 2);
        }
      }
    }
    // Alignment patterns, skipping the three that would sit on a finder.
    const centres = ALIGN[version];
    for (const row of centres) {
      for (const col of centres) {
        if ((row === 6 && col === 6) || (row === 6 && col === size - 7) ||
            (row === size - 7 && col === 6)) continue;
        for (let r = -2; r <= 2; r++) {
          for (let c = -2; c <= 2; c++) {
            set(row + r, col + c, Math.max(Math.abs(r), Math.abs(c)) !== 1);
          }
        }
      }
    }
    // Timing patterns.
    for (let i = 8; i < size - 8; i++) {
      set(6, i, i % 2 === 0);
      set(i, 6, i % 2 === 0);
    }
    // The one module that is always dark.
    set(size - 8, 8, true);
    // Reserve the format areas; they are written once the mask is chosen.
    for (let i = 0; i < 9; i++) {
      if (!grid.reserved[8][i]) { grid.modules[8][i] = false; grid.reserved[8][i] = true; }
      if (!grid.reserved[i][8]) { grid.modules[i][8] = false; grid.reserved[i][8] = true; }
    }
    for (let i = 0; i < 8; i++) {
      grid.modules[8][size - 1 - i] = false; grid.reserved[8][size - 1 - i] = true;
      if (i < 7) { grid.modules[size - 1 - i][8] = false; grid.reserved[size - 1 - i][8] = true; }
    }
    // And the version areas, for versions that carry them.
    if (version >= 7) {
      for (let i = 0; i < 18; i++) {
        const row = Math.floor(i / 3), col = i % 3;
        grid.reserved[size - 11 + col][row] = true;
        grid.reserved[row][size - 11 + col] = true;
      }
    }
  };

  const placeData = (grid, codewords, version) => {
    const size = sizeOf(version);
    let bitIndex = 0;
    const totalBits = codewords.length * 8;
    let upward = true;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;              // the vertical timing column
      for (let step = 0; step < size; step++) {
        const row = upward ? size - 1 - step : step;
        for (let offset = 0; offset < 2; offset++) {
          const col = right - offset;
          if (grid.reserved[row][col]) continue;
          let bit = false;
          if (bitIndex < totalBits) {
            bit = ((codewords[bitIndex >> 3] >> (7 - (bitIndex & 7))) & 1) === 1;
            bitIndex++;
          }
          grid.modules[row][col] = bit;
        }
      }
      upward = !upward;
    }
  };

  const MASKS = [
    (r, c) => (r + c) % 2 === 0,
    (r) => r % 2 === 0,
    (r, c) => c % 3 === 0,
    (r, c) => (r + c) % 3 === 0,
    (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
    (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
    (r, c) => ((((r * c) % 2) + ((r * c) % 3)) % 2) === 0,
    (r, c) => ((((r + c) % 2) + ((r * c) % 3)) % 2) === 0,
  ];

  /* The standard's four penalty rules. The lowest total wins, which is what
     keeps a code free of patterns a reader would mistake for a finder. */
  const penalty = modules => {
    const size = modules.length;
    let score = 0;
    const run = line => {
      let total = 0, length = 1;
      for (let i = 1; i < size; i++) {
        if (line[i] === line[i - 1]) length++;
        else { if (length >= 5) total += length - 2; length = 1; }
      }
      if (length >= 5) total += length - 2;
      return total;
    };
    for (let i = 0; i < size; i++) {
      score += run(modules[i]);
      score += run(modules.map(row => row[i]));
    }
    for (let r = 0; r < size - 1; r++) {
      for (let c = 0; c < size - 1; c++) {
        const first = modules[r][c];
        if (first === modules[r][c + 1] && first === modules[r + 1][c] &&
            first === modules[r + 1][c + 1]) score += 3;
      }
    }
    const shapes = [[true, false, true, true, true, false, true, false, false, false, false],
                    [false, false, false, false, true, false, true, true, true, false, true]];
    const matches = line => {
      let total = 0;
      for (let i = 0; i + 11 <= size; i++) {
        for (const shape of shapes) {
          if (shape.every((value, j) => line[i + j] === value)) { total += 40; break; }
        }
      }
      return total;
    };
    for (let i = 0; i < size; i++) {
      score += matches(modules[i]);
      score += matches(modules.map(row => row[i]));
    }
    let dark = 0;
    for (const row of modules) for (const value of row) if (value) dark++;
    const percent = (dark * 100) / (size * size);
    score += Math.floor(Math.abs(percent - 50) / 5) * 10;
    return score;
  };

  const formatBits = mask => {
    // Level M is 0b00; five bits of level and mask, BCH(15,5), then masked.
    let value = (0b00 << 3) | mask;
    let remainderBits = value << 10;
    for (let i = 14; i >= 10; i--) {
      if (remainderBits & (1 << i)) remainderBits ^= 0b10100110111 << (i - 10);
    }
    return ((value << 10) | remainderBits) ^ 0b101010000010010;
  };

  const versionBits = version => {
    let remainderBits = version << 12;
    for (let i = 17; i >= 12; i--) {
      if (remainderBits & (1 << i)) remainderBits ^= 0b1111100100101 << (i - 12);
    }
    return (version << 12) | remainderBits;
  };

  const writeFormat = (modules, version, mask) => {
    const size = sizeOf(version);
    const bits = formatBits(mask);
    /* Both copies carry the fifteen bits most significant first, and the two
       runs of the second copy are seven modules then eight, not the other way
       round. Getting either backwards leaves a symbol a reader cannot open. */
    const first = [[8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [8, 7], [8, 8],
                   [7, 8], [5, 8], [4, 8], [3, 8], [2, 8], [1, 8], [0, 8]];
    const second = [];
    for (let i = 0; i < 7; i++) second.push([size - 1 - i, 8]);
    for (let i = 0; i < 8; i++) second.push([8, size - 8 + i]);
    for (let i = 0; i < 15; i++) {
      const value = ((bits >> (14 - i)) & 1) === 1;
      modules[first[i][0]][first[i][1]] = value;
      modules[second[i][0]][second[i][1]] = value;
    }
    modules[size - 8][8] = true;
  };

  const writeVersion = (modules, version) => {
    if (version < 7) return;
    const size = sizeOf(version);
    const bits = versionBits(version);
    for (let i = 0; i < 18; i++) {
      const value = ((bits >> i) & 1) === 1;
      const row = Math.floor(i / 3), col = i % 3;
      modules[size - 11 + col][row] = value;
      modules[row][size - 11 + col] = value;
    }
  };

  /* ``forcedMask`` exists for the tests, which compare this encoder against a
     reference one mask at a time; picking a mask by score is not something two
     implementations have to agree on, but every other module is. */
  const build = (text, forcedMask = null) => {
    const bytes = toBytes(text);
    const version = pickVersion(bytes.length);
    const codewords = interleave(codewordsFor(bytes, version), version);
    const size = sizeOf(version);

    const masks = forcedMask === null ? [0, 1, 2, 3, 4, 5, 6, 7] : [forcedMask];
    let best = null;
    for (const mask of masks) {
      const grid = blankMatrix(size);
      placeFunctionPatterns(grid, version);
      placeData(grid, codewords, version);
      for (let r = 0; r < size; r++) {
        for (let c = 0; c < size; c++) {
          if (!grid.reserved[r][c] && MASKS[mask](r, c)) grid.modules[r][c] = !grid.modules[r][c];
        }
      }
      writeFormat(grid.modules, version, mask);
      writeVersion(grid.modules, version);
      const score = penalty(grid.modules);
      if (!best || score < best.score) best = {score, mask, modules: grid.modules, version};
    }
    return best;
  };

  window.poswaiQr = {
    /** The dark/light grid for one string, smallest version that fits. */
    modules: text => build(String(text)).modules,
    build,
  };
})();
