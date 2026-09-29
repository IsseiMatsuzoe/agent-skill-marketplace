import { fail } from './contracts.js';

// Model publishers and inference hosts are separate trust decisions, never inferred from an alias.
export function resolveRouting(registry, agent, explicitlyRequested) {
  const router = registry.routing.openrouter;
  const publisher = agent.backend === 'openrouter' ? agent.model.split('/')[0] : null;
  const tier = publisher === null ? registry.routing.direct[agent.backend]
    : router.approved_model_providers.includes(publisher) ? 'auto_allowed' : 'explicit_only';
  const selection = agent.premium ? 'explicit_only' : tier;
  if (selection === 'explicit_only' && !explicitlyRequested)
    fail('EXPLICIT_REQUEST_REQUIRED', 'This provider or premium profile is explicit-only; automatic selection is unavailable.');
  if (publisher === null) return { selection, provider_only: null };
  // Explicit choice permits the configured route for that family, never a privacy relaxation.
  const providers = explicitlyRequested && Object.hasOwn(router.explicit_providers, publisher)
    ? router.explicit_providers[publisher] : router.approved_providers;
  if (!providers.length)
    fail('POLICY_OR_MODEL_UNAVAILABLE', 'No serving provider is configured under the required routing policy.');
  return { selection, provider_only: [...providers] };
}
