"""Build an allowlisted plugin archive, never a backend/secret archive."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins" / "external-agents"
FILES = ["plugin.json", "mcp.json", ".codex-plugin/plugin.json", ".mcp.json", "scripts/relay.mjs", "skills/orchestration.md"] + [
    f"skills/{name}/SKILL.md" for name in
    ("ask-claude", "design-review", "x-research", "ask-external-agent")
]


def build(output, endpoint=None, skills_only=False, app_id=None):
    if sum(bool(v) for v in (endpoint, skills_only, app_id)) > 1:
        raise ValueError("Choose one host connection mode")
    if app_id and not re.fullmatch(r"(?:plugin_)?asdk_app_[A-Za-z0-9_-]+", app_id):
        raise ValueError("Use the actual registered OpenAI app ID, never a credential")
    if endpoint:
        url = urlsplit(endpoint)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment):
            raise ValueError("Use a credential-free HTTPS endpoint URL")
    files = {name: (PLUGIN / name).read_bytes() for name in FILES}
    if skills_only or app_id:
        del files["scripts/relay.mjs"]
        del files["mcp.json"]
        del files[".mcp.json"]
        compat = json.loads(files[".codex-plugin/plugin.json"])
        compat.pop("mcpServers", None)
        files[".codex-plugin/plugin.json"] = json.dumps(compat, indent=2).encode()
        if app_id:
            portable = json.loads(files["plugin.json"])
            portable["extensions"]["com.openai"]["apps"] = "./.app.json"
            compat["apps"] = "./.app.json"
            files["plugin.json"] = json.dumps(portable, indent=2).encode()
            files[".codex-plugin/plugin.json"] = json.dumps(compat, indent=2).encode()
            files[".app.json"] = json.dumps({"apps": {"external_agents": {"id": app_id, "required": True}}}, indent=2).encode()
    elif endpoint:
        del files["scripts/relay.mjs"]
        for name in ("mcp.json", ".mcp.json"):
            config = json.loads(files[name])
            config["mcpServers"]["external_agents"] = {"type": "streamable-http" if name == "mcp.json" else "http", "url": endpoint}
            files[name] = json.dumps(config, indent=2).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with ZipFile(output) as archive:
        assert sorted(archive.namelist()) == sorted(files)
        assert archive.testzip() is None
    return sorted(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="An already configured, authenticated HTTPS MCP endpoint")
    parser.add_argument("--skills-only", action="store_true", help="For a host with the gateway connected separately")
    parser.add_argument("--app-id", help="Actual registered ChatGPT MCP app ID; creates a mapped remote Plugin without local stdio")
    args = parser.parse_args()
    if sum(bool(v) for v in (args.url, args.skills_only, args.app_id)) > 1:
        parser.error("Choose a remote endpoint, registered app ID, or skills-only packaging")
    target = ROOT / "dist" / ("external-agents-chatgpt.zip" if args.app_id else "external-agents-skills.zip" if args.skills_only else "external-agents.zip")
    names = build(target, args.url, args.skills_only, args.app_id)
    print(json.dumps({"archive": str(target), "files": names, "contains_backend_or_secrets": False}, indent=2))
