import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createGateway } from '../src/gateway.js';
import { createAdapters, DEFAULT_TIMEOUTS, postJson, timeoutProfileFor } from '../src/adapters.js';
import { validateRegistry } from '../src/contracts.js';

const registry = JSON.parse(readFileSync(new URL('../registry.json', import.meta.url)));
const env = { ANTHROPIC_API_KEY: 'test-anthropic-key', XAI_API_KEY: 'test-xai-key', OPENROUTER_API_KEY: 'test-openrouter-key', EXTERNAL_AGENTS_ENABLE_PAID: 'true' };
const frame = (type, fields = {}) => `event: ${type}\ndata: ${JSON.stringify({ type, ...fields })}\n\n`;
const streamResponse = frames => new Response(frames.join(''), { headers: { 'Content-Type': 'text/event-stream' } });
const anthropicStart = (model = 'claude-sonnet-5-5', usage = { input_tokens: 17 }) => frame('message_start', { message: { model, usage } });
const flush = () => new Promise(resolve => setImmediate(resolve));

function manualTimers() {
  let clock = 0; let nextId = 0; const jobs = new Map();
  return {
    setTimeout(callback, delay) { const id = ++nextId; jobs.set(id, { at: clock + delay, callback }); return id; },
    clearTimeout(id) { jobs.delete(id); },
    now() { return clock; },
    advance(ms) {
      const target = clock + ms;
      while (true) {
        const due = [...jobs.entries()].filter(([, job]) => job.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        const [id, job] = due; jobs.delete(id); clock = job.at; job.callback();
      }
      clock = target;
    },
  };
}

function gatewayFor(fetchImpl, timeoutConfig) {
  const calls = []; const logs = [];
  const transport = (backend, key, body, _fetch, options) => postJson(backend, key, body, (url, init) => {
    calls.push({ backend, url, init, body: JSON.parse(init.body) });
    return fetchImpl(url, init);
  }, { ...options, ...(timeoutConfig ? { timeoutConfig } : {}) });
  const gateway = createGateway({ registry, env, adapters: createAdapters(transport), log: value => logs.push(value) });
  return { gateway, calls, logs };
}

test('Anthropic adaptive stream keeps thinking private, returns visible text and safe usage diagnostics', async () => {
  const { gateway, calls, logs } = gatewayFor(async () => streamResponse([
    anthropicStart('claude-sonnet-5-5', { input_tokens: 17, cache_read_input_tokens: 3, cache_creation_input_tokens: 2 }),
    frame('content_block_start', { index: 0, content_block: { type: 'thinking' } }),
    frame('content_block_delta', { index: 0, delta: { type: 'thinking_delta', thinking: 'PRIVATE_CHAIN_OF_THOUGHT' } }),
    frame('content_block_stop', { index: 0 }),
    frame('content_block_start', { index: 1, content_block: { type: 'text', text: '' } }),
    frame('content_block_delta', { index: 1, delta: { type: 'text_delta', text: 'Visible answer' } }),
    frame('message_delta', { delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 29, output_tokens_details: { text_tokens: 11, thinking_tokens: 18 } } }),
    frame('message_stop'),
  ]));
  const result = await gateway({ agent: 'claude', task: 'safe test' });
  assert.equal(result.ok, true); assert.equal(result.response, 'Visible answer');
  assert.equal(result.usage.input_tokens, 17); assert.equal(result.usage.output_tokens, 29);
  assert.equal(result.usage.cache_read_tokens, 3); assert.equal(result.usage.cache_write_tokens, 2);
  assert.equal(result.usage.reasoning_tokens, 18);
  assert.equal(result.diagnostics.stop_reason, 'end_turn'); assert.deepEqual(result.diagnostics.content_block_counts, { thinking: 1, text: 1 });
  assert.equal(result.diagnostics.visible_text_blocks, 1); assert.equal(result.diagnostics.visible_text_characters, 14);
  assert.equal(result.diagnostics.thinking_block_count, 1); assert.equal(result.diagnostics.thinking_block_present, true);
  assert.equal(result.policy.answer_target_tokens, 2048); assert.equal(result.policy.provider_generation_ceiling, 128000);
  assert.equal(calls[0].body.max_tokens, 128000); assert.deepEqual(calls[0].body.thinking, { type: 'adaptive' });
  assert.deepEqual(calls[0].body.output_config, { effort: 'medium' }); assert.equal(calls[0].body.stream, true);
  assert.ok(!JSON.stringify([result, logs]).includes('PRIVATE_CHAIN_OF_THOUGHT'));
});

