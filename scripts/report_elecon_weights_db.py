"""Report Elecon weight coverage in the database, per series and variant."""

from __future__ import annotations

import sys
from collections import defaultdict

import psycopg

DB = "postgresql://gearbox:gearbox@localhost:5433/gearbox"


def main() -> int:
    with psycopg.connect(DB) as c:
        rows = c.execute("""
            SELECT s.series_code, g.size, d.dim_name, d.weight_kg, d.source_page
            FROM gear_series s
            JOIN gear_size g ON g.series_id = s.id
            LEFT JOIN dimension d ON d.gear_size_id = g.id
                 AND d.dim_name IN ('net_weight_kg','net_weight_kg_torque_arm')
            WHERE s.vendor_id = 1
            ORDER BY s.series_code,
                     CASE WHEN g.size ~ '^[0-9]+$' THEN g.size::int ELSE 0 END,
                     d.dim_name
        """).fetchall()

        have: dict[str, dict[str, list[tuple[str, float | None, int | None]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        all_sizes: dict[str, list[str]] = defaultdict(list)
        for series, size, dim, kg, page in rows:
            all_sizes[series].append(size)
            have[series][size].append((dim or "-", kg, page))

    print(f"{'series':8} {'sizes':>5} {'w(H)':>5} {'w(T)':>5} {'none':>5}  gaps")
    for series in sorted(all_sizes):
        sizes = sorted(set(all_sizes[series]), key=lambda s: int(s) if s.isdigit() else 0)
        h = t = n = 0
        gaps = []
        for size in sizes:
            dims = {d for d, _, _ in have[series][size]}
            if "net_weight_kg" in dims:
                h += 1
            if "net_weight_kg_torque_arm" in dims:
                t += 1
            if "net_weight_kg" not in dims:
                n += 1
                gaps.append(size)
        print(f"{series:8} {len(sizes):>5} {h:>5} {t:>5} {n:>5}  {','.join(gaps) or '-'}")

    print("\nper-size detail (series-size: H kg@page | T kg@page):")
    for series in sorted(all_sizes):
        sizes = sorted(set(all_sizes[series]), key=lambda s: int(s) if s.isdigit() else 0)
        for size in sizes:
            cells = []
            for dim, kg, page in sorted(have[series][size]):
                tag = "H" if dim == "net_weight_kg" else "T"
                cells.append(f"{tag}={kg}@p{page}" if kg is not None else f"{tag}=-")
            print(f"   {series}-{size:>3}  {' | '.join(cells) or 'NO WEIGHT ROW'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
