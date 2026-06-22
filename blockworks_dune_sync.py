#!/usr/bin/env python3
"""Maintain a Blockworks-seeded CSV and upload it to Dune.

Default behavior:
  1. Reads the persisted state CSV if it exists.
  2. Otherwise reads the historical seed CSV that was scraped once already.
  3. Fetches the latest Blockworks execution and merges only new/recent dates.
  4. Writes the updated state CSV.
  5. Uploads/replaces the Dune upload table with the full state CSV.

GitHub Actions runners are ephemeral, so the workflow commits the updated state
CSV back to the repository after every successful run.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PAGE_URL = (
    "https://blockworks.com/analytics/solana/solana-spot-dexs/"
    "solana-spot-dex-volume-by-pair-category/"
)
BLOCKWORKS_REST_API = "https://rest.blockworksresearch.com"
DUNE_UPLOAD_CSV_URL = "https://api.dune.com/api/v1/uploads/csv"
DEFAULT_QUERY_ID = "3056"
DEFAULT_TABLE_NAME = "solana_spot_dex_pair_category_volume"
DEFAULT_HISTORICAL_CSV = "data/historical_solana_spot_dex_volume_by_pair_category.csv"
DEFAULT_STATE_CSV = "data/solana_spot_dex_pair_category_volume.csv"

HTTP_HEADERS = {
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Origin": "https://blockworks.com",
    "Referer": PAGE_URL,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/125 Safari/537.36"
    ),
}

@dataclass(frozen=True)
class SeriesColumn:
    source_key: str
    output_key: str
    label: str


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def request_text(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 120,
    retries: int = 3,
) -> str:
    merged_headers = dict(HTTP_HEADERS)
    if headers:
        merged_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, data=body, headers=merged_headers, method=method)
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {url}: {error_body[:1000]}") from exc
        except URLError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            break

    raise RuntimeError(f"Failed to request {url}: {last_error}") from last_error


def request_json(url: str, **kwargs: Any) -> dict[str, Any]:
    return json.loads(request_text(url, **kwargs))


def load_page_visualization() -> dict[str, Any]:
    html = request_text(PAGE_URL, headers={"Accept": "text/html"})
    prefix = '<script id="__NEXT_DATA__" type="application/json">'
    start = html.find(prefix)
    if start == -1:
        raise RuntimeError("Could not find Blockworks __NEXT_DATA__ payload")

    end = html.find("</script>", start)
    payload = json.loads(html[start + len(prefix) : end])
    visualization = payload["props"]["pageProps"]["content"]["visualization"]
    if visualization["slug"] != "solana-spot-dex-volume-by-pair-category":
        raise RuntimeError(f"Unexpected visualization slug: {visualization['slug']}")
    return visualization


def latest_execution_id(query_id: str, fallback_execution_id: str | None = None) -> str:
    query = urlencode({"query_id": query_id, "limit": 1, "page": 1, "state": "success"})
    url = f"{BLOCKWORKS_REST_API}/v1/internal/studio/queries/executions?{query}"
    payload = request_json(url)
    executions = payload.get("data") or []
    if executions:
        return executions[0]["execution_id"]
    if fallback_execution_id:
        return fallback_execution_id
    raise RuntimeError(f"No successful Blockworks execution found for query_id={query_id}")


def fetch_execution_rows(execution_id: str) -> list[dict[str, Any]]:
    query = urlencode({"limit": 50000, "page": 1})
    url = (
        f"{BLOCKWORKS_REST_API}/v1/internal/studio/queries/executions/"
        f"{execution_id}/rows?{query}"
    )
    payload = request_json(url, timeout=180)
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("Blockworks rows response did not include a data array")
    return rows


def dune_safe_name(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value or not re.match(r"^[a-z_]", value):
        value = f"col_{value}"
    return value


def normalize_column_name(value: str) -> str:
    if value == "block_date":
        return value
    return dune_safe_name(value)


def series_from_visualization(visualization: dict[str, Any]) -> list[SeriesColumn]:
    groups = visualization["config"]["options"]["groups"]
    series_items = [item for group in groups for item in group["series"]]
    output: list[SeriesColumn] = []
    used_names: set[str] = set()

    for item in series_items:
        label = item["label"]
        name = dune_safe_name(f"{label}_volume_usd")
        original = name
        suffix = 2
        while name in used_names:
            name = f"{original}_{suffix}"
            suffix += 1
        used_names.add(name)
        output.append(SeriesColumn(item["column"], name, label))
    return output


def normalize_block_date(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text


def parse_block_date(value: Any) -> date | None:
    normalized = normalize_block_date(value)
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def read_seed_rows(path: Path, fieldnames: list[str]) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows: list[dict[str, Any]] = []

        for source_row in reader:
            row = {fieldname: "" for fieldname in fieldnames}
            for source_key, value in source_row.items():
                if source_key is None:
                    continue
                target_key = normalize_column_name(source_key)
                if target_key in row:
                    row[target_key] = value

            row["block_date"] = normalize_block_date(row.get("block_date"))
            if not row["block_date"]:
                continue
            rows.append(row)

    return rows


def build_fresh_rows(
    rows: list[dict[str, Any]],
    series: list[SeriesColumn],
) -> list[dict[str, Any]]:
    output_rows: list[dict[str, Any]] = []

    for source_row in rows:
        block_date = normalize_block_date(source_row.get("block_date"))
        if not block_date:
            continue

        output_rows.append(
            {
                "block_date": block_date,
                **{column.output_key: source_row.get(column.source_key) for column in series},
            }
        )

    return output_rows


def merge_rows(
    existing_rows: list[dict[str, Any]],
    fresh_rows: list[dict[str, Any]],
    *,
    refresh_lookback_days: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_by_date: dict[date, dict[str, Any]] = {}
    for row in existing_rows:
        parsed = parse_block_date(row.get("block_date"))
        if parsed:
            rows_by_date[parsed] = row

    max_existing_date = max(rows_by_date) if rows_by_date else None
    lookback_days = max(refresh_lookback_days, 0)
    refresh_cutoff = (
        max_existing_date - timedelta(days=lookback_days)
        if max_existing_date is not None
        else None
    )

    added_dates = 0
    refreshed_dates = 0
    skipped_old_dates = 0

    for row in fresh_rows:
        parsed = parse_block_date(row.get("block_date"))
        if parsed is None:
            continue

        should_merge = (
            max_existing_date is None
            or parsed > max_existing_date
            or (refresh_cutoff is not None and parsed >= refresh_cutoff)
        )
        if not should_merge:
            skipped_old_dates += 1
            continue

        if parsed in rows_by_date:
            refreshed_dates += 1
        else:
            added_dates += 1
        rows_by_date[parsed] = row

    merged_rows = [rows_by_date[key] for key in sorted(rows_by_date)]
    stats = {
        "added_dates": added_dates,
        "existing_max_date": max_existing_date.isoformat() if max_existing_date else None,
        "merged_max_date": max(rows_by_date).isoformat() if rows_by_date else None,
        "refreshed_dates": refreshed_dates,
        "refresh_lookback_days": lookback_days,
        "skipped_old_dates": skipped_old_dates,
    }
    return merged_rows, stats


def rows_to_csv(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({fieldname: row.get(fieldname, "") for fieldname in fieldnames})
    return buffer.getvalue()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def upload_csv_to_dune(
    csv_text: str,
    *,
    api_key: str,
    table_name: str,
    description: str,
    is_private: bool,
) -> dict[str, Any]:
    body = json.dumps(
        {
            "data": csv_text,
            "description": description,
            "table_name": table_name,
            "is_private": is_private,
        }
    ).encode("utf-8")

    response = request_text(
        DUNE_UPLOAD_CSV_URL,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-DUNE-API-KEY": api_key,
        },
        body=body,
        timeout=180,
        retries=1,
    )
    return json.loads(response)


def choose_seed_csv(args: argparse.Namespace) -> tuple[Path, str]:
    state_csv = Path(args.state_csv)
    historical_csv = Path(args.historical_csv)

    if state_csv.exists():
        return state_csv, "state_csv"
    if historical_csv.exists():
        return historical_csv, "historical_csv"
    if args.allow_empty_seed:
        return state_csv, "empty_seed"

    raise RuntimeError(
        f"No state CSV found at {state_csv} and no historical seed CSV found at "
        f"{historical_csv}. Add the historical CSV to the repo, or pass "
        "--allow-empty-seed to rebuild entirely from Blockworks."
    )


def sync_once(args: argparse.Namespace) -> dict[str, Any]:
    visualization = load_page_visualization()
    query_id = args.query_id or visualization["queryId"]
    execution_id = latest_execution_id(query_id, visualization.get("lastExecutionId"))
    source_rows = fetch_execution_rows(execution_id)
    series = series_from_visualization(visualization)
    fieldnames = [
        "block_date",
        *(column.output_key for column in series),
    ]

    seed_csv, seed_source = choose_seed_csv(args)
    existing_rows = [] if seed_source == "empty_seed" else read_seed_rows(seed_csv, fieldnames)
    fresh_rows = build_fresh_rows(source_rows, series)
    merged_rows, merge_stats = merge_rows(
        existing_rows,
        fresh_rows,
        refresh_lookback_days=args.refresh_lookback_days,
    )
    csv_text = rows_to_csv(merged_rows, fieldnames)

    state_csv = Path(args.state_csv)
    write_text(state_csv, csv_text)
    if args.output_csv:
        write_text(Path(args.output_csv), csv_text)

    result: dict[str, Any] = {
        "csv_bytes": len(csv_text.encode("utf-8")),
        "execution_id": execution_id,
        "fresh_source_row_count": len(source_rows),
        "merged_row_count": len(merged_rows),
        "output_csv": args.output_csv,
        "query_id": query_id,
        "seed_csv": str(seed_csv),
        "seed_row_count": len(existing_rows),
        "seed_source": seed_source,
        "state_csv": str(state_csv),
        **merge_stats,
    }

    if args.skip_dune:
        result["dune_upload"] = "skipped"
        return result

    api_key = os.getenv("DUNE_API_KEY")
    if not api_key:
        raise RuntimeError("DUNE_API_KEY is required unless --skip-dune is set")

    result["dune_upload"] = upload_csv_to_dune(
        csv_text,
        api_key=api_key,
        table_name=args.table_name,
        description=args.description,
        is_private=args.is_private,
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query-id",
        default=os.getenv("BLOCKWORKS_QUERY_ID", DEFAULT_QUERY_ID),
        help="Blockworks query id. Defaults to 3056.",
    )
    parser.add_argument(
        "--historical-csv",
        default=os.getenv("HISTORICAL_CSV", DEFAULT_HISTORICAL_CSV),
        help="One-time seed CSV with historical data scraped earlier.",
    )
    parser.add_argument(
        "--state-csv",
        default=os.getenv("STATE_CSV", DEFAULT_STATE_CSV),
        help="Persisted CSV updated by every GitHub Actions run.",
    )
    parser.add_argument(
        "--output-csv",
        default=os.getenv("OUTPUT_CSV"),
        help="Optional extra copy of the merged upload CSV.",
    )
    parser.add_argument(
        "--refresh-lookback-days",
        type=int,
        default=int(os.getenv("REFRESH_LOOKBACK_DAYS", "7")),
        help="Refresh this many days before the current CSV max date to catch late updates.",
    )
    parser.add_argument(
        "--table-name",
        default=os.getenv("DUNE_TABLE_NAME", DEFAULT_TABLE_NAME),
        help="Dune upload table name. Dune will expose it as dataset_<table_name>.",
    )
    parser.add_argument(
        "--description",
        default=os.getenv(
            "DUNE_TABLE_DESCRIPTION",
            "Solana Spot DEX volume by pair category, seeded from historical CSV and updated daily from Blockworks.",
        ),
        help="Dune table description.",
    )
    parser.add_argument(
        "--private",
        dest="is_private",
        action="store_true",
        default=env_bool("DUNE_IS_PRIVATE", False),
        help="Upload as a private table. Requires a Dune Enterprise plan.",
    )
    parser.add_argument(
        "--allow-empty-seed",
        action="store_true",
        default=env_bool("ALLOW_EMPTY_SEED", False),
        help="Allow rebuilding from Blockworks if neither the state nor historical CSV exists.",
    )
    parser.add_argument(
        "--skip-dune",
        action="store_true",
        default=env_bool("SKIP_DUNE", False),
        help="Build/update the state CSV but do not upload to Dune.",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run forever, sleeping between syncs. Prefer GitHub Actions in production.",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=float(os.getenv("SYNC_INTERVAL_HOURS", "24")),
        help="Daemon sleep interval in hours.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    while True:
        try:
            result = sync_once(args)
            print(json.dumps(result, indent=2, sort_keys=True))
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            if not args.daemon:
                return 1

        if not args.daemon:
            return 0
        time.sleep(args.interval_hours * 60 * 60)


if __name__ == "__main__":
    raise SystemExit(main())
