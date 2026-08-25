"""Secret audit for the repository (task 10.1).

Scans every GIT-TRACKED file for common credential signatures and verifies
secrets-bearing files (.env, key JSONs) are untracked. Exit code 0 = clean.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "OpenAI-like key": r"sk-[A-Za-z0-9_\-]{20,}",
    "AWS access key": r"AKIA[0-9A-Z]{16}",
    "GitHub PAT": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "Google API key": r"AIza[0-9A-Za-z_\-]{35}",
    "Slack token": r"xox[baprs]-[A-Za-z0-9\-]{10,}",
    "Private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Groq key": r"gsk_[A-Za-z0-9]{20,}",
    "JWT literal": r"eyJhbGciOi[A-Za-z0-9._\-]{40,}",
}

FORBIDDEN_TRACKED = (".env",)


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def main() -> int:
    findings: list[str] = []

    files = tracked_files()
    for forbidden in FORBIDDEN_TRACKED:
        if forbidden in files:
            findings.append(f"FORBIDDEN: {forbidden} is git-tracked")
    for f in files:
        if re.search(r"service[_-]?account.*\.json$|\.pem$|\.key$", f):
            findings.append(f"FORBIDDEN: possible key file tracked: {f}")

    for f in files:
        path = Path(f)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in PATTERNS.items():
            for m in re.finditer(pattern, text):
                snippet = text[max(0, m.start() - 20):m.end() - 10]
                findings.append(f"{label} in {f}: ...{snippet!r}...")

    # untracked-but-present secrets are fine; report their status only
    env = Path(".env")
    if env.exists():
        is_tracked = ".env" in files
        print(f".env present and {'TRACKED (BAD)' if is_tracked else 'untracked (good)'}")

    if findings:
        print("AUDIT FAILED:")
        for item in findings:
            print(f"  - {item}")
        return 1
    print("AUDIT CLEAN: no credential material in tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
