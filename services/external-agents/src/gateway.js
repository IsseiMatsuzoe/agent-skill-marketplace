import { randomUUID } from 'node:crypto';
import { inputSchema, resultSchema, usageSchema, validateRegistry, fail, GatewayError } from './contracts.js';
import { createAdapters, keyNames } from './adapters.js';
import { ImageStore } from './images.js';

export function createGateway({ registry, env = {}, adapters = createAdapters(), images = new ImageStore(), log = record => console.error(JSON.stringify(record)) }) {
  const config = validateRegistry(registry);
  let busy = false;
  return async function callExternalAgent(raw) {
    const start = Date.now();
    const result = { request_id: randomUUID(), ok: false, agent: null, backend: null, model: null, response: null, sources: [], usage: null, policy: null, images_sent: [], warnings: [], error: null };
    let locked = false; let mode = null;
    try {
      const parsed = inputSchema.safeParse(raw);
      if (!parsed.success) fail('INVALID_INPUT', 'Input does not match the tool schema.');
      const input = parsed.data; mode = input.mode;
      const agent = config.agents.find(a => a.alias === input.agent.toLowerCase().trim());
      if (!agent) fail('INVALID_AGENT', 'Unknown logical agent alias.');
      Object.assign(result, { agent: agent.alias, backend: agent.backend, model: agent.model || null });
      if (!agent.enabled) fail('AGENT_DISABLED', 'This logical agent is disabled in the registry.');
      if (agent.selection_policy === 'explicit_only' && !input.user_requested_agent)
        fail('EXPLICIT_REQUEST_REQUIRED', 'This agent requires the user to explicitly request it.');
      if (!agent.capabilities.includes(input.mode)) fail('CAPABILITY_UNAVAILABLE', 'This agent does not support the requested mode.');
      if ((input.visual_review || input.asset_ids.length || input.image_files.length) && !agent.capabilities.includes('image'))
        fail('CAPABILITY_UNAVAILABLE', 'This agent adapter does not support image input.');
      if (input.x_search && input.mode !== 'x_research') fail('INVALID_INPUT', 'Search filters require x_research mode.');
      if (input.x_search?.allowed_handles && input.x_search?.excluded_handles) fail('INVALID_INPUT', 'Choose allowed or excluded handles, not both.');
      if (input.x_search?.from_date && input.x_search?.to_date && input.x_search.from_date > input.x_search.to_date)
        fail('INVALID_INPUT', 'Search dates are reversed.');
      input.max_output_tokens ??= agent.default_max_output_tokens;
      input.depth ??= agent.default_depth;
      if (input.max_output_tokens > agent.max_output_tokens) fail('BUDGET_BLOCKED', 'Requested output limit exceeds the registry ceiling.');
      const policy = { selection: agent.selection_policy, privacy: agent.privacy_profile,
        data_collection: agent.backend === 'openrouter' ? 'deny' : null, zdr: agent.privacy_profile === 'zdr', cross_model_fallback: false,
        depth: input.depth, max_output_tokens: input.max_output_tokens, x_search_max_turns: input.mode === 'x_research' ? agent.max_search_turns : null };
      result.policy = policy;
      const key = env[keyNames[agent.backend]];
      if (!key?.trim()) fail('CONFIG_REQUIRED', `Set ${keyNames[agent.backend]} in the local secret file; never paste it into chat.`);
      if (env.EXTERNAL_AGENTS_ENABLE_PAID !== 'true') fail('PAID_CALLS_DISABLED', 'Owner must knowingly enable paid calls locally after mock tests.');
      if (busy) fail('BUSY', 'One request is already in progress. No retry was made.');
      busy = true; locked = true;
      const sent = await images.resolve(input);
      const normalized = await adapters[agent.backend]({ agent, input, images: sent, key, policy });
      if (usageSchema.safeParse(normalized.usage).success) result.usage = normalized.usage;
      if (typeof normalized.response !== 'string' || !normalized.response.trim() || typeof normalized.model !== 'string' || !normalized.model)
        fail('INVALID_PROVIDER_OUTPUT', 'Provider returned no usable response or actual model.');
      const datedSnapshot = agent.backend === 'anthropic' && normalized.model.startsWith(`${agent.model}-`) && /^\d{8}$/.test(normalized.model.slice(agent.model.length + 1));
      if (normalized.model !== agent.model && !datedSnapshot)
        fail('MODEL_MISMATCH', 'Provider reported an unexpected model; no substitute is accepted.');
      const candidate = { ...result, model: normalized.model, response: normalized.response, sources: normalized.sources, usage: normalized.usage, warnings: normalized.warnings, ok: true, images_sent: sent.map(({ bytes, ...metadata }) => metadata) };
      if (!resultSchema.safeParse(candidate).success) fail('INVALID_PROVIDER_OUTPUT', 'Normalized provider output failed validation.');
      Object.assign(result, candidate);
      if (input.depth !== 'standard') result.warnings.push('DEPTH_IS_ANSWER_DETAIL_NOT_A_COMPUTE_OR_PRICE_GUARANTEE');
      if (agent.backend !== 'openrouter') result.warnings.push('DIRECT_PROVIDER_RETENTION_DEPENDS_ON_ACCOUNT_TERMS');
      if (input.visual_review) result.warnings.push('IMAGE_RECEIPT_MEANS_BYTES_INCLUDED_IN_ACCEPTED_REQUEST_NOT_PROOF_OF_UNDERSTANDING');
      if (!resultSchema.safeParse(result).success) fail('INVALID_PROVIDER_OUTPUT', 'Normalized provider output failed validation.');
    } catch (error) {
      // Never expose exceptions, request bodies, provider error payloads or signed URLs.
      result.ok = false; result.response = null; result.sources = []; result.images_sent = []; result.warnings = [];
      if (error instanceof GatewayError && usageSchema.safeParse(error.usage).success) result.usage = error.usage;
      result.error = { code: error instanceof GatewayError ? error.code : 'PROVIDER_ERROR',
        message: error instanceof GatewayError ? error.message : 'External agent request failed; no retry was made.', retryable: false };
    } finally {
      if (locked) busy = false;
    }
    const safe = resultSchema.parse(result);
    // Deliberately construct the log allowlist. Neither output nor exception objects reach logging.
    log({ request_id: safe.request_id, agent: safe.agent, backend: safe.backend, model: safe.model,
      mode, elapsed_ms: Date.now() - start, usage: safe.usage, status: safe.ok ? 'success' : safe.error.code });
    return safe;
  };
}
