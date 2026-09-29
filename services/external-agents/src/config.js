import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { parseEnv } from 'node:util';
import { z } from 'zod';
import { validateRegistry, fail } from './contracts.js';

export const root = fileURLToPath(new URL('../', import.meta.url));
export const local = join(root, '.local');
export const settingsSchema = z.object({
  port: z.number().int().min(1024).max(65535).default(47831),
  file_download_origins: z.array(z.string().url()).default([]),
}).strict();
export function loadConfig() {
  try {
    const registryPath = existsSync(join(local, 'registry.json')) ? join(local, 'registry.json') : join(root, 'registry.json');
    const registry = validateRegistry(JSON.parse(readFileSync(registryPath, 'utf8')));
    const settings = settingsSchema.parse(existsSync(join(local, 'settings.json')) ? JSON.parse(readFileSync(join(local, 'settings.json'), 'utf8')) : {});
    for (const origin of settings.file_download_origins) {
      const u = new URL(origin);
      if (u.protocol !== 'https:' || u.origin !== origin) fail('CONFIG_REQUIRED', 'Download origins must be exact HTTPS origins.');
    }
    const secrets = existsSync(join(local, 'secrets.env')) ? parseEnv(readFileSync(join(local, 'secrets.env'), 'utf8')) : {};
    // Local secrets win over stale parent environments. Never print this object.
    return { registry, settings, env: { ...process.env, ...secrets } };
  } catch { fail('CONFIG_REQUIRED', 'Local configuration is missing or invalid. Run setup and doctor.'); }
}
