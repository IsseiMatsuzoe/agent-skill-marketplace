import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createGateway } from '../src/gateway.js';
import { createAdapters } from '../src/adapters.js';
import { validateRegistry } from '../src/contracts.js';

const defaults = JSON.parse(readFileSync(new URL('../registry.json', import.meta.url)));
function setup(registry = structuredClone(defaults), reject = false) {
  const calls = [];
  const adapters = createAdapters(async (backend, key, body) => {
    calls.push({ backend, body });
    if (reject) throw new Error('Unavailable');
    if (backend === 'anthropic') return { model: body.model, content: [{ type: 'text', text: 'Answer' }] };
    if (backend === 'xai') return { model: body.model, output: [{ type: 'message', content: [{ type: 'output_text', text: 'Answer' }] }] };
    return { model: body.model, choices: [{ message: { content: 'Answer' } }] };
  });
  const gateway = createGateway({ registry, adapters, log: () => {}, env: {
    ANTHROPIC_API_KEY: 'test', XAI_API_KEY: 'test', OPENROUTER_API_KEY: 'test', EXTERNAL_AGENTS_ENABLE_PAID: 'true',
  } });
  return { gateway, calls };
}

test('automatic OpenRouter calls pin approved serving hosts with deny and no fallback', async () => {
  const { gateway, calls } = setup();
  for (const agent of ['gemini', 'muse']) {
    const result = await gateway({ agent, task: 'A second opinion' });
    assert.equal(result.ok, true);
    assert.equal(result.policy.selection, 'auto_allowed');
    assert.deepEqual(result.policy.provider_only, defaults.routing.openrouter.approved_providers);
    assert.deepEqual(calls.at(-1).body.provider, {
      only: defaults.routing.openrouter.approved_providers,
      data_collection: 'deny', allow_fallbacks: false, require_parameters: true,
    });
  }
});

test('provider promotion and demotion apply independently of model names and aliases', async () => {
  const registry = structuredClone(defaults);
  registry.routing.openrouter.approved_model_providers = ['qwen'];
  registry.routing.openrouter.approved_providers = ['alibaba'];
  registry.agents.find(a => a.alias === 'qwen').model = 'qwen/a-future-reviewed-model';
  const { gateway, calls } = setup(registry);
  assert.equal((await gateway({ agent: 'gemini', task: 'x' })).error.code, 'EXPLICIT_REQUEST_REQUIRED');
  assert.equal(calls.length, 0);
  const result = await gateway({ agent: 'qwen', task: 'x' });
  assert.equal(result.ok, true);
  assert.equal(result.model, 'qwen/a-future-reviewed-model');
  assert.deepEqual(calls[0].body.provider.only, ['alibaba']);
  // An alias cannot grant trust to a different model publisher.
  registry.agents.find(a => a.alias === 'gemini').model = 'unreviewed/some-model';
  assert.equal((await setup(registry).gateway({ agent: 'gemini', task: 'x' })).error.code, 'EXPLICIT_REQUEST_REQUIRED');
});

test('explicit families use only configured hosts and keep deny and ZDR', async () => {
  const registry = structuredClone(defaults);
  registry.agents.find(a => a.alias === 'kimi').privacy_profile = 'zdr';
  const { gateway, calls } = setup(registry);
  for (const [agent, hosts] of [['kimi', ['novita']], ['qwen', ['alibaba']], ['deepseek', ['deepseek']]]) {
    assert.equal((await gateway({ agent, task: 'x' })).error.code, 'EXPLICIT_REQUEST_REQUIRED');
    const result = await gateway({ agent, task: 'x', user_requested_agent: true });
    assert.equal(result.ok, true);
    assert.equal(result.policy.selection, 'explicit_only');
    assert.deepEqual(calls.at(-1).body.provider.only, hosts);
    assert.equal(calls.at(-1).body.provider.data_collection, 'deny');
    assert.equal(calls.at(-1).body.provider.allow_fallbacks, false);
    assert.equal(calls.at(-1).body.provider.zdr, agent === 'kimi' ? true : undefined);
  }
  assert.equal(calls.length, 3);
});

test('unreviewed new families default explicit-only, with no arbitrary endpoint access', async () => {
  const registry = structuredClone(defaults);
  Object.assign(registry.agents.find(a => a.alias === 'experimental'), { enabled: true, model: 'new-family/model' });
  const { gateway, calls } = setup(registry);
  assert.equal((await gateway({ agent: 'experimental', task: 'x' })).error.code, 'EXPLICIT_REQUEST_REQUIRED');
  assert.equal(calls.length, 0);
  assert.equal((await gateway({ agent: 'experimental', task: 'x', user_requested_agent: true })).ok, true);
  assert.deepEqual(calls[0].body.provider.only, defaults.routing.openrouter.approved_providers);
});