test('Anthropic thinking-only max_tokens exhaustion returns typed error with usage and safe diagnostics', async () => {
  const { gateway, logs } = gatewayFor(async () => streamResponse([
    anthropicStart('claude-sonnet-5-5', { input_tokens: 8 }),
    frame('content_block_start', { index: 0, content_block: { type: 'thinking' } }),
    frame('content_block_delta', { index: 0, delta: { type: 'thinking_delta', thinking: 'PRIVATE_REASONING' } }),
    frame('message_delta', { delta: { stop_reason: 'max_tokens' }, usage: { output_tokens: 128000 } }),
    frame('message_stop'),
  ]));
  const result = await gateway({ agent: 'claude', task: 'budget regression' });
  assert.equal(result.error.code, 'OUTPUT_BUDGET_EXHAUSTED'); assert.equal(result.usage.output_tokens, 128000);
  assert.equal(result.diagnostics.stop_reason, 'max_tokens'); assert.equal(result.diagnostics.visible_text_characters, 0);
  assert.equal(result.diagnostics.thinking_block_count, 1); assert.ok(!JSON.stringify([result, logs]).includes('PRIVATE_REASONING'));
});

test('Anthropic max_tokens with partial visible text succeeds and warns OUTPUT_TRUNCATED', async () => {
  const { gateway } = gatewayFor(async () => streamResponse([
    anthropicStart(),
    frame('content_block_start', { index: 0, content_block: { type: 'text', text: '' } }),
    frame('content_block_delta', { index: 0, delta: { type: 'text_delta', text: 'Partial but useful' } }),
    frame('message_delta', { delta: { stop_reason: 'max_tokens' }, usage: { output_tokens: 128000 } }),
    frame('message_stop'),
  ]));
  const result = await gateway({ agent: 'claude', task: 'partial regression' });
  assert.equal(result.ok, true); assert.equal(result.response, 'Partial but useful');
  assert.ok(result.warnings.includes('OUTPUT_TRUNCATED')); assert.equal(result.usage.output_tokens, 128000);
});

test('Anthropic explicit stream error is normalized immediately with no retry', async () => {
  const { gateway, calls, logs } = gatewayFor(async () => streamResponse([
    frame('error', { error: { type: 'rate_limit_error', message: 'PRIVATE_PROVIDER_ERROR_BODY' } }),
  ]));
  const result = await gateway({ agent: 'claude', task: 'error regression' });
  assert.equal(result.error.code, 'RATE_LIMITED'); assert.equal(calls.length, 1);
  assert.ok(!JSON.stringify([result, logs]).includes('PRIVATE_PROVIDER_ERROR_BODY'));
});

test('accepted Anthropic stream interruption has uncertain outcome semantics and no retry', async () => {
  let sends = 0; let reads = 0;
  const { gateway, calls } = gatewayFor(async () => {
    sends++;
    return new Response(new ReadableStream({ pull(controller) {
      if (reads++ === 0) controller.enqueue(new TextEncoder().encode(anthropicStart()));
      else controller.error(new Error('PRIVATE_TRANSPORT_DETAIL'));
    } }));
  });
  const result = await gateway({ agent: 'claude', task: 'interrupt regression' });
  assert.equal(result.error.code, 'STREAM_INTERRUPTED'); assert.match(result.error.message, /billing may already have occurred/i);
  assert.equal(sends, 1); assert.equal(calls.length, 1);
});

