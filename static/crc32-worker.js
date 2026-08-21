'use strict';

// CRC32 worker - keeps checksum computation off the main thread so chunk
// uploads and UI stay responsive. Same table algorithm as the old inline JS.
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();

self.onmessage = (e) => {
  const { id, buffer } = e.data;
  const view = new Uint8Array(buffer);
  let c = 0xFFFFFFFF;
  for (let i = 0; i < view.length; i++) {
    c = CRC_TABLE[(c ^ view[i]) & 0xFF] ^ (c >>> 8);
  }
  const crc = ((c ^ 0xFFFFFFFF) >>> 0).toString(16).padStart(8, '0');
  self.postMessage({ id, crc });
};
