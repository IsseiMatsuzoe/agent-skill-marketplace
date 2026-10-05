#!/usr/bin/env python3
"""Import or check the explicitly invoked, instruction-only i-have-adhd skill."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "plugins/portable-agent-skills/skills/i-have-adhd"
REPOSITORY = "ayghri/i-have-adhd"
COMMIT = "839872f9d1cd634fed642b4589ce7226199cc15f"
FILES = {
    "skills/i-have-adhd/SKILL.md": "9138ae4af11065b7971eea17edc48a2498c1af35",
    "skills/i-have-adhd/agents/openai.yaml": "0e8285b9bb854e7ee4c25f4c48f593a87e9eb85d",
    "LICENSE": "19db5f1b0ca65e277c158bd4c4263139ccfd859c"
}
MAPPING = {
    "skills/i-have-adhd/SKILL.md": "upstream.md",
    "skills/i-have-adhd/agents/openai.yaml": "agents/openai.yaml",
    "LICENSE": "LICENSE",
}
WRAPPER = '''---
name: i-have-adhd
description: "Use only when the user explicitly invokes i-have-adhd or asks for this formatting mode. Organize the answer around the conclusion, next action, and short numbered steps. This is an optional presentation preference, not a diagnosis or an automatic writing-skill choice."
license: MIT
---

# i-have-adhd

Read `upstream.md` in full and use it as formatting guidance only after explicit invocation. Apply it to the requested response or duration. Continue for the session only if the user requests a session-wide mode; stop when the user requests normal output. Never enable it globally or infer activation from a mention of ADHD, a health question, or an installation request.

The upstream statement that the reader has ADHD is not evidence about this user. Do not infer, diagnose, or store a diagnosis. This integration offers an optional way to organize output; its medical generalizations are not clinical guidance.

Preserve facts, uncertainty, qualifications, conditions, and safety-relevant detail. A short or action-first answer must not turn a possibility into a diagnosis, an unverified explanation into a fact, or a proposal into completed work. Give time estimates only when there is a reasonable basis and label uncertainty. Do the authorized work rather than assigning unnecessary steps back to the user. Do not invent an action when the request only needs an answer.

Follow the user's language, document format, and requested level of detail. This mode shapes assistant responses and does not automatically rewrite quoted text or deliverables. For Japanese writing tasks, keep the existing yomiyasu/natural-japanese routing; for non-Japanese editing, keep Humanizer routing. Do not apply another writing skill solely because this mode was invoked. When both formatting and editing are explicitly requested, preserve the editing skill's meaning rules and the requested artifact format.

Only instructions, explicit-invocation metadata, and the MIT license are included. Do not install upstream hooks, run SessionStart code, change host settings, install dependencies, or make external calls to activate this mode.
'''


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def provenance() -> dict:
    return {"repository": REPOSITORY, "commit": COMMIT, "license": "MIT", "files": FILES,
            "path_mapping": MAPPING, "local_entrypoint": "SKILL.md", "activation": "explicit-only"}


def validate() -> None:
    assert FILES and set(FILES) == set(MAPPING), "Missing reviewed hashes"
    for source, expected in FILES.items():
        assert blob_sha((TARGET / MAPPING[source]).read_bytes()) == expected, source
    assert (TARGET / "SKILL.md").read_text(encoding="utf-8") == WRAPPER, "Formatting wrapper mismatch"
    assert json.loads((TARGET / "SOURCE.json").read_text(encoding="utf-8")) == provenance()
    expected_paths = set(MAPPING.values()) | {"SKILL.md", "SOURCE.json"}
    actual = {p.relative_to(TARGET).as_posix() for p in TARGET.rglob("*") if p.is_file()}
    assert actual == expected_paths, f"Unexpected instruction-skill files: {actual - expected_paths}"
    assert "allow_implicit_invocation: false" in (TARGET / "agents/openai.yaml").read_text(encoding="utf-8")
    print("PASS: i-have-adhd provenance, instruction-only file set, wrapper, and explicit activation.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Import only the reviewed instruction files")
    parser.add_argument("--check", action="store_true", help="Check the installed source files offline (default)")
    args = parser.parse_args()
    if args.write:
        downloaded = {}
        for source, expected in FILES.items():
            with urlopen(f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{source}", timeout=30) as response:
                data = response.read(1_000_001)
            assert len(data) <= 1_000_000 and blob_sha(data) == expected, source
            data.decode("utf-8")
            downloaded[source] = data
        for source, data in downloaded.items():
            target = TARGET / MAPPING[source]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (TARGET / "SKILL.md").write_text(WRAPPER, encoding="utf-8", newline="\n")
        (TARGET / "SOURCE.json").write_text(json.dumps(provenance(), indent=2) + "\n", encoding="utf-8", newline="\n")
    validate()


if __name__ == "__main__":
    main()
