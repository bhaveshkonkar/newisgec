"""Indicative (NOT published) net weights for series the catalogue omits.

The Elecon EON-Series catalogue publishes "Average Weight [kg]" only for
S1, S3, S4, K3 and K4. K2 and S2 have no weight table anywhere in the PDF,
so those sizes get an ESTIMATE derived from the nearest published series
with the same frame-size number.

Every estimate carries its basis and is reported as indicative (~) in the
UI and in chat replies - it is never written into the `dimension` table
alongside real published weights, so published and estimated data never mix.

Factors are collected here so they are easy to review/adjust.
"""
from __future__ import annotations

# series -> (donor series, factor, why)
BASIS: dict[str, tuple[str, float, str]] = {
    'K2': ('K3', 1.00,
           'K3 (3-stage) and K4 (4-stage) publish identical weights, so the '
           'bevel-helical housing weight does not change with stage count; '
           'K2 taken at the K3 figure for the same size.'),
    'S2': ('S3', 0.89,
           'S1 (single stage) publishes ~0.79x the S3 (triple stage) weight '
           'at size 20 and above; S2 (double stage) taken as the midpoint.'),
}

# how far from the requested size we will borrow a donor weight
SIZE_SLACK = 3


def indicative_weight(series: str, size: str, lookup) -> dict | None:
    """Estimate a weight for `series`/`size` using a donor series.

    `lookup(series, size)` must return the published weight_kg or None.
    Returns {'weight_kg', 'donor_series', 'donor_size', 'factor', 'basis'}
    or None when no donor data is close enough.
    """
    spec = BASIS.get(str(series).upper())
    if not spec:
        return None
    donor, factor, why = spec
    try:
        want = int(str(size))
    except (TypeError, ValueError):
        return None

    exact = lookup(donor, str(size))
    if exact is not None:
        return {'weight_kg': round(exact * factor, 1), 'donor_series': donor,
                'donor_size': str(size), 'factor': factor, 'basis': why,
                'published': False}

    # nearest donor size within slack
    best = None
    for off in range(1, SIZE_SLACK + 1):
        for cand in (want - off, want + off):
            got = lookup(donor, str(cand))
            if got is not None:
                best = (cand, got)
                break
        if best:
            break
    if not best:
        return None
    return {'weight_kg': round(best[1] * factor, 1), 'donor_series': donor,
            'donor_size': str(best[0]), 'factor': factor, 'basis': why,
            'published': False}
