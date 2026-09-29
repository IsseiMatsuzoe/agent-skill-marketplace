---
name: design-review
description: Review UI, visual design, screenshots or motion-design key frames against the user's goals or an accepted design. Typically uses Claude through the common external-agent gateway.
---

Read [shared orchestration](../orchestration.md). Infer the design goal and select the relevant visual and surrounding context; do not require a fixed brief. Distinguish reference images from the current implementation and preserve accepted decisions.

Obtain real image references from the host or local upload `asset_ids`. For a local host, run `node <this-plugin-root>/scripts/relay.mjs --upload <absolute-image-path>` for the selected image, resolving the plugin root from this Skill's installation path. Pass its returned `asset_id`. Hosted Chat uses actual `image_files` references instead; do not run the local helper there. Never invent download URLs, treat a path as an upload or reconstruct an image from prose.

Call `call_external_agent` with `agent: "claude"`, `mode: "review"`, `visual_review: true`, the selected images, a focused task and any useful context. Set `user_requested_agent` only if the user explicitly named the specialist. Describe image roles or frame timestamps when relevant. Ask for prioritized, concrete corrections grounded in visible evidence without imposing a fixed output template.

Verify `ok` and that `images_sent` covers the selected images. Missing or failed image transfer stops the visual review; do not claim textual descriptions prove visual inspection. Explain uncertainties: key frames cannot establish continuous smoothness, flicker or audio synchronization, and received bytes do not prove understanding. Evaluate the advice before implementation.
