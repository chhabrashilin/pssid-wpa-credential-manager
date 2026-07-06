/**
 * Pure-JavaScript MD4 (RFC 1320).
 *
 * Vendored deliberately: OpenSSL 3 removed MD4 from the default provider, so
 * `crypto.createHash("md4")` is unavailable on many modern Node builds. NT
 * hashes (MSCHAPv2) require MD4, so we ship a tested implementation instead of
 * depending on the platform legacy provider.
 *
 * Verified against RFC 1320 Appendix A.5 test vectors (see md4.test.ts).
 *
 * MD4 is cryptographically broken; it is used here ONLY because the MSCHAPv2
 * NT hash is defined as MD4(UTF-16LE(password)). It is never used as a
 * general-purpose hash.
 */

function rotl(x: number, n: number): number {
  return (x << n) | (x >>> (32 - n));
}

// Round auxiliary functions.
function f(x: number, y: number, z: number): number {
  return (x & y) | (~x & z);
}
function g(x: number, y: number, z: number): number {
  return (x & y) | (x & z) | (y & z);
}
function h(x: number, y: number, z: number): number {
  return x ^ y ^ z;
}

// 32-bit safe addition.
function add(...args: number[]): number {
  let sum = 0;
  for (const a of args) sum = (sum + a) | 0;
  return sum >>> 0;
}

export function md4(input: Buffer): Buffer {
  const msgLenBits = input.length * 8;

  // Padding: 0x80 byte, then zeros, until length ≡ 56 (mod 64), then 8-byte
  // little-endian original bit length.
  const padLen = ((input.length % 64) < 56 ? 56 : 120) - (input.length % 64);
  const total = input.length + padLen + 8;
  const buf = Buffer.alloc(total);
  input.copy(buf);
  buf[input.length] = 0x80;
  // Little-endian 64-bit length (only lower 32 bits meaningful for our sizes).
  buf.writeUInt32LE(msgLenBits >>> 0, total - 8);
  buf.writeUInt32LE(Math.floor(msgLenBits / 0x100000000), total - 4);

  let a = 0x67452301;
  let b = 0xefcdab89;
  let c = 0x98badcfe;
  let d = 0x10325476;

  const x = new Array<number>(16);
  for (let off = 0; off < total; off += 64) {
    for (let i = 0; i < 16; i++) x[i] = buf.readUInt32LE(off + i * 4);

    const aa = a;
    const bb = b;
    const cc = c;
    const dd = d;

    // Round 1
    const r1 = [3, 7, 11, 19];
    for (let i = 0; i < 16; i++) {
      const k = i;
      const s = r1[i % 4]!;
      if (i % 4 === 0) a = rotl(add(a, f(b, c, d), x[k]!), s);
      else if (i % 4 === 1) d = rotl(add(d, f(a, b, c), x[k]!), s);
      else if (i % 4 === 2) c = rotl(add(c, f(d, a, b), x[k]!), s);
      else b = rotl(add(b, f(c, d, a), x[k]!), s);
    }

    // Round 2 (constant 0x5a827999)
    const r2 = [3, 5, 9, 13];
    const order2 = [0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15];
    for (let i = 0; i < 16; i++) {
      const k = order2[i]!;
      const s = r2[i % 4]!;
      if (i % 4 === 0) a = rotl(add(a, g(b, c, d), x[k]!, 0x5a827999), s);
      else if (i % 4 === 1) d = rotl(add(d, g(a, b, c), x[k]!, 0x5a827999), s);
      else if (i % 4 === 2) c = rotl(add(c, g(d, a, b), x[k]!, 0x5a827999), s);
      else b = rotl(add(b, g(c, d, a), x[k]!, 0x5a827999), s);
    }

    // Round 3 (constant 0x6ed9eba1)
    const r3 = [3, 9, 11, 15];
    const order3 = [0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15];
    for (let i = 0; i < 16; i++) {
      const k = order3[i]!;
      const s = r3[i % 4]!;
      if (i % 4 === 0) a = rotl(add(a, h(b, c, d), x[k]!, 0x6ed9eba1), s);
      else if (i % 4 === 1) d = rotl(add(d, h(a, b, c), x[k]!, 0x6ed9eba1), s);
      else if (i % 4 === 2) c = rotl(add(c, h(d, a, b), x[k]!, 0x6ed9eba1), s);
      else b = rotl(add(b, h(c, d, a), x[k]!, 0x6ed9eba1), s);
    }

    a = add(a, aa);
    b = add(b, bb);
    c = add(c, cc);
    d = add(d, dd);
  }

  const out = Buffer.alloc(16);
  out.writeUInt32LE(a >>> 0, 0);
  out.writeUInt32LE(b >>> 0, 4);
  out.writeUInt32LE(c >>> 0, 8);
  out.writeUInt32LE(d >>> 0, 12);
  return out;
}
