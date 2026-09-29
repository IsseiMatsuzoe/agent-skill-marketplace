// Transport only: all policy, routing, image validation and inference live in the shared gateway.
import { readFileSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, extname } from 'node:path';
import { createInterface } from 'node:readline';

function connection() {
  const path = process.env.EXTERNAL_AGENTS_CONNECTION_FILE || join(homedir(), '.config', 'external-agents', 'connection.json');
  const config = JSON.parse(readFileSync(path, 'utf8'));
  const url = new URL(config.url);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.pathname !== '/mcp' || url.username || url.password || url.search || url.hash || typeof config.token !== 'string' || config.token.length < 32)
    throw new Error('Invalid connection');
  return { url, token: config.token };
}
async function request(config, path, body, type) {
  const response = await fetch(new URL(path, config.url), {
    method: 'POST', headers: { Authorization: `Bearer ${config.token}`, 'Content-Type': type, Accept: 'application/json, text/event-stream' },
    // Leave room for the gateway's 30-minute X Search/deep absolute timeout.
    body, redirect: 'error', signal: AbortSignal.timeout(31 * 60 * 1000),
  });
  if (!response.ok) { await response.body?.cancel(); throw new Error('Gateway rejected request'); }
  if (response.status === 202 || response.status === 204) { await response.body?.cancel(); return null; }
  let size = 0; const chunks = [];
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > 4 * 1024 * 1024) throw new Error('Response too large');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
try {
  const config = connection();
  if (process.argv[2] === '--upload') {
    const file = process.argv[3];
    const mime = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' }[extname(file ?? '').toLowerCase()];
    if (!mime || !statSync(file).isFile() || statSync(file).size > 5 * 1024 * 1024) throw new Error('Invalid image');
    console.log(JSON.stringify(await request(config, '/assets', readFileSync(file), mime)));
  } else {
    const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
    for await (const line of lines) {
      if (!line.trim()) continue;
      let message;
      try {
        if (Buffer.byteLength(line) > 256 * 1024) throw new Error('Input too large');
        message = JSON.parse(line);
        const result = await request(config, '/mcp', line, 'application/json');
        if (result !== null) process.stdout.write(JSON.stringify(result) + '\n');
      } catch {
        if (message?.id !== undefined) process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: message.id,
          error: { code: -32603, message: 'GATEWAY_UNAVAILABLE: check local connection and running backend. Outcome may be unknown; no retry was made.' } }) + '\n');
        else process.stderr.write('RELAY_REQUEST_FAILED\n');
      }
    }
  }
} catch {
  process.stderr.write('CONNECTION_REQUIRED: run npm run connect-host in the prepared backend, then npm start. No secret values were printed.\n');
  process.exitCode = 1;
}
