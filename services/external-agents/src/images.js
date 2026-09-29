import https from 'node:https';
import dns from 'node:dns';
import { randomUUID, createHash } from 'node:crypto';
import ipaddr from 'ipaddr.js';
import sharp from 'sharp';
import { fail, GatewayError } from './contracts.js';

export const MAX_IMAGE = 5 * 1024 * 1024;
export const MAX_TOTAL = 12 * 1024 * 1024;
export function publicAddress(address) {
  try { return ipaddr.process(address).range() === 'unicast'; } catch { return false; }
}
export function validateDownloadUrl(raw, origins) {
  let u;
  try { u = new URL(raw); } catch { fail('IMAGE_UNAVAILABLE', 'Invalid image URL.'); }
  if (u.protocol !== 'https:' || u.username || u.password || u.hash || !origins.includes(u.origin))
    fail('IMAGE_UNAVAILABLE', 'Image download origin is not approved.');
  const literal = u.hostname.replace(/^\[|\]$/g, '');
  if (ipaddr.isValid(literal) && !publicAddress(literal)) fail('IMAGE_UNAVAILABLE', 'Private image address is forbidden.');
  return u;
}
// Resolve once at connect time and pass only the vetted address to the socket.
// No preflight DNS lookup followed by an unvalidated second resolution.
export function safeLookup(host, options, callback, lookup = dns.lookup) {
  lookup(host, { all: true }, (error, addresses) => {
    if (error || !addresses.length || addresses.some(a => !publicAddress(a.address)))
      return callback(new Error('Blocked image address'));
    if (options.all) callback(null, addresses);
    else callback(null, addresses[0].address, addresses[0].family);
  });
}
export async function downloadImage(raw, origins, get = https.get) {
  const url = validateDownloadUrl(raw, origins);
  return new Promise((resolve, reject) => {
    const unavailable = () => reject(new GatewayError('IMAGE_UNAVAILABLE', 'Image download failed; no image was omitted or replaced.'));
    const req = get(url, { lookup: safeLookup, agent: false, signal: AbortSignal.timeout(20000) }, response => {
      // Reject ALL redirects. Never forward signed URLs or credentials elsewhere.
      if (response.statusCode !== 200) { response.destroy(); unavailable(); return; }
      let size = 0; const chunks = [];
      response.on('data', chunk => {
        size += chunk.length;
        if (size > MAX_IMAGE) { response.destroy(); unavailable(); return; }
        chunks.push(chunk);
      });
      response.on('error', unavailable);
      response.on('end', () => resolve(Buffer.concat(chunks)));
    });
    req.on('error', unavailable);
  });
}

export async function validateImage(bytes, claimedMime, id = randomUUID()) {
  if (!Buffer.isBuffer(bytes) || !bytes.length || bytes.length > MAX_IMAGE)
    fail('IMAGE_REJECTED', 'Image is empty or exceeds 5 MiB.');
  try {
    const image = sharp(bytes, { limitInputPixels: 20000000, failOn: 'warning', animated: true });
    const meta = await image.metadata();
    const mime = { png: 'image/png', jpeg: 'image/jpeg', webp: 'image/webp' }[meta.format];
    if (!mime || (meta.pages ?? 1) !== 1 || (claimedMime && claimedMime !== mime))
      fail('IMAGE_REJECTED', 'Image must be a single-frame PNG, JPEG or WebP with matching MIME.');
    // Decode fully and strip metadata. Orient pixels, do not crop, shrink or recolor.
    const { data, info } = await image.rotate().toBuffer({ resolveWithObject: true });
    if (data.length > MAX_IMAGE) fail('IMAGE_REJECTED', 'Normalized image exceeds 5 MiB.');
    return { id, bytes: data, mime_type: mime, width: info.width, height: info.height, sha256: createHash('sha256').update(data).digest('hex') };
  } catch (error) {
    if (error instanceof GatewayError) throw error;
    fail('IMAGE_REJECTED', 'Image decoding failed or pixel limit exceeded.');
  }
}

export class ImageStore {
  constructor({ origins = [], download = downloadImage, now = Date.now } = {}) {
    this.origins = origins; this.download = download; this.now = now; this.assets = new Map();
  }
  prune() { for (const [id, a] of this.assets) if (a.expires <= this.now()) this.assets.delete(id); }
  async upload(bytes, mime) {
    this.prune();
    if (this.assets.size >= 12) fail('IMAGE_REJECTED', 'Temporary image store is full; wait for expiry.');
    const image = await validateImage(bytes, mime);
    this.assets.set(image.id, { image, expires: this.now() + 15 * 60 * 1000 });
    return { asset_id: image.id, expires_in_seconds: 900 };
  }
  async resolve(input) {
    this.prune();
    if (input.asset_ids.length + input.image_files.length > 3) fail('IMAGE_REJECTED', 'At most three images per request.');
    const images = [];
    for (const id of input.asset_ids) {
      const asset = this.assets.get(id);
      if (!asset) fail('IMAGE_UNAVAILABLE', 'Image asset is missing or expired.');
      images.push(asset.image);
    }
    for (const file of input.image_files) {
      const bytes = await this.download(file.download_url, this.origins);
      images.push(await validateImage(bytes, file.mime_type, file.file_id));
    }
    if (images.reduce((s, i) => s + i.bytes.length, 0) > MAX_TOTAL) fail('IMAGE_REJECTED', 'Combined images exceed 12 MiB.');
    if (input.visual_review && !images.length) fail('IMAGE_UNAVAILABLE', 'Visual review requires actual images.');
    return images;
  }
}
