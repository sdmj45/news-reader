"""Measures the real GDELT GAL JSON-NL schema instead of trusting the announcement post.

Specification section 4.1 requires inspecting actual GAL data before relying on a parser for
it. This script does that: it finds a recent GAL file, downloads it, and reports field
presence, description coverage, duplicate and invalid URL rates, language spread and source
diversity, all computed from the records themselves.

    python -I scripts/probe_gdelt.py [--url URL] [--json]

Writes nothing to the database. On a network failure it says so and exits non-zero; it never
substitutes sample data.

File naming, confirmed against live files on 2026-11-14:
    https://data.gdeltproject.org/gdeltv3/gal/YYYYMMDDHHMM00.gal.json.gz
published in the minutes following each quarter hour, not every minute.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import sys

import httpx

from app.collectors.gdelt_collector import describe_payload

BASE = "https://data.gdeltproject.org/gdeltv3/gal"
UA = "NewsReaderBot/0.1 (+personal news aggregator; schema probe)"


def candidate_urls(now: dt.datetime, quarters_back: int = 6) -> list[str]:
    """GAL filenames worth trying, newest first.

    Files appear a minute or two after each quarter hour, so each quarter is probed across a
    small window rather than at the exact mark.
    """
    base = now.replace(second=0, microsecond=0)
    urls: list[str] = []
    for q in range(quarters_back):
        mark = base - dt.timedelta(minutes=(base.minute % 15) + 15 * q)
        for offset in range(0, 6):
            stamp = (mark + dt.timedelta(minutes=offset)).strftime("%Y%m%d%H%M00")
            urls.append(f"{BASE}/{stamp}.gal.json.gz")
    return urls


def fetch_latest(client: httpx.Client, quarters_back: int = 6) -> tuple[str, bytes]:
    """Returns (url, decompressed payload) for the most recent GAL file that exists."""
    errors: list[str] = []
    for url in candidate_urls(dt.datetime.now(dt.UTC), quarters_back):
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            errors.append(f"{url}: {type(exc).__name__}")
            continue
        if response.status_code == 404:
            continue
        if not response.is_success:
            errors.append(f"{url}: HTTP {response.status_code}")
            continue
        return url, decompress(response.content)
    raise SystemExit(
        "No GAL file could be retrieved.\n"
        + ("\n".join(errors[:10]) if errors else "Every candidate returned 404.")
    )


def decompress(payload: bytes) -> bytes:
    """GAL files are gzip. Served as ``.gz`` without Content-Encoding, so httpx leaves them."""
    if payload[:2] == b"\x1f\x8b":
        return gzip.decompress(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Probe this exact GAL file instead of searching.")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    parser.add_argument("--sample", type=int, default=2000, help="Records to measure.")
    args = parser.parse_args()

    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=60.0) as client:
        if args.url:
            response = client.get(args.url)
            response.raise_for_status()
            url, payload = args.url, decompress(response.content)
        else:
            url, payload = fetch_latest(client)

    report = describe_payload(payload, sample_size=args.sample)
    report["source_url"] = url
    report["payload_bytes"] = len(payload)
    report["probed_at"] = dt.datetime.now(dt.UTC).isoformat()

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print(f"GAL file        : {url}")
    print(f"Decompressed    : {report['payload_bytes']:,} bytes, {report['lines_total']:,} lines")
    print(f"Sampled         : {report['lines_sampled']:,} lines, "
          f"{report['records_decoded']:,} decoded, {report['lines_malformed']} malformed")
    print(f"Invalid URLs    : {report['invalid_urls']}")
    print(f"Dup canonical   : {report['duplicate_canonical_urls']}")
    print(f"Description cov : {report['description_coverage']:.1%} "
          f"(median {report['description_median_chars']} chars)")
    print(f"Distinct domains: {report['distinct_domains']}")
    print("\nField presence (share of records with a non-empty value):")
    for field, share in sorted(report["field_presence"].items(), key=lambda kv: -kv[1]):
        print(f"  {field:<10} {share:6.1%}")
    print("\nRaw keys present in the sample:")
    for key, count in sorted(report["keys_non_empty"].items(), key=lambda kv: -kv[1]):
        print(f"  {key:<16} {count:>6} non-empty / {report['keys_seen'].get(key, 0)} present")
    print("\nTop languages:", ", ".join(f"{k}={v}" for k, v in report["languages"][:10]))
    print("Top domains   :", ", ".join(f"{k}({v})" for k, v in report["top_domains"][:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
