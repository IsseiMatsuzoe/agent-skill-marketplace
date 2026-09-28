# Agent Skill Marketplace

A one-plugin marketplace for Humanizer. GitHub is the source of truth; installed plugins are local copies that must be refreshed after a source update. This package has no MCP server.

## Contents

- `.agents/plugins/marketplace.json`: the marketplace catalog.
- `plugins/humanizer/plugin.json`: the portable plugin manifest.
- `plugins/humanizer/.codex-plugin/plugin.json`: the Codex compatibility manifest.
- `plugins/humanizer/skills/humanizer/SKILL.md`: the Humanizer skill.
- `plugins/humanizer/LICENSE`: the upstream MIT license.

## Humanizer source

The skill is an unchanged copy of [`blader/humanizer` v3.0.0](https://github.com/blader/humanizer/tree/v3.0.0), commit `9862685f575c65a8247f90369951df1b3416e3d6`. Copyright © 2025 Siqi Chen. The MIT license is included beside the plugin. The upstream skill is self-contained, so it needs no references or scripts at runtime.

For updates, review the new upstream version and license, replace the skill and license, update both plugin manifests, validate, then commit and push this repository. Refresh the installed marketplace and plugin afterward.

## Install in the ChatGPT desktop app / Codex

1. Add this GitHub repository as a marketplace: `codex plugin marketplace add IsseiMatsuzoe/agent-skill-marketplace --ref main`.
2. Restart the ChatGPT desktop app. Open the Plugins Directory, select the **Personal** marketplace, and install **Humanizer**.
3. Start a new chat and ask, for example, `@humanizer Rewrite this paragraph without changing its facts: ...`. If the composer does not offer an `@humanizer` entry, select the installed Humanizer plugin or invoke its `humanizer` skill from the skill picker; the exact composer syntax depends on the surface.

After a GitHub update, run `codex plugin marketplace upgrade personal`, reinstall or refresh Humanizer in the app, and start a new chat. Local marketplace support does not by itself publish this plugin to the universal ChatGPT plugin directory or make it available in ChatGPT Web or mobile.