test('idle timeout resets for ping, reasoning, text and X Search progress events', async () => {
  const timers = manualTimers(); let controller;
  const bodyStream = new ReadableStream({ start(value) { controller = value; } });
  const pending = postJson('xai', 'fake', { model: 'grok-4.7', stream: true }, async () => new Response(bodyStream), {
    timers, now: timers.now, timeoutProfile: 'ordinary_10m',
    timeoutConfig: { connectionMs: 40, idleMs: 10, ordinaryMs: 200, extendedMs: 300 },
  });
  let settled = false; pending.finally(() => { settled = true; }).catch(() => {});
  await flush();
  const send = async value => { controller.enqueue(new TextEncoder().encode(value)); await flush(); };
  timers.advance(8); await send('event: ping\n\n');
  timers.advance(8); await send(frame('response.created', { response: { model: 'grok-4.7', status: 'in_progress' } }));
  timers.advance(8); await send(frame('response.reasoning_summary_text.delta', { delta: 'PRIVATE_REASONING_SUMMARY' }));
  timers.advance(8); await send(frame('response.output_item.added', { item: { id: 'search-1', type: 'x_search_call', status: 'in_progress' } }));
  timers.advance(8); await send(frame('response.output_text.delta', { delta: 'Visible search report' }));
  assert.equal(settled, false);
  const final = { model: 'grok-4.7', status: 'completed', output: [
    { id: 'search-1', type: 'x_search_call', status: 'completed' },
    { type: 'message', content: [{ type: 'output_text', text: 'Visible search report' }] },
  ] };
  controller.enqueue(new TextEncoder().encode(frame('response.completed', { response: final }))); controller.close();
  const result = await pending;
  assert.equal(result.status, 'completed'); assert.equal(result.diagnostics.x_search_calls_completed, 1);
  assert.ok(!JSON.stringify(result).includes('PRIVATE_REASONING_SUMMARY'));
});

test('idle timeout fires on configured inactivity without a real wait', async () => {
  const timers = manualTimers(); const bodyStream = new ReadableStream({ start() {} });
  const pending = postJson('anthropic', 'fake', { stream: true }, async () => new Response(bodyStream), {
    timers, now: timers.now, timeoutProfile: 'ordinary_10m',
    timeoutConfig: { connectionMs: 40, idleMs: 12, ordinaryMs: 200, extendedMs: 300 },
  }).then(value => ({ value }), error => ({ error }));
  await flush(); timers.advance(12);
  const result = await pending;
  assert.equal(result.error.code, 'IDLE_TIMEOUT'); assert.equal(result.error.diagnostics.timeout_layer, 'idle');
});

test('connection/header timeout is distinct and fires before response acceptance', async () => {
  const timers = manualTimers(); let sends = 0;
  const pending = postJson('anthropic', 'fake', { stream: true }, async () => { sends++; return new Promise(() => {}); }, {
    timers, now: timers.now, timeoutProfile: 'ordinary_10m',
    timeoutConfig: { connectionMs: 9, idleMs: 12, ordinaryMs: 200, extendedMs: 300 },
  }).then(value => ({ value }), error => ({ error }));
  await flush(); timers.advance(9);
  const result = await pending;
  assert.equal(result.error.code, 'CONNECTION_TIMEOUT'); assert.equal(result.error.diagnostics.timeout_layer, 'connection');
  assert.equal(sends, 1);
});

test('absolute timeout uses 10 minute ordinary and 30 minute deep/X-research profiles', async () => {
  assert.equal(timeoutProfileFor({ mode: 'general', depth: 'standard' }), 'ordinary_10m');
  assert.equal(timeoutProfileFor({ mode: 'general', depth: 'deep' }), 'extended_30m');
  assert.equal(timeoutProfileFor({ mode: 'x_research', depth: 'brief' }), 'extended_30m');
  assert.deepEqual(DEFAULT_TIMEOUTS, { connectionMs: 30000, idleMs: 300000, ordinaryMs: 600000, extendedMs: 1800000 });
  for (const [profile, duration] of [['ordinary_10m', 30], ['extended_30m', 60]]) {
    const timers = manualTimers(); const bodyStream = new ReadableStream({ start() {} });
    const pending = postJson('xai', 'fake', { stream: true }, async () => new Response(bodyStream), {
      timers, now: timers.now, timeoutProfile: profile,
      timeoutConfig: { connectionMs: 5, idleMs: 100, ordinaryMs: 30, extendedMs: 60 },
    }).then(value => ({ value }), error => ({ error }));
    await flush(); timers.advance(duration - 1); await flush();
    timers.advance(1);
    const result = await pending;
    assert.equal(result.error.code, 'ABSOLUTE_TIMEOUT'); assert.equal(result.error.diagnostics.timeout_layer, 'absolute');
  }
});

