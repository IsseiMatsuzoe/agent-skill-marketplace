import { z } from 'zod';

export const modes = ['general', 'design', 'review', 'x_research', 'rewrite'];
export const depths = ['brief', 'standard', 'deep'];
const short = z.string().max(512);
const count = z.number().nonnegative().finite().nullable();
export const fileSchema = z.object({
  download_url: z.string().url().max(8192), file_id: short,
  mime_type: short.optional(), file_name: short.optional(),
}).strict();
export const inputSchema = z.object({
  agent: z.string().min(1).max(64), task: z.string().min(1).max(32000),
  mode: z.enum(modes).default('general'), context: z.string().max(64000).optional(),
  depth: z.enum(depths).optional(), max_output_tokens: z.number().int().min(64).max(8192).optional(),
  reasoning_effort: z.enum(['low', 'medium', 'high']).optional().describe('Optional reasoning preference. High only for explicit user intent or a clearly demanding task; never a billing guarantee.'),
  user_requested_agent: z.boolean().default(false).describe('True only when the user explicitly named this logical agent. Caller attestation, not inferred from task difficulty.'),
  visual_review: z.boolean().default(false).describe('Require actual image transfer for visual critique.'),
  image_files: z.array(fileSchema).max(3).default([]),
  asset_ids: z.array(z.string().uuid()).max(3).default([]),
  attachments: z.array(z.object({ name: short, text: z.string().max(32000) }).strict()).max(3).default([]),
  x_search: z.object({
    kind: z.enum(['discussion', 'retrieval']).default('discussion'),
    from_date: z.string().date().optional(), to_date: z.string().date().optional(),
    allowed_handles: z.array(z.string().regex(/^[A-Za-z0-9_]{1,15}$/)).max(20).optional(),
    excluded_handles: z.array(z.string().regex(/^[A-Za-z0-9_]{1,15}$/)).max(20).optional(),
  }).strict().optional(),
}).strict();

export const usageSchema = z.object({
  input_tokens: count, output_tokens: count, reasoning_tokens: count,
  cache_read_tokens: count, cache_write_tokens: count,
  x_posts_fetched: count, x_users_fetched: count, x_search_calls: count,
  cost: z.object({ amount: count, currency: z.literal('USD'), basis: z.enum(['provider_reported', 'unknown']) }),
}).strict();
export const resultSchema = z.object({
  request_id: z.string().uuid(), ok: z.boolean(), agent: z.string().nullable(),
  backend: z.string().nullable(), model: z.string().nullable(),
  response: z.string().nullable(),
  sources: z.array(z.object({ url: z.string(), title: z.string().nullable(), handle: z.string().nullable(), timestamp: z.string().nullable(), provenance: z.literal('provider_citation'), handle_provenance: z.enum(['provider', 'derived_from_url']).nullable() }).strict()),
  usage: usageSchema.nullable(),
  policy: z.object({ selection: z.string(), privacy: z.string(), data_collection: z.literal('deny').nullable(), zdr: z.boolean(), cross_model_fallback: z.literal(false), depth: z.enum(depths), max_output_tokens: z.number(), output_limit_policy: z.enum(['request_limit', 'advisory']), guaranteed_cost_ceiling: z.literal(false), reasoning_effort: z.enum(['low', 'medium', 'high']).nullable(), x_search_max_turns: z.number().nullable() }).strict().nullable(),
  images_sent: z.array(z.object({ id: z.string(), sha256: z.string(), width: z.number(), height: z.number(), mime_type: z.string() }).strict()),
  warnings: z.array(z.string()),
  error: z.object({ code: z.string(), message: z.string(), retryable: z.literal(false) }).strict().nullable(),
}).strict();

export class GatewayError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}
export function fail(code, message) { throw new GatewayError(code, message); }

const record = z.object({
  alias: z.string().regex(/^[a-z][a-z0-9-]{0,63}$/), backend: z.enum(['anthropic', 'xai', 'openrouter']),
  model: z.string().max(200), capabilities: z.array(z.enum([...modes, 'image'])),
  selection_policy: z.enum(['auto_allowed', 'explicit_only']),
  privacy_profile: z.enum(['direct', 'deny_collection', 'zdr']),
  default_depth: z.enum(depths), default_max_output_tokens: z.number().int().min(64).max(8192),
  max_output_tokens: z.number().int().min(64).max(8192), max_search_turns: z.number().int().min(1).max(5).optional(),
  output_limit_policy: z.enum(['request_limit', 'advisory']).default('request_limit'),
  reasoning_defaults: z.object({ ordinary: z.enum(['low', 'medium']), retrieval: z.enum(['low', 'medium']) }).strict().optional(),
  enabled: z.boolean(), premium: z.boolean(),
}).strict();
export function validateRegistry(raw) {
  const parsed = z.object({ version: z.literal(1), agents: z.array(record).min(1) }).strict().safeParse(raw);
  if (!parsed.success) fail('CONFIG_REQUIRED', 'Invalid registry schema.');
  const aliases = new Set();
  for (const a of parsed.data.agents) {
    if (aliases.has(a.alias) || (a.enabled && !a.model.trim()) || a.default_max_output_tokens > a.max_output_tokens)
      fail('CONFIG_REQUIRED', 'Invalid registry alias or token limits.');
    aliases.add(a.alias);
    if ((a.backend === 'openrouter') === (a.privacy_profile === 'direct'))
      fail('CONFIG_REQUIRED', 'Privacy profile is incompatible with the backend.');
    if (a.capabilities.includes('image') && a.backend !== 'anthropic')
      fail('CONFIG_REQUIRED', 'This adapter does not yet implement image input.');
    if (a.capabilities.includes('x_research') && (a.backend !== 'xai' || !a.max_search_turns))
      fail('CONFIG_REQUIRED', 'X research requires native search and a turn limit.');
    if (a.backend === 'xai' && (a.output_limit_policy !== 'advisory' || !a.reasoning_defaults))
      fail('CONFIG_REQUIRED', 'Update the Grok registry: advisory output policy and conservative reasoning defaults are required.');
    if (a.backend !== 'xai' && (a.output_limit_policy === 'advisory' || a.reasoning_defaults))
      fail('CONFIG_REQUIRED', 'Reasoning/advisory settings require a supporting adapter.');
    if (a.premium && a.selection_policy !== 'explicit_only')
      fail('CONFIG_REQUIRED', 'Premium profiles must require explicit selection.');
  }
  return parsed.data;
}
