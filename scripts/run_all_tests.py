"""Run every gate in order and stop at the first failure.

    .venv\Scripts\python.exe scripts\run_all_tests.py

Requires a running Next dev server on :3000 and the Python service on :8000.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

GATES = [
    ("engine regression", "test_phase0_regression.py", []),
    ("conflicting ratings", "test_conflicting_ratings.py", []),
    ("pricing cache", "test_pricing_cache.py", []),
    ("llm transport", "test_llm_transport.py", []),
    ("document extraction", "test_docparse.py", []),
    ("office upload", "test_upload_office.py", []),
    ("sessions", "test_sessions.py", []),
    ("fresh init equivalence", "test_fresh_init.py", []),
    ("http acceptance", "test_acceptance.py", []),
]

failed: list[tuple[str, str]] = []

for label, script, args in GATES:
    print(f"\n{'=' * 70}\n  {label}  ({script})\n{'=' * 70}")
    start = time.time()
    r = subprocess.run([PY, str(ROOT / "scripts" / script), *args],
                       cwd=ROOT, capture_output=True, text=True)
    took = time.time() - start
    tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-3:]
    for ln in tail:
        print("  " + ln)
    print(f"  [{took:.1f}s, exit {r.returncode}]")
    if r.returncode != 0:
        failed.append((label, r.stdout[-2500:] + r.stderr[-1500:]))

print(f"\n{'=' * 70}")
if failed:
    print(f"  {len(failed)} GATE(S) FAILED\n{'=' * 70}")
    for label, out in failed:
        print(f"\n### {label}\n{out}")
    sys.exit(1)
print("  ALL GATES PASS\n" + "=" * 70)
sys.exit(0)