test('xAI X Search streaming verifies native search and normalizes citations, usage and status', async () => {
  const response = { model: 'grok-4.7', status: 'completed', output: [
    { id: 'x-1', type: 'x_search_call', status: 'completed' },
    { type: 'message', content: [{ type: 'output_text', text: 'Report [[1]]', annotations: [
      { type: 'url_citation', url: 'https://x.com/maintainer/status/42', title: 'Public post' },
    ] }] },
  ], usage: { input_tokens: 25, output_tokens: 19, output_tokens_details: { reasoning_tokens: 12, text_tokens: 7 }, server_side_tool_usage_details: { x_search_calls: 1, x_posts_fetched: 4, x_users_fetched: 2 } } };
  const { gateway, calls } = gatewayFor(async () => streamResponse([
    frame('response.created', { response: { model: 'grok-4.7', status: 'in_progress' } }),
    frame('response.output_item.added', { output_index: 0, item: { id: 'x-1', type: 'x_search_call', status: 'in_progress' } }),
    frame('response.output_item.done', { output_index: 0, item: { id: 'x-1', type: 'x_search_call', status: 'completed' } }),
    frame('response.output_text.delta', { delta: 'Report [[1]]' }),
    frame('response.completed', { response }),
  ]));
  const result = await gateway({ agent: 'grok', task: 'find a discussion', mode: 'x_research', x_search: { allowed_handles: ['maintainer'], from_date: '2026-09-20' }, max_output_tokens: 512 });
  assert.equal(result.ok, true); assert.equal(result.response, 'Report [[1]]');
  assert.equal(calls[0].body.stream, true); assert.equal(calls[0].body.store, false);
  assert.equal(calls[0].body.tools[0].type, 'x_search'); assert.deepEqual(calls[0].body.tools[0].allowed_x_handles, ['maintainer']);
  assert.equal(calls[0].body.max_turns, 2); assert.equal(calls[0].body.max_output_tokens, undefined);
  assert.match(calls[0].body.input[0].content, /answer target: 512 tokens/i);
  assert.equal(result.sources[0].handle, 'maintainer'); assert.equal(result.sources[0].url, 'https://x.com/maintainer/status/42');
  assert.equal(result.usage.x_search_calls, 1); assert.equal(result.usage.x_posts_fetched, 4); assert.equal(result.usage.x_users_fetched, 2);
  assert.equal(result.usage.reasoning_tokens, 12); assert.equal(result.usage.text_tokens, 7);
  assert.equal(result.diagnostics.status, 'completed'); assert.equal(result.diagnostics.x_search_calls_completed, 1);
  assert.equal(result.diagnostics.tool_event_counts.x_search, 1);
  assert.equal(result.policy.timeout_profile, 'extended_30m'); assert.equal(result.policy.provider_generation_ceiling, null);
});

test('xAI failed X Search output_item.done is not accepted as search success', async () => {
  const { gateway, calls } = gatewayFor(async () => streamResponse([
    frame('response.created', { response: { model: 'grok-4.7', status: 'in_progress' } }),
    frame('response.output_item.added', { output_index: 0, item: { id: 'x-failed', type: 'x_search_call', status: 'in_progress' } }),
    frame('response.output_item.done', { output_index: 0, item: { id: 'x-failed', type: 'x_search_call', status: 'failed' } }),
    frame('response.output_text.delta', { delta: 'Generated without verified search' }),
    frame('response.completed', { response: {
      model: 'grok-4.7', status: 'completed',
      output: [
        { id: 'x-failed', type: 'x_search_call', status: 'failed' },
        { type: 'message', content: [{ type: 'output_text', text: 'Generated without verified search' }] },
      ],
      usage: { input_tokens: 10, output_tokens: 6, server_side_tool_usage_details: { x_search_calls: 0, x_posts_fetched: 0, x_users_fetched: 0 } },
    } }),
  ]));
  const result = await gateway({ agent: 'grok', task: 'verify recent discussion', mode: 'x_research' });
  assert.equal(result.error.code, 'SEARCH_UNVERIFIED');
  assert.equal(result.diagnostics.x_search_calls_completed, 0);
  assert.equal(result.diagnostics.tool_event_counts.x_search, 1);
  assert.equal(calls.length, 1);
});