test('empty automatic and explicit allowlists fail before sending, without escalation', async () => {
  const registry = structuredClone(defaults);
  registry.routing.openrouter.approved_providers = [];
  registry.routing.openrouter.explicit_providers.moonshotai = [];
  const { gateway, calls } = setup(registry);
  for (const request of [{ agent: 'gemini' }, { agent: 'gemini', user_requested_agent: true }, { agent: 'kimi', user_requested_agent: true }]) {
    const result = await gateway({ ...request, task: 'x' });
    assert.equal(result.error.code, 'POLICY_OR_MODEL_UNAVAILABLE');
    assert.equal(result.error.retryable, false);
  }
  assert.equal(calls.length, 0);
  await assert.rejects(createAdapters(async () => { throw new Error('Must not send'); }).openrouter({ policy: {} }), e => e.code === 'POLICY_OR_MODEL_UNAVAILABLE');
});

test('automatic routes never inherit an explicit-only hosting exception', async () => {
  const registry = structuredClone(defaults);
  registry.routing.openrouter.explicit_providers.google = ['unapproved-host'];
  const { gateway, calls } = setup(registry);
  assert.equal((await gateway({ agent: 'gemini', task: 'x' })).ok, true);
  assert.deepEqual(calls[0].body.provider.only, defaults.routing.openrouter.approved_providers);
});

test('direct provider demotion and premium profiles require explicit choice without changing model', async () => {
  const registry = structuredClone(defaults);
  registry.routing.direct.xai = 'explicit_only';
  registry.agents.find(a => a.alias === 'claude').premium = true;
  const { gateway, calls } = setup(registry);
  for (const agent of ['grok', 'claude']) {
    assert.equal((await gateway({ agent, task: 'x' })).error.code, 'EXPLICIT_REQUEST_REQUIRED');
    const result = await gateway({ agent, task: 'x', user_requested_agent: true });
    assert.equal(result.ok, true);
    assert.equal(result.model, registry.agents.find(a => a.alias === agent).model);
    assert.equal(result.policy.provider_only, null);
  }
  assert.equal(calls.length, 2);
});

test('failed allowed route makes one attempt without relaxing provider or data policy', async () => {
  const { gateway, calls } = setup(structuredClone(defaults), true);
  const result = await gateway({ agent: 'gemini', task: 'x' });
  assert.equal(result.ok, false); assert.equal(result.error.retryable, false);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].body.provider.data_collection, 'deny');
  assert.deepEqual(calls[0].body.provider.only, defaults.routing.openrouter.approved_providers);
});

test('registry rejects legacy trust, malformed routes and model routing variants', () => {
  for (const change of [r => r.version = 1, r => delete r.routing,
    r => r.agents[0].selection_policy = 'auto_allowed',
    r => r.routing.openrouter.approved_providers = ['*'],
    r => r.routing.openrouter.approved_providers = ['meta', 'meta'],
    r => r.routing.openrouter.explicit_providers.qwen = ['https://example.org'],
    r => r.agents.find(agent => agent.alias === 'qwen').model = 'qwen/unsafe-model:free']) {
    const registry = structuredClone(defaults); change(registry);
    assert.throws(() => validateRegistry(registry));
  }
});

test('multilingual prose, equations, code and arbitrary context survive every adapter unchanged', async () => {
  const task = 'Explain the attached relation. Answer in Japanese.\nこの式の意味を説明して。';
  const context = 'Earlier decision: 境界条件は固定。\n\\[C_{AB}(t)=\\langle A(t)B(0)\\rangle\\]\n```js\nconst x = "日本語";\n```\nrepo/\n  src/';
  const attachment = 'Original passage: α ≠ β\nDefinitions: A is an operator.\n改行を保存。';
  const { gateway, calls } = setup();
  for (const agent of ['claude', 'grok', 'gemini']) {
    assert.equal((await gateway({ agent, task, context, attachments: [{ name: '選択部分.txt', text: attachment }] })).ok, true);
    const { backend, body } = calls.at(-1);
    const text = backend === 'anthropic' ? body.messages[0].content.at(-1).text : backend === 'xai' ? body.input[0].content : body.messages[0].content;
    for (const original of [task, context, attachment]) assert.ok(text.includes(original));
  }
});
