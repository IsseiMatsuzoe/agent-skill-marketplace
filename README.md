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

## Install from GitHub in the desktop Codex environment

1. Add this GitHub repository as a marketplace: `codex plugin marketplace add IsseiMatsuzoe/agent-skill-marketplace --ref main`.
2. Restart the ChatGPT desktop app. Open the Plugins Directory, select the **Personal** marketplace, and install **Humanizer**.
3. Start a new chat and select Humanizer from the plugin or skill picker.

After a GitHub update, run `codex plugin marketplace upgrade personal`, reinstall or refresh Humanizer in the app, and start a new chat.

## Install in ChatGPT Web

Package the contents of `plugins/humanizer/` as a ZIP with `plugin.json` at the ZIP root. In ChatGPT, open **Plugins → Add → Upload plugin archive**, select that ZIP, then install the resulting personal plugin. In a new chat, type `@humanizer` and select **Humanizer** from the suggestion list.

The ChatGPT upload is a snapshot. Pushing GitHub changes does not update that cloud copy automatically; upload and install a new archive after each reviewed update. A GitHub marketplace alone does not publish the plugin to the universal directory.
