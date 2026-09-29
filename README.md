# Agent Skill Marketplace

The **Personal** marketplace contains two independently installable plugins: **Portable Agent Skills** and **External Agents** for Chat, Work, and Codex. **Portable Agent Skills** still bundles **Humanizer** and **Natural Japanese** without an MCP dependency. Install or select the plugin, then describe the task; the host uses the request intent and skill descriptions to choose the appropriate skill. ChatGPT may show only the plugin in its picker, so individual `@humanizer` and `@natural-japanese` entries are not guaranteed. GitHub is the source of truth; installed plugins are snapshots that need refreshing after updates.

**External Agents** adds `ask-claude`, `design-review`, `x-research`, and `ask-external-agent`. They share one authenticated MCP tool, `call_external_agent`, with registry-controlled routing, selection and privacy. Its separate local service requires setup; installing the plugin does not start or deploy the backend. See [setup and architecture](docs/external-agents.md) and [verification status](docs/external-agents-verification.md). Paid calls are disabled by default. No files inside `plugins/portable-agent-skills` were changed for this addition.

## Contents

- `.agents/plugins/marketplace.json`: the Personal marketplace catalog.
- `plugins/external-agents/`: the separate External Agents portable package and thin workflow skills.
- `services/external-agents/`: the gateway, registry, provider adapters, mock tests and local setup CLI.
- `plugins/portable-agent-skills/plugin.json`: the portable plugin manifest.
- `plugins/portable-agent-skills/.codex-plugin/plugin.json`: the Codex compatibility manifest and plugin display name.
- `plugins/portable-agent-skills/skills/humanizer/SKILL.md`: the Humanizer skill.
- `plugins/portable-agent-skills/skills/natural-japanese/`: the Natural Japanese skill and its required support files.
- `plugins/portable-agent-skills/LICENSE`: the Humanizer upstream MIT license.
- `plugins/portable-agent-skills/skills/natural-japanese/LICENSE`: the Natural Japanese upstream MIT license.

## Humanizer source

The skill is an unchanged copy of [`blader/humanizer` v3.0.0](https://github.com/blader/humanizer/tree/v3.0.0), commit `9862685f575c65a8247f90369951df1b3416e3d6`. Copyright © 2025 Siqi Chen. The MIT license is included beside the plugin. The upstream skill is self-contained, so it needs no references or scripts at runtime.

For a future Humanizer update, review the new upstream version and license, replace the skill and license, update the plugin manifests, validate, then commit and push this repository.

## Natural Japanese source

The included files are unchanged copies from [`coji/natural-japanese` v1.5.0](https://github.com/coji/natural-japanese/tree/v1.5.0/skills/natural-japanese), commit `21e632661a910bf97289c501089ad11eb8b4d85f`. Copyright © 2026 coji; its MIT license is included with the skill. The package includes the referenced materials, style template, and runtime scripts used by the skill. Development-only calibration and fixtures are excluded.

In Codex and other hosts with script execution and `uv`, Natural Japanese can run `lint.py` and its other mechanical checks; its experimental semantic check is opt-in and may download a model. In ordinary Chat, iOS, or any host without arbitrary script execution, use the included `references/manual-checklist.md` review fallback. Script execution is optional and strengthens quality checks where available. No Natural Japanese-specific MCP server is included.

## Install from GitHub in the desktop Codex environment

1. Add this GitHub repository as a marketplace: `codex plugin marketplace add IsseiMatsuzoe/agent-skill-marketplace --ref main`.
2. Restart the ChatGPT desktop app. Open the Plugins Directory, select the **Personal** marketplace, and install **Portable Agent Skills**.
3. Start a new chat with **Portable Agent Skills** selected and describe the writing task. The host chooses a bundled skill from the request intent and skill descriptions.

After a GitHub update, run `codex plugin marketplace upgrade personal`, refresh or reinstall **Portable Agent Skills**, and start a new chat. An older standalone **Humanizer** plugin, if installed, may appear as a separate picker entry.

## Install in ChatGPT Web

Package the contents of `plugins/portable-agent-skills/` as a ZIP with `plugin.json` at the ZIP root. Upload it to install or update the existing **Portable Agent Skills** plugin in ChatGPT. In a new chat, select the plugin if needed and describe the task; the internal skill is chosen from the request intent and skill descriptions. Individual skills may not appear in the `@` picker.

The ChatGPT upload is a snapshot. Pushing GitHub changes does not update that cloud copy automatically; update the existing plugin with a new archive after each reviewed update. A GitHub marketplace alone does not publish the plugin to the universal directory.
