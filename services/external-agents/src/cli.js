import { mkdirSync, existsSync, readFileSync, writeFileSync, copyFileSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';
import { randomBytes } from 'node:crypto';
import { homedir } from 'node:os';
import { root, local, loadConfig } from './config.js';
import { keyNames } from './adapters.js';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const command = process.argv[2];
try {
  if (command === 'setup') {
    mkdirSync(local, { recursive: true, mode: 0o700 });
    const secrets = join(local, 'secrets.env');
    if (!existsSync(secrets)) writeFileSync(secrets, readFileSync(join(root, '.env.example'), 'utf8') + `\nEXTERNAL_AGENTS_MCP_TOKEN=${randomBytes(32).toString('hex')}\nEXTERNAL_AGENTS_ENABLE_PAID=false\n`, { mode: 0o600, flag: 'wx' });
    if (!existsSync(join(local, 'settings.json'))) writeFileSync(join(local, 'settings.json'), JSON.stringify({ port: 47831, file_download_origins: [] }, null, 2));
    if (!existsSync(join(local, 'registry.json'))) copyFileSync(join(root, 'registry.json'), join(local, 'registry.json'));
    console.log('Local setup prepared. Secret values were not displayed. Paid calls remain controlled by .local/secrets.env.');
  } else if (command === 'connect-host') {
    const { env, settings } = loadConfig();
    if (!env.EXTERNAL_AGENTS_MCP_TOKEN || env.EXTERNAL_AGENTS_MCP_TOKEN.length < 32) throw new Error();
    const directory = join(homedir(), '.config', 'external-agents');
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    const path = join(directory, 'connection.json');
    writeFileSync(path, JSON.stringify({ url: `http://127.0.0.1:${settings.port}/mcp`, token: env.EXTERNAL_AGENTS_MCP_TOKEN }), { mode: 0o600 });
    console.log(JSON.stringify({ connection_file: path, provider_keys_copied: false, paid_calls_changed: false }));
  } else if (command === 'doctor') {
    const { registry, env, settings } = loadConfig();
    console.log(JSON.stringify({ node: process.version, registry: 'valid', agents: registry.agents.length,
      keys: Object.fromEntries(Object.values(keyNames).map(k => [k, env[k]?.trim() ? 'present_unverified' : 'missing'])),
      mcp_token: env.EXTERNAL_AGENTS_MCP_TOKEN?.length >= 32 ? 'present' : 'missing',
      paid_calls: env.EXTERNAL_AGENTS_ENABLE_PAID === 'true' ? 'enabled' : 'disabled',
      file_download_origins: settings.file_download_origins.length, network_called: false,
    }, null, 2));
  } else if (command === 'check-models') {
    const { registry } = loadConfig();
    const response = await fetch('https://openrouter.ai/api/v1/models', { redirect: 'error', signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error();
    const catalog = await response.json(); const ids = new Set(catalog.data.map(m => m.id));
    const results = registry.agents.filter(a => a.backend === 'openrouter' && a.model).map(a => ({ agent: a.alias, model: a.model, exists: ids.has(a.model) }));
    console.log(JSON.stringify({ checked_at: new Date().toISOString(), results, privacy_compatible_endpoint_verified: false, inference_called: false }, null, 2));
    if (results.some(r => !r.exists)) process.exitCode = 1;
  } else if (command === 'upload') {
    const file = process.argv[3];
    if (!file || statSync(file).size > 5 * 1024 * 1024) throw new Error();
    const mime = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' }[extname(file).toLowerCase()];
    if (!mime) throw new Error();
    const { env, settings } = loadConfig();
    const response = await fetch(`http://127.0.0.1:${settings.port}/assets`, { method: 'POST', headers: { Authorization: `Bearer ${env.EXTERNAL_AGENTS_MCP_TOKEN}`, 'Content-Type': mime }, body: readFileSync(file), signal: AbortSignal.timeout(20000), redirect: 'error' });
    if (!response.ok) throw new Error();
    console.log(JSON.stringify(await response.json()));
  } else if (command === 'smoke') {
    const name = process.argv[3];
    if (!process.argv.includes('--allow-paid')) throw new Error();
    const { env, settings, registry } = loadConfig();
    if (env.EXTERNAL_AGENTS_ENABLE_PAID !== 'true') throw new Error();
    const cases = {
      'claude-text': { agent: 'claude', task: 'Reply with one short greeting.', max_output_tokens: 256 },
      'claude-image': { agent: 'claude', task: 'Describe only the visible shapes and their relative positions.', mode: 'review', visual_review: true, asset_ids: [process.argv[4]], max_output_tokens: 512 },
      'grok-x': { agent: 'grok', task: 'Find one recent public developer discussion about API integration. Cite the source and separate reports from verified facts.', mode: 'x_research', max_output_tokens: 512 },
      'openrouter': { agent: 'gemini', task: 'Reply with one short greeting.', max_output_tokens: 256 },
    };
    const input = cases[name]; if (!input) throw new Error();
    console.log(JSON.stringify({ paid_test: name, model: registry.agents.find(a => a.alias === input.agent)?.model, max_output_tokens: input.max_output_tokens, calls: 1, retries: 0 }));
    const client = new Client({ name: 'external-agents-smoke', version: '0.1.0' });
    try {
      await client.connect(new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${settings.port}/mcp`), { requestInit: { headers: { Authorization: `Bearer ${env.EXTERNAL_AGENTS_MCP_TOKEN}` } } }));
      const response = await client.callTool({ name: 'call_external_agent', arguments: input }, undefined, { timeout: 115000 });
      console.log(JSON.stringify(response.structuredContent, null, 2));
      if (response.isError) process.exitCode = 1;
    } finally { await client.close(); }
  } else throw new Error();
} catch { console.error('COMMAND_FAILED: check the command, local configuration and service status. No secret or raw error details were printed.'); process.exitCode = 1; }
