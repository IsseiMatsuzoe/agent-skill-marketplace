# Agent Skill Marketplace

The **Personal** marketplace contains one plugin: **Portable Agent Skills** for Chat, Work, and Codex. The plugin currently contains one skill, **Humanizer**. Use `@humanizer` to select the skill directly in ChatGPT. GitHub is the source of truth; installed plugins are snapshots that need refreshing after updates. No MCP server is included.

## Contents

- `.agents/plugins/marketplace.json`: the Personal marketplace catalog.
- `plugins/portable-agent-skills/plugin.json`: the portable plugin manifest.
- `plugins/portable-agent-skills/.codex-plugin/plugin.json`: the Codex compatibility manifest and plugin display name.
- `plugins/portable-agent-skills/skills/humanizer/SKILL.md`: the Humanizer skill.
- `plugins/portable-agent-skills/LICENSE`: the upstream MIT license.

## Humanizer source

The skill is an unchanged copy of [`blader/humanizer` v3.0.0](https://github.com/blader/humanizer/tree/v3.0.0), commit `9862685f575c65a8247f90369951df1b3416e3d6`. Copyright © 2025 Siqi Chen. The MIT license is included beside the plugin. The upstream skill is self-contained, so it needs no references or scripts at runtime.

For a future Humanizer update, review the new upstream version and license, replace the skill and license, update the plugin manifests, validate, then commit and push this repository.

## Install from GitHub in the desktop Codex environment

1. Add this GitHub repository as a marketplace: `codex plugin marketplace add IsseiMatsuzoe/agent-skill-marketplace --ref main`.
2. Restart the ChatGPT desktop app. Open the Plugins Directory, select the **Personal** marketplace, and install **Portable Agent Skills**.
3. Start a new chat and select the **Humanizer** skill directly.

After a GitHub update, run `codex plugin marketplace upgrade personal`, refresh or reinstall **Portable Agent Skills**, and start a new chat. Remove any previously installed standalone **Humanizer** plugin to avoid duplicate picker entries.

## Install in ChatGPT Web

Package the contents of `plugins/portable-agent-skills/` as a ZIP with `plugin.json` at the ZIP root. In ChatGPT, open **Plugins → Add → Upload plugin archive**, select that ZIP, and install **Portable Agent Skills**. In a new chat, type `@humanizer` and select the **Humanizer** skill. Uninstall the old standalone **Humanizer** plugin if it is still installed.

The ChatGPT upload is a snapshot. Pushing GitHub changes does not update that cloud copy automatically; upload and install a new archive after each reviewed update. A GitHub marketplace alone does not publish the plugin to the universal directory.