test('xAI terminal search usage confirms X Search without an output item', async () => {
  const { gateway } = gatewayFor(async () => streamResponse([
    frame('response.created', { response: { model: 'grok-4.7', status: 'in_progress' } }),
    frame('response.output_text.delta', { delta: 'Terminal usage confirms the search' }),
    frame('response.completed', { response: {
      model: 'grok-4.7', status: 'completed',
      output: [{ type: 'message', content: [{ type: 'output_text', text: 'Terminal usage confirms the search' }] }],
      usage: { input_tokens: 10, output_tokens: 6, server_side_tool_usage_details: { x_posts_fetched: 2 } },
    } }),
  ]));
  const result = await gateway({ agent: 'grok', task: 'verify recent discussion', mode: 'x_research' });
  assert.equal(result.ok, true);
  assert.equal(result.diagnostics.x_search_calls_completed, 1);
  assert.equal(result.usage.x_posts_fetched, 2);
});

test('xAI final diagnostics only retain a safe returned model identifier', async () => {
  const result = await postJson('xai', 'fake', { stream: true }, async () => streamResponse([
    frame('response.created', { response: { model: 'grok-4.7', status: 'in_progress' } }),
    frame('response.completed', { response: {
      model: 'grok-4.7\nPRIVATE_MODEL_METADATA', status: 'completed', output: [],
    } }),
  ]));
  assert.equal(result.model, 'grok-4.7\nPRIVATE_MODEL_METADATA');
  assert.equal(result.diagnostics.returned_model, null);
});

test('xAI explicit provider stream failure is normalized immediately with no retry', async () => {
  const { gateway, calls, logs } = gatewayFor(async () => streamResponse([
    frame('response.failed', { response: { status: 'failed', error: { type: 'server_error', message: 'PRIVATE_PROVIDER_ERROR_BODY' } } }),
  ]));
  const result = await gateway({ agent: 'grok', task: 'provider failure' });
  assert.equal(result.error.code, 'PROVIDER_ERROR'); assert.equal(calls.length, 1);
  assert.ok(!JSON.stringify([result, logs]).includes('PRIVATE_PROVIDER_ERROR_BODY'));
});

test('Claude Opus validates as explicit premium and never replaces normal Sonnet routing', async () => {
  validateRegistry(registry);
  const opus = registry.agents.find(agent => agent.alias === 'claude-opus');
  assert.equal(opus.backend, 'anthropic'); assert.equal(opus.model, 'claude-opus-5-5');
  assert.equal(opus.premium, true); assert.deepEqual(opus.capabilities, registry.agents[0].capabilities);
  const calls = [];
  const adapters = createAdapters(async (backend, _key, body) => {
    calls.push({ backend, body });
    return { model: body.model, content: [{ type: 'text', text: 'answer' }], usage: { input_tokens: 2, output_tokens: 2 } };
  });
  const gateway = createGateway({ registry, env, adapters, log: () => {} });
  const sonnet = await gateway({ agent: 'claude', task: 'normal Claude' });
  assert.equal(sonnet.ok, true); assert.equal(sonnet.model, 'claude-sonnet-5-5'); assert.equal(calls.length, 1);
  assert.equal((await gateway({ agent: 'claude-opus', task: 'automatic' })).error.code, 'EXPLICIT_REQUEST_REQUIRED');
  assert.equal(calls.length, 1);
  const explicit = await gateway({ agent: 'claude-opus', task: 'Opus please', user_requested_agent: true });
  assert.equal(explicit.ok, true); assert.equal(explicit.model, 'claude-opus-5-5');
  assert.equal(explicit.policy.selection, 'explicit_only'); assert.equal(calls.length, 2);
  assert.equal(calls[1].body.model, 'claude-opus-5-5');
  const mismatchGateway = createGateway({ registry, env, adapters: createAdapters(async () => ({ model: 'claude-sonnet-5-5', content: [{ type: 'text', text: 'wrong model' }] })), log: () => {} });
  const mismatch = await mismatchGateway({ agent: 'claude-opus', task: 'Opus only', user_requested_agent: true });
  assert.equal(mismatch.error.code, 'MODEL_MISMATCH');
  const unsafe = structuredClone(registry); unsafe.agents.find(agent => agent.alias === 'claude-opus').premium = false;
  assert.throws(() => validateRegistry(unsafe));
});
