import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import sharp from 'sharp';
import { EventEmitter } from 'node:events';
import { Readable } from 'node:stream';
import { createGateway } from '../src/gateway.js';
import { createAdapters, postJson } from '../src/adapters.js';
import { validateRegistry, inputSchema, resultSchema } from '../src/contracts.js';
import { ImageStore, validateImage, publicAddress, validateDownloadUrl, safeLookup, downloadImage, MAX_IMAGE } from '../src/images.js';

const registry = JSON.parse(readFileSync(new URL('../registry.json', import.meta.url)));
const env = { ANTHROPIC_API_KEY: 'secret-a', XAI_API_KEY: 'secret-x', OPENROUTER_API_KEY: 'secret-o', EXTERNAL_AGENTS_ENABLE_PAID: 'true' };
const png = () => sharp({ create: { width: 7, height: 5, channels: 3, background: 'red' } }).png().toBuffer();
function fixture(backend, model) {
  if (backend === 'anthropic') return { model, content: [{ type: 'text', text: 'Answer' }], usage: { input_tokens: 11, output_tokens: 5 } };
  if (backend === 'xai') return { model, status: 'completed', output: [
    { type: 'x_search_call', status: 'completed' },
    { type: 'message', content: [{ type: 'output_text', text: 'Report https://fake.example', annotations: [{ type: 'url_citation', url: 'https://x.com/developer/status/123', title: 'A report', timestamp: '2026-09-28T00:00:00Z' }] }] },
  ], usage: { input_tokens: 10, output_tokens: 9, server_side_tool_usage_details: { x_posts_fetched: 3, x_users_fetched: 1 } } };
  return { model, choices: [{ message: { content: 'Answer' }, finish_reason: 'stop' }], usage: { prompt_tokens: 4, completion_tokens: 2, cost: 0.0001 } };
}
function setup(options = {}) {
  const calls = []; const logs = [];
  const post = async (backend, key, body) => { calls.push({ backend, key, body }); return fixture(backend, body.model); };
  const gateway = createGateway({ registry, env, adapters: createAdapters(post), log: line => logs.push(line), ...options });
  return { gateway, calls, logs };
}

