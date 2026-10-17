import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

msg = sys.argv[1] if len(sys.argv) > 1 else "S3 size range"
body = json.dumps({"message": msg, "form": None, "session_id": "probe-1"}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/chat", data=body, method="POST",
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        j = json.loads(r.read())
        print("status", r.status)
        print("reply:", repr(j.get("reply"))[:600])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read()[:400].decode())

# also call catalog_qa directly to see whether it returns None
import asyncio

import reasoning

ctx = reasoning._catalog_context(msg)
print("\n_catalog_context length:", len(ctx or ""))
ans = asyncio.run(reasoning.catalog_qa(msg, []))
print("catalog_qa ->", "None" if ans is None else repr(ans[:200]))