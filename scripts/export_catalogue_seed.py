"""Generate init/06_catalogue_seed.sql from the live catalogue.

init/00..05 create the schema and the derating factors, but the gearbox
catalogue itself comes out of the vendor PDFs via scripts/import_gearbox.py.
A deployment built only from init/ therefore has a valid schema containing no
gearboxes, and the selection engine returns nothing without reporting an error.

This exports the catalogue tables as INSERT ... ON CONFLICT DO NOTHING so the
seed is safe to replay alongside the rest of init/.

    .venv\\Scripts\\python.exe scripts\\export_catalogue_seed.py

Refuses to run if the live catalogue looks empty -- that almost always means
it is pointed at the wrong database, and an empty seed is worse than none.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "init" / "06_catalogue_seed.sql"

# order matters only for readability; pg_dump emits FK-safe ordering itself
TABLES = [
    "public.vendor",
    "public.gear_series",
    "public.gear_size",
    "public.power_rating",
    "public.thermal_capacity",
    "public.dimension",
    "public.series_mounting",
    "public.catalog_page",
    "public.service_factor",
    "public.ambient_factor",
    "public.altitude_factor",
    "public.application",
    "public.duty_factor",
]

HEADER = """\
-- ============================================================================
-- Catalogue data seed. GENERATED FILE -- do not hand-edit.
--
-- Regenerate with:
--     .venv\\Scripts\\python.exe scripts\\export_catalogue_seed.py
--
-- Why this file exists: init/00..05 build the *schema* and the derating
-- factors, but the gearbox catalogue itself (14 series, 4476 power ratings,
-- 1391 thermal capacities, 168 dimensions) is parsed out of the vendor PDFs
-- by scripts/import_gearbox.py. Without this seed a fresh deployment starts
-- with a valid schema containing no gearboxes at all: the selection engine
-- returns nothing and reports no error, which is the worst possible failure
-- mode for an engineering tool.
--
-- Every INSERT is ON CONFLICT DO NOTHING, so replaying init/ is safe.
-- scripts/test_fresh_init.py asserts the row counts match the live database.
-- ============================================================================

"""

INSERT_RE = re.compile(r"^INSERT INTO ", re.M)


def main() -> int:
    cmd = [
        "docker", "exec", "gearbox-db", "pg_dump", "-U", "gearbox", "-d", "gearbox",
        "--data-only", "--inserts", "--no-owner", "--no-privileges",
    ]
    for t in TABLES:
        cmd += ["-t", t]

    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        print(res.stderr[:800], file=sys.stderr)
        return 1

    body: list[str] = []
    inserts = 0
    pending: list[str] = []

    def flush() -> None:
        """Close the previous INSERT with ON CONFLICT DO NOTHING."""
        nonlocal inserts
        if not pending:
            return
        pending[-1] = pending[-1].rstrip()
        assert pending[-1].endswith(";")
        pending[-1] = pending[-1][:-1] + " ON CONFLICT DO NOTHING;"
        body.extend(pending)
        inserts += 1
        pending.clear()

    for line in res.stdout.splitlines():
        stripped = line.strip()

        # skip pg_dump session preamble; the app sets its own
        if stripped.startswith("SET ") or stripped.startswith("\\"):
            continue

        if stripped.startswith("INSERT INTO "):
            flush()
            pending.append(line)
            # a statement that already ends here is a single-line insert
            if stripped.endswith(";"):
                flush()
            continue

        if stripped == "":
            continue

        # multi-line VALUES body belongs to the INSERT being collected
        if pending:
            pending.append(line)
        else:
            flush()
            body.append(line)
    flush()

    if inserts == 0:
        print("refusing to write an empty seed: pg_dump returned no INSERTs",
              file=sys.stderr)
        return 1

    OUT.write_text(HEADER + "\n".join(body) + "\n", encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  {inserts} idempotent inserts, {size_kb:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())