test('every enabled alias routes through its registry backend and normalizes output', async () => {
  const { gateway, calls } = setup();
  for (const agent of registry.agents.filter(a => a.enabled)) {
    const result = await gateway({ agent: agent.alias, task: 'Hello', user_requested_agent: true });
    assert.equal(result.ok, true); assert.equal(result.backend, agent.backend); assert.equal(result.model, agent.model);
    assert.equal(calls.at(-1).backend, agent.backend); assert.equal(calls.at(-1).body.model, agent.model);
    assert.ok(resultSchema.safeParse(result).success); assert.ok(result.response.length > 0);
  }
});
test('all explicit-only aliases reject automatic choice before transport', async () => {
  const { gateway, calls } = setup();
  for (const agent of ['kimi', 'qwen', 'deepseek']) assert.equal((await gateway({ agent, task: 'Hello' })).error.code, 'EXPLICIT_REQUEST_REQUIRED');
  assert.equal(calls.length, 0);
});
test('auto-allowed agents require no explicit naming', async () => {
  const { gateway } = setup();
  for (const agent of ['claude', 'grok', 'gemini', 'muse']) assert.equal((await gateway({ agent, task: 'Hello' })).ok, true);
});
test('unknown, disabled, invalid inputs and capabilities never send', async () => {
  const { gateway, calls } = setup();
  for (const [input, code] of [
    [{ agent: 'not-a-model', task: 'x' }, 'INVALID_AGENT'], [{ agent: 'experimental', task: 'x' }, 'AGENT_DISABLED'],
    [{ agent: 'claude', task: 'x', mode: 'x_research' }, 'CAPABILITY_UNAVAILABLE'],
    [{ agent: 'grok', task: 'x', visual_review: true }, 'CAPABILITY_UNAVAILABLE'],
    [{ agent: 'claude', task: '', api_key: 'secret' }, 'INVALID_INPUT'],
    [{ agent: 'grok', task: 'x', mode: 'x_research', x_search: { from_date: '2026-09-29', to_date: '2026-09-28' } }, 'INVALID_INPUT'],
    [{ agent: 'grok', task: 'x', mode: 'x_research', x_search: { allowed_handles: ['x'], excluded_handles: ['y'] } }, 'INVALID_INPUT'],
  ]) assert.equal((await gateway(input)).error.code, code);
  assert.equal(calls.length, 0);
});
test('missing credentials and separate paid gate fail closed', async () => {
  for (const agent of ['claude', 'grok', 'gemini']) assert.equal((await setup({ env: {} }).gateway({ agent, task: 'x' })).error.code, 'CONFIG_REQUIRED');
  const { gateway, calls } = setup({ env: { ...env, EXTERNAL_AGENTS_ENABLE_PAID: 'false' } });
  assert.equal((await gateway({ agent: 'claude', task: 'x' })).error.code, 'PAID_CALLS_DISABLED'); assert.equal(calls.length, 0);
});
test('privacy denial and ZDR injected even for explicitly requested agents', async () => {
  const config = structuredClone(registry); config.agents.find(a => a.alias === 'kimi').privacy_profile = 'zdr';
  const { gateway, calls } = setup({ registry: config });
  for (const agent of ['gemini', 'muse', 'kimi', 'qwen', 'deepseek']) {
    const result = await gateway({ agent, task: 'x', user_requested_agent: true });
    assert.equal(result.ok, true); assert.equal(calls.at(-1).body.provider.data_collection, 'deny');
    assert.equal(calls.at(-1).body.provider.allow_fallbacks, false);
    assert.equal(calls.at(-1).body.provider.zdr, agent === 'kimi' ? true : undefined);
    assert.equal(result.policy.zdr, agent === 'kimi');
  }
});
test('privacy-incompatible endpoint returns policy/availability error once', async () => {
  let attempts = 0;
  const transport = (backend, key, body) => postJson(backend, key, body, async () => {
    attempts++; return new Response(JSON.stringify({ error: { message: 'No endpoints match privacy. secret-o' } }), { status: 404 });
  });
  const { gateway, logs } = setup({ adapters: createAdapters(transport) });
  const result = await gateway({ agent: 'kimi', task: 'private prompt', user_requested_agent: true });
  assert.equal(result.error.code, 'POLICY_OR_MODEL_UNAVAILABLE'); assert.equal(attempts, 1);
  assert.ok(!JSON.stringify([result, logs]).includes('secret-o'));
});
test('Claude accepts its explicit output ceiling without changing other routes', async () => {
  const { gateway, calls } = setup();
  assert.equal((await gateway({ agent: 'claude', task: 'hard', depth: 'deep' })).ok, true);
  assert.equal(calls[0].body.model, registry.agents[0].model); assert.equal(calls[0].body.max_tokens, 2048);
  for (const limit of [4097, 8192]) {
    const result = await gateway({ agent: 'claude', task: 'x', max_output_tokens: limit });
    assert.equal(result.ok, true); assert.equal(result.backend, 'anthropic');
    assert.equal(result.policy.max_output_tokens, limit);
    assert.equal(calls.at(-1).backend, 'anthropic'); assert.equal(calls.at(-1).body.max_tokens, limit);
  }
  assert.equal((await gateway({ agent: 'claude', task: 'x', max_output_tokens: 8193 })).error.code, 'INVALID_INPUT');
  assert.equal((await gateway({ agent: 'gemini', task: 'x', max_output_tokens: 4097 })).error.code, 'BUDGET_BLOCKED');
  assert.equal(calls.length, 3);
});
test('registry rejects unsafe privacy, duplicates and capabilities', () => {
  for (const mutate of [r => r.agents.push(r.agents[0]), r => r.agents[2].privacy_profile = 'direct', r => r.agents[0].privacy_profile = 'deny_collection', r => r.agents[0].max_output_tokens = 64, r => r.agents[2].capabilities.push('image')]) {
    const bad = structuredClone(registry); mutate(bad); assert.throws(() => validateRegistry(bad));
  }
});
test('actual decoded image bytes are in Claude request with matching evidence', async () => {
  const images = new ImageStore(); const uploaded = await images.upload(await png(), 'image/png');
  const { gateway, calls, logs } = setup({ images });
  const result = await gateway({ agent: 'claude', task: 'review', visual_review: true, asset_ids: [uploaded.asset_id], mode: 'review' });
  assert.equal(result.ok, true); assert.equal(result.images_sent[0].width, 7); assert.equal(result.images_sent[0].height, 5);
  const content = calls[0].body.messages[0].content;
  assert.equal(content[0].type, 'image'); assert.equal(content[0].source.media_type, 'image/png');
  const sent = Buffer.from(content[0].source.data, 'base64'); assert.equal((await sharp(sent).metadata()).width, 7);
  assert.ok(!JSON.stringify(logs).includes(content[0].source.data)); assert.ok(!('tools' in calls[0].body));
});
test('OpenAI file input uses same decode and image adapter as local assets', async () => {
  const images = new ImageStore({ download: async () => png() });
  const { gateway, calls } = setup({ images });
  const result = await gateway({ agent: 'claude', task: 'review', visual_review: true, image_files: [{ download_url: 'https://files.example/image', file_id: 'file-1', mime_type: 'image/png' }] });
  assert.equal(result.ok, true); assert.equal(result.images_sent[0].id, 'file-1'); assert.equal(calls[0].body.messages[0].content[0].type, 'image');
});
test('missing, expired, failed, partial and invalid images never become text-only success', async () => {
  let now = 0; const images = new ImageStore({ now: () => now, download: async () => { throw new Error('signed-url-secret'); } });
  const uploaded = await images.upload(await png(), 'image/png'); now = 901000;
  const { gateway, calls } = setup({ images });
  for (const extra of [{}, { asset_ids: [uploaded.asset_id] }, { image_files: [{ download_url: 'https://files.example/x?secret=1', file_id: 'f' }] }]) {
    const result = await gateway({ agent: 'claude', task: 'review', visual_review: true, ...extra });
    assert.equal(result.ok, false); assert.equal(result.images_sent.length, 0); assert.equal(result.response, null);
    assert.ok(!JSON.stringify(result).includes('signed-url-secret'));
  }
  assert.equal(calls.length, 0);
  await assert.rejects(validateImage(Buffer.from('not image'), 'image/png'));
  await assert.rejects(validateImage(await png(), 'image/jpeg'));
  const live = await images.upload(await png(), 'image/png');
  assert.equal((await gateway({ agent: 'claude', task: 'x', asset_ids: [live.asset_id, uploaded.asset_id] })).ok, false); assert.equal(calls.length, 0);
});
test('download rejects SSRF, userinfo, non-HTTPS and unapproved origins', () => {
  for (const address of ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1', '192.168.1.2', 'fc00::1', '0.0.0.0']) assert.equal(publicAddress(address), false);
  assert.equal(publicAddress('8.8.8.8'), true);
  for (const url of ['http://files.example/x', 'https://user:pass@files.example/x', 'https://evil.example/x', 'https://127.0.0.1/x', 'https://[::1]/x'])
    assert.throws(() => validateDownloadUrl(url, ['https://files.example', 'https://127.0.0.1', 'https://[::1]']));
});
test('native X Search request, filters, citations and item counts are preserved', async () => {
  const { gateway, calls } = setup();
  const result = await gateway({ agent: 'grok', task: 'discussion', mode: 'x_research', x_search: { allowed_handles: ['developer'], from_date: '2026-09-20' } });
  assert.equal(result.ok, true); assert.equal(calls[0].body.tools[0].type, 'x_search');
  assert.deepEqual(calls[0].body.tools[0].allowed_x_handles, ['developer']); assert.equal(calls[0].body.max_turns, 2);
  assert.equal(result.sources.length, 1); assert.equal(result.sources[0].handle, 'developer');
  assert.equal(result.sources[0].handle_provenance, 'derived_from_url'); assert.equal(result.sources[0].timestamp, '2026-09-28T00:00:00Z');
  assert.equal(result.usage.x_posts_fetched, 3); assert.equal(result.usage.x_users_fetched, 1);
  assert.equal(result.usage.x_search_calls, null); assert.equal(result.usage.cost.basis, 'unknown');
});
test('normal Grok has no search tool; unconfirmed search cannot succeed', async () => {
  const { gateway, calls } = setup(); await gateway({ agent: 'grok', task: 'hello' }); assert.equal(calls[0].body.tools, undefined);
  const { gateway: noSearch } = setup({ adapters: createAdapters(async (_, __, body) => ({ model: body.model, output: [{ type: 'message', content: [{ type: 'output_text', text: 'Invented search result' }] }] })) });
  assert.equal((await noSearch({ agent: 'grok', task: 'search', mode: 'x_research' })).error.code, 'SEARCH_UNVERIFIED');
});
test('Grok uses conservative reasoning and advisory answer length without a billing ceiling', async () => {
  const { gateway, calls } = setup();
  for (const [extra, effort] of [[{}, 'medium'], [{ x_search: { kind: 'retrieval' } }, 'low'], [{ reasoning_effort: 'high' }, 'high']]) {
    const result = await gateway({ agent: 'grok', task: 'discussion', mode: 'x_research', max_output_tokens: 8000, ...extra });
    assert.equal(result.ok, true); assert.equal(result.policy.reasoning_effort, effort);
    assert.equal(result.policy.output_limit_policy, 'advisory'); assert.equal(result.policy.guaranteed_cost_ceiling, false);
    assert.equal(calls.at(-1).body.reasoning.effort, effort); assert.equal(calls.at(-1).body.max_output_tokens, undefined);
    assert.equal(result.usage.cost.basis, 'unknown');
  }
  assert.equal(calls.length, 3);
  const { gateway: measured } = setup({ adapters: createAdapters(async (_, __, body) => ({ ...fixture('xai', body.model), usage: {
    input_tokens: 10000, output_tokens: 3000, output_tokens_details: { reasoning_tokens: 2500 },
    server_side_tool_usage_details: { x_search_calls: 10, x_posts_fetched: 44, x_users_fetched: 0 },
  } })) });
  const result = await measured({ agent: 'grok', task: 'x', mode: 'x_research', max_output_tokens: 64 });
  assert.equal(result.ok, true); assert.equal(result.usage.reasoning_tokens, 2500); assert.equal(result.usage.x_search_calls, 10);
  assert.equal(result.usage.x_posts_fetched, 44); assert.equal(result.usage.x_users_fetched, 0);
});
test('provider HTTP errors, malformed JSON and timeout use safe errors with no retries', async () => {
  for (const [status, code] of [[401, 'AUTH_FAILED'], [429, 'RATE_LIMITED'], [500, 'PROVIDER_ERROR']]) {
    let n = 0;
    await assert.rejects(postJson('anthropic', 'secret', {}, async () => { n++; return new Response('sensitive', { status }); }), e => e.code === code && !e.message.includes('sensitive'));
    assert.equal(n, 1);
  }
  await assert.rejects(postJson('xai', 'secret', {}, async () => new Response('invalid')), e => e.code === 'INVALID_PROVIDER_OUTPUT');
  await assert.rejects(postJson('xai', 'secret', {}, async () => { throw new DOMException('secret', 'TimeoutError'); }), e => e.code === 'PROVIDER_TIMEOUT');
});
test('wire request has fixed endpoint, credential header and no redirect', async () => {
  await postJson('anthropic', 'secret-a', { example: true }, async (url, init) => {
    assert.equal(url, 'https://api.anthropic.com/v1/messages'); assert.equal(init.headers['x-api-key'], 'secret-a');
    assert.equal(init.redirect, 'error'); assert.equal(init.method, 'POST'); return new Response('{}');
  });
});
test('invalid output and model substitution are rejected, no secret logging', async () => {
  for (const data of [{ model: 'expensive-alternative', choices: [{ message: { content: 'x' } }] }, { model: registry.agents[2].model, choices: [] }]) {
    const { gateway, logs } = setup({ adapters: createAdapters(async () => data) });
    const result = await gateway({ agent: 'gemini', task: 'PRIVATE_PROMPT' }); assert.equal(result.ok, false);
    assert.ok(!JSON.stringify(logs).includes('PRIVATE_PROMPT')); assert.ok(!JSON.stringify(logs).includes('secret-o'));
  }
  const { gateway, logs } = setup({ adapters: { anthropic: async () => { throw new Error('secret-a PRIVATE_PROMPT'); } } });
  const result = await gateway({ agent: 'claude', task: 'PRIVATE_PROMPT' });
  assert.ok(!JSON.stringify([result, logs]).includes('PRIVATE_PROMPT')); assert.ok(!JSON.stringify([result, logs]).includes('secret-a'));
});
test('one provider generation at a time', async () => {
  let finish; const pending = new Promise(resolve => { finish = resolve; });
  const { gateway } = setup({ adapters: createAdapters(async (_, __, body) => { await pending; return fixture('anthropic', body.model); }) });
  const first = gateway({ agent: 'claude', task: 'first' });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((await gateway({ agent: 'claude', task: 'second' })).error.code, 'BUSY');
  finish(); assert.equal((await first).ok, true);
});
test('input schema is closed to provider overrides', () => {
  for (const extra of [{ provider: { data_collection: 'allow' } }, { backend: 'xai' }, { model: 'premium' }, { api_key: 'value' }])
    assert.equal(inputSchema.safeParse({ agent: 'claude', task: 'x', ...extra }).success, false);
});

test('DNS address validation is bound to socket lookup and blocks mixed answers', async () => {
  for (const addresses of [[{ address: '127.0.0.1', family: 4 }], [{ address: '8.8.8.8', family: 4 }, { address: '10.1.1.1', family: 4 }]]) {
    await assert.rejects(new Promise((resolve, reject) => safeLookup('approved.example', {}, (e, a) => e ? reject(e) : resolve(a), (_, __, cb) => cb(null, addresses))));
  }
  const result = await new Promise((resolve, reject) => safeLookup('approved.example', { all: true }, (e, a) => e ? reject(e) : resolve(a), (_, __, cb) => cb(null, [{ address: '8.8.8.8', family: 4 }])));
  assert.deepEqual(result, [{ address: '8.8.8.8', family: 4 }]);
});
test('downloads refuse redirects and byte overflow without following another URL', async () => {
  for (const [status, body] of [[302, Buffer.from('redirect')], [200, Buffer.alloc(MAX_IMAGE + 1)]]) {
    let requests = 0;
    const get = (_, options, callback) => {
      requests++; assert.equal(options.lookup, safeLookup); assert.equal(options.agent, false);
      const response = Readable.from([body]); response.statusCode = status;
      response.headers = { location: 'http://169.254.169.254/' };
      queueMicrotask(() => callback(response)); return new EventEmitter();
    };
    await assert.rejects(downloadImage('https://files.example/image', ['https://files.example'], get));
    assert.equal(requests, 1);
  }
});
test('invalid actual model and extra provider fields cannot enter logs', async () => {
  const { gateway, logs } = setup({ adapters: { anthropic: async () => ({ model: 'secret-a', response: 'body' }) } });
  const result = await gateway({ agent: 'claude', task: 'PRIVATE_PROMPT' });
  assert.equal(result.error.code, 'MODEL_MISMATCH'); assert.ok(!JSON.stringify([result, logs]).includes('secret-a'));
});
test('search verification failure retains normalized billed usage when available', async () => {
  const { gateway } = setup({ adapters: createAdapters(async () => ({ model: 'grok-4.7', output: [], usage: { input_tokens: 42, output_tokens: 4 } })) });
  const result = await gateway({ agent: 'grok', task: 'search', mode: 'x_research' });
  assert.equal(result.error.code, 'SEARCH_UNVERIFIED'); assert.equal(result.usage.input_tokens, 42);
});
