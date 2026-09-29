"""Offline packaging, boundary, and secret checks; no provider or network calls."""
import json
import re
import subprocess
import tempfile
from pathlib import Path
from package_plugin import ROOT, PLUGIN, FILES, build

manifest = json.loads((PLUGIN / "plugin.json").read_text())
compat = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
assert manifest["name"] == compat["name"] == PLUGIN.name
assert manifest["version"] == compat["version"]
assert manifest["extensions"]["com.openai"]["interface"] == compat["interface"]
assert compat["skills"] == "./skills/"
assert compat["mcpServers"] == "./.mcp.json"
portable = json.loads((PLUGIN / "mcp.json").read_text())
legacy = json.loads((PLUGIN / ".mcp.json").read_text())
assert portable["mcpServers"]["external_agents"]["type"] == "stdio"
assert legacy["mcpServers"]["external_agents"]["command"] == "node"
assert portable["mcpServers"]["external_agents"]["args"] == ["${PLUGIN_ROOT}/scripts/relay.mjs"]
assert legacy["mcpServers"]["external_agents"]["args"] == ["scripts/relay.mjs"]
catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
assert [p["name"] for p in catalog["plugins"]] == ["portable-agent-skills", "external-agents"]
for path in PLUGIN.glob("skills/*/SKILL.md"):
    text = path.read_text(encoding="utf8")
    assert "call_external_agent" in text
    assert not re.search(r"ANTHROPIC_API_KEY|XAI_API_KEY|OPENROUTER_API_KEY|api\.anthropic|api\.x\.ai|openrouter\.ai", text)
    assert path.parent.name == re.search(r"^name: (.+)$", text, re.M)[1]
for name in FILES:
    text = (PLUGIN / name).read_text(encoding="utf8")
    assert not re.search(r"sk-(?:ant-|or-v1-)?[A-Za-z0-9_-]{20,}|xai-[A-Za-z0-9_-]{20,}|Bearer [A-Za-z0-9_-]{32,}", text)
with tempfile.TemporaryDirectory() as directory:
    target = Path(directory) / "plugin.zip"
    assert len(build(target)) == 9
    assert len(build(target, skills_only=True)) == 6
    assert len(build(target, "https://mcp.example.org/mcp")) == 8
    try:
        build(target, "https://mcp.example.org/mcp?token=secret")
    except ValueError:
        pass
    else:
        raise AssertionError("Credential-bearing URL accepted")
# Compare every existing plugin blob against the audited baseline, including names.
baseline = "07565230180468846c08f6c47c56e62d87648238"
subprocess.run(["git", "diff", "--exit-code", baseline, "--", "plugins/portable-agent-skills"], cwd=ROOT, check=True)
print("PASS: manifests, catalog, thin skills, archive allowlist, secret patterns, existing plugin boundary")
