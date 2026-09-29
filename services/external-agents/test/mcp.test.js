import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import sharp from 'sharp';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { createGateway } from '../src/gateway.js';
import { createAdapters } from '../src/adapters.js';
import { createHttpServer } from '../src/server.js';
import { ImageStore } from '../src/images.js';

test('real MCP HTTP initialize/list/call/output/error and authenticated upload, with mock inference', async () => {
  const token = 'test-local-token-with-at-least-32-characters';
  const registry = JSON.parse(readFileSync(new URL('../registry.json', import.meta.url)));
  const images = new ImageStore(); let calls = 0; let lastBody;
  const gateway = createGateway({ registry, images, env: { ANTHROPIC_API_KEY: 'fake', EXTERNAL_AGENTS_ENABLE_PAID: 'true' }, log: () => {}, adapters: createAdapters(async (_, __, body) => {
    calls++; lastBody = body; return { model: body.model, content: [{ type: 'text', text: 'MCP verified' }] };
  }) });
  const server = createHttpServer({ token, images, call: gateway, port: 0 });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const client = new Client({ name: 'local-test', version: '1' });
  try {
    assert.equal((await fetch(`${base}/mcp`, { method: 'POST', body: '{}' })).status, 401);
    assert.equal((await fetch(`${base}/assets`, { method: 'POST', headers: { Authorization: 'Bearer wrong' }, body: 'image' })).status, 401);
    assert.equal((await fetch(`${base}/health`, { headers: { Authorization: `Bearer ${token}`, Origin: 'https://evil.example' } })).status, 403);
    assert.equal(calls, 0);
    await client.connect(new StreamableHTTPClientTransport(new URL(`${base}/mcp`), { requestInit: { headers: { Authorization: `Bearer ${token}` } } }));
    const { tools } = await client.listTools(); assert.equal(tools.length, 1); assert.equal(tools[0].name, 'call_external_agent');
    assert.ok(tools[0].outputSchema); assert.deepEqual(tools[0]._meta['openai/fileParams'], ['image_files']);
    const imageObject = tools[0].inputSchema.properties.image_files.items;
    assert.deepEqual(imageObject.required.sort(), ['download_url', 'file_id']);
    assert.deepEqual(Object.keys(imageObject.properties).sort(), ['download_url', 'file_id', 'file_name', 'mime_type']);
    const result = await client.callTool({ name: tools[0].name, arguments: { agent: 'claude', task: 'hello' } });
    assert.equal(result.isError, false); assert.equal(result.structuredContent.response, 'MCP verified');
    assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
    const rejected = await client.callTool({ name: tools[0].name, arguments: { agent: 'kimi', task: 'auto' } });
    assert.equal(rejected.isError, true); assert.equal(rejected.structuredContent.error.code, 'EXPLICIT_REQUEST_REQUIRED');
    const bytes = await sharp({ create: { width: 8, height: 6, channels: 3, background: 'blue' } }).png().toBuffer();
    const upload = await fetch(`${base}/assets`, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'image/png' }, body: bytes });
    assert.equal(upload.status, 201); const asset = await upload.json();
    const visual = await client.callTool({ name: tools[0].name, arguments: { agent: 'claude', task: 'review', mode: 'review', visual_review: true, asset_ids: [asset.asset_id] } });
    assert.equal(visual.isError, false); assert.equal(visual.structuredContent.images_sent[0].width, 8);
    assert.equal(lastBody.messages[0].content[0].type, 'image'); assert.equal(calls, 2);
  } finally { await client.close(); await new Promise(resolve => server.close(resolve)); }
});
