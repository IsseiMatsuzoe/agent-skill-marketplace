import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { inputSchema, resultSchema, GatewayError } from './contracts.js';
import { createGateway } from './gateway.js';
import { ImageStore, MAX_IMAGE } from './images.js';
import { loadConfig } from './config.js';

export function makeMcp(call) {
  const mcp = new McpServer({ name: 'external-agents', version: '0.1.0' });
  mcp.registerTool('call_external_agent', {
    title: 'Call an external specialist',
    description: 'Send only selected task material to a logical external agent. Check user intent before setting user_requested_agent. This may incur cost and sends data outside OpenAI. No repository access or automatic retries. For visual critique set visual_review=true and attach actual images.',
    inputSchema, outputSchema: resultSchema,
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false, openWorldHint: true },
    _meta: { 'openai/fileParams': ['image_files'] },
  }, async input => {
    const result = await call(input);
    return { content: [{ type: 'text', text: JSON.stringify(result) }], structuredContent: result, isError: !result.ok };
  });
  return mcp;
}
function authorized(header, token) {
  const got = Buffer.from(header ?? ''); const expected = Buffer.from(`Bearer ${token}`);
  return got.length === expected.length && timingSafeEqual(got, expected);
}
function json(res, status, body) { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); }
export async function readBody(req, limit) {
  let total = 0; const chunks = [];
  for await (const chunk of req) {
    total += chunk.length;
    if (total > limit) throw new GatewayError('INVALID_INPUT', 'Request body exceeds the local limit.');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}
export function createHttpServer({ token, call, images, port = 47831, paidCallsEnabled = false }) {
  if (typeof token !== 'string' || token.length < 32) throw new GatewayError('CONFIG_REQUIRED', 'Run setup to create the local MCP token.');
  const server = createServer(async (req, res) => {
    try {
      const allowedHosts = [`127.0.0.1:${server.address()?.port ?? port}`, `localhost:${server.address()?.port ?? port}`];
      if (!allowedHosts.includes(req.headers.host) || req.headers.origin) return json(res, 403, { error: 'ORIGIN_REJECTED' });
      if (!authorized(req.headers.authorization, token)) return json(res, 401, { error: 'AUTH_REQUIRED' });
      if (req.url === '/health' && req.method === 'GET') return json(res, 200, {
        status: 'ready', inference_verified: false, paid_calls_enabled: paidCallsEnabled === true,
      });
      if (req.url === '/assets' && req.method === 'POST') {
        const asset = await images.upload(await readBody(req, MAX_IMAGE), req.headers['content-type']);
        return json(res, 201, asset);
      }
      if (req.url !== '/mcp') return json(res, 404, { error: 'NOT_FOUND' });
      if (req.method !== 'POST') return json(res, 405, { error: 'METHOD_NOT_ALLOWED' });
      const body = JSON.parse((await readBody(req, 256 * 1024)).toString('utf8'));
      const mcp = makeMcp(call);
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
      res.on('close', () => { void transport.close(); void mcp.close(); });
      await mcp.connect(transport);
      await transport.handleRequest(req, res, body);
    } catch (error) {
      if (!res.headersSent) json(res, 400, { error: error instanceof GatewayError ? error.code : 'INVALID_REQUEST' });
      else res.end();
    }
  });
  server.requestTimeout = 120000;
  server.headersTimeout = 15000;
  return server;
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const { registry, settings, env } = loadConfig();
    const images = new ImageStore({ origins: settings.file_download_origins });
    const call = createGateway({ registry, env, images });
    const server = createHttpServer({ token: env.EXTERNAL_AGENTS_MCP_TOKEN, call, images, port: settings.port,
      paidCallsEnabled: env.EXTERNAL_AGENTS_ENABLE_PAID === 'true' });
    server.on('error', () => { console.error('SERVER_START_FAILED'); process.exitCode = 1; });
    server.listen(settings.port, '127.0.0.1', () => console.error(`External Agents listening on loopback port ${settings.port}; paid calls ${env.EXTERNAL_AGENTS_ENABLE_PAID === 'true' ? 'enabled' : 'disabled'}.`));
    for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => process.exit(0)));
  } catch { console.error('CONFIG_REQUIRED: run npm run setup and npm run doctor.'); process.exitCode = 1; }
}
