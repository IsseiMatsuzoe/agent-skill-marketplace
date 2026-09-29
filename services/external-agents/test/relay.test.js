import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { execFile } from 'node:child_process';
import sharp from 'sharp';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { createHttpServer } from '../src/server.js';
import { createGateway } from '../src/gateway.js';
import { createAdapters } from '../src/adapters.js';
import { ImageStore } from '../src/images.js';
import { readFileSync } from 'node:fs';

const relay = fileURLToPath(new URL('../../../plugins/external-agents/scripts/relay.mjs', import.meta.url));
test('packaged stdio relay discovers the common tool and transfers real uploaded bytes', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'external-agents-relay-'));
  const token = 'test-mcp-secret-only-never-provider-keys';
  const registry = JSON.parse(readFileSync(new URL('../registry.json', import.meta.url)));
  const images = new ImageStore(); let body;
  const call = createGateway({ registry, images, env: { ANTHROPIC_API_KEY: 'provider-only', EXTERNAL_AGENTS_ENABLE_PAID: 'true' }, log: () => {},
    adapters: createAdapters(async (_, key, input) => { assert.equal(key, 'provider-only'); body = input; return { model: input.model, content: [{ type: 'text', text: 'image response' }] }; }) });
  const server = createHttpServer({ token, images, call, port: 0 });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const config = join(directory, 'connection.json');
  writeFileSync(config, JSON.stringify({ url: `http://127.0.0.1:${server.address().port}/mcp`, token }));
  const environment = { ...process.env, EXTERNAL_AGENTS_CONNECTION_FILE: config };
  const client = new Client({ name: 'relay-test', version: '1' });
  try {
    const file = join(directory, 'image.png');
    writeFileSync(file, await sharp({ create: { width: 19, height: 17, channels: 3, background: 'red' } }).png().toBuffer());
    const upload = await promisify(execFile)(process.execPath, [relay, '--upload', file], { env: environment });
    assert.ok(!upload.stdout.includes(token));
    const asset = JSON.parse(upload.stdout);
    await client.connect(new StdioClientTransport({ command: process.execPath, args: [relay], env: environment }));
    const list = await client.listTools(); assert.equal(list.tools.length, 1);
    assert.equal(list.tools[0].name, 'call_external_agent');
    const result = await client.callTool({ name: 'call_external_agent', arguments: { agent: 'claude', task: 'review', visual_review: true, asset_ids: [asset.asset_id] } });
    assert.equal(result.structuredContent.ok, true); assert.equal(result.structuredContent.images_sent[0].width, 19);
    assert.equal(body.messages[0].content[0].type, 'image');
    const rejected = await client.callTool({ name: 'call_external_agent', arguments: { agent: 'unknown', task: 'x' } });
    assert.equal(rejected.structuredContent.error.code, 'INVALID_AGENT');
    // An unavailable gateway is an explicit MCP error, never a retried generation.
    await new Promise(resolve => server.close(resolve));
    await assert.rejects(client.listTools(), error => /GATEWAY_UNAVAILABLE/.test(error.message) && !error.message.includes(token));
  } finally {
    await client.close(); server.close(); rmSync(directory, { recursive: true, force: true });
  }
});

test('relay rejects non-loopback connection before exposing its token', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'external-agents-relay-'));
  try {
    const config = join(directory, 'connection.json');
    writeFileSync(config, JSON.stringify({ url: 'https://example.org/mcp', token: 'do-not-leak-this-private-mcp-token' }));
    await assert.rejects(promisify(execFile)(process.execPath, [relay], { env: { ...process.env, EXTERNAL_AGENTS_CONNECTION_FILE: config } }), error =>
      error.stderr.includes('CONNECTION_REQUIRED') && !error.stderr.includes('do-not-leak'));
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
