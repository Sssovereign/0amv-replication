#!/usr/bin/env python3
"""Extract Compass Z_SK0AMV daily history without modifying Compass files.

`day.vdat` is authoritative for every flushed date. The current
`Z_SK0AMV__.cde` cache can supply exact completed-day OHLC before Compass
flushes that date, but its volume and amount are deliberately marked invalid.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import math
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

DAY_VDAT_RELATIVE = Path("WavMain/ANALYSE/Data/ChinaStk/Z_SK/day.vdat")
CDE_RELATIVE = Path("WavMain/Temp/Z_SK0AMV__.cde")

CODE = b"Z_SK0AMV"
PAGE_HEADER = CODE.ljust(28, b"\x00")
PAGE_RECORDS = 250
DAY_RECORD = struct.Struct("<fIfffff")  # amount, YYYYMMDD, O, H, L, C, volume
CDE_HEADER_SIZE = 22
CDE_RECORD = struct.Struct("<I11f")  # HHMMSS, last, volume, amount, ..., high, low, ...
INITIALIZATION_DATE = dt.date(1993, 1, 3)


class ParseError(RuntimeError):
    """Raised when a source file cannot satisfy the known binary contract."""


def discover_compass_roots() -> list[Path]:
    """Find unambiguous common Compass roots without embedding user paths."""
    candidates: list[Path] = []
    if os.name == "nt":
        candidates.append(Path("C:/Compass"))
    elif sys.platform == "darwin":
        volumes = Path("/Volumes")
        if volumes.is_dir():
            try:
                candidates.extend(volume / "Compass" for volume in volumes.iterdir())
            except OSError:
                pass

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.expanduser()
        if not (candidate / DAY_VDAT_RELATIVE).is_file():
            continue
        key = str(candidate.resolve())
        if key not in seen:
            seen.add(key)
            roots.append(candidate)
    return roots


def resolve_source_paths(args: argparse.Namespace) -> tuple[Path, Path | None]:
    """Resolve explicit paths first, then COMPASS_ROOT, then safe discovery."""
    root = args.compass_root
    if root is None:
        environment_root = os.environ.get("COMPASS_ROOT")
        root = Path(environment_root) if environment_root else None

    if root is None and args.day_vdat is None:
        discovered = discover_compass_roots()
        if len(discovered) > 1:
            options = ", ".join(str(path) for path in discovered)
            raise ParseError(
                f"Multiple Compass installations found ({options}); pass --compass-root"
            )
        if discovered:
            root = discovered[0]

    if root is not None:
        root = root.expanduser()

    if args.day_vdat is not None:
        day_vdat = args.day_vdat.expanduser()
    elif root is not None:
        day_vdat = root / DAY_VDAT_RELATIVE
    else:
        raise ParseError(
            "Compass location is unknown; pass --compass-root or --day-vdat, "
            "or set COMPASS_ROOT"
        )

    if args.cde is not None:
        cde = args.cde.expanduser()
    elif root is not None:
        cde = root / CDE_RELATIVE
    else:
        cde = None
    return day_vdat, cde


def default_output_dir() -> Path:
    configured = os.environ.get("COMPASS_0AMV_OUTPUT_DIR")
    return Path(configured).expanduser() if configured else Path.cwd() / "output"


def stable_read(
    path: Path, attempts: int = 3, pause: float = 0.2
) -> tuple[bytes, os.stat_result]:
    """Read only when size and mtime remain stable across the read."""
    if not path.exists():
        raise ParseError(f"Source file does not exist: {path}")
    for _ in range(attempts):
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        if (
            before.st_size == after.st_size == len(data)
            and before.st_mtime_ns == after.st_mtime_ns
        ):
            return data, after
        time.sleep(pause)
    raise ParseError(f"Source file changed repeatedly while being read: {path}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_date(value: int) -> dt.date | None:
    text = str(value)
    if len(text) != 8:
        return None
    try:
        date = dt.datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None
    if not (1990 <= date.year <= dt.date.today().year + 1):
        return None
    return date


def valid_ohlcv(
    open_: float, high: float, low: float, close: float, volume: float
) -> bool:
    values = (open_, high, low, close, volume)
    if not all(math.isfinite(value) and value > 0 for value in values):
        return False
    return low <= min(open_, close) <= max(open_, close) <= high


def parse_day_vdat(data: bytes) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse only fixed pages explicitly headed by `Z_SK0AMV`."""
    offsets: list[int] = []
    cursor = 0
    while True:
        offset = data.find(PAGE_HEADER, cursor)
        if offset < 0:
            break
        offsets.append(offset)
        cursor = offset + 1

    pages: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for offset in offsets:
        page_rows: list[dict[str, Any]] = []
        for slot in range(PAGE_RECORDS):
            record_offset = offset + len(PAGE_HEADER) + slot * DAY_RECORD.size
            if record_offset + DAY_RECORD.size > len(data):
                break
            amount, date_value, open_, high, low, close, volume = DAY_RECORD.unpack_from(
                data, record_offset
            )
            date = parse_date(date_value)
            if date is None or not valid_ohlcv(open_, high, low, close, volume):
                break
            if not math.isfinite(amount) or amount < 0:
                raise ParseError(
                    f"Invalid amount at page {offset}, slot {slot}: {amount}"
                )
            if page_rows and date <= page_rows[-1]["date"]:
                raise ParseError(
                    f"Non-increasing page dates at {offset}: "
                    f"{page_rows[-1]['date']} -> {date}"
                )
            page_rows.append(
                {
                    "date": date,
                    "open": float(open_),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume),
                    "volume_valid": True,
                    "amount": float(amount),
                    "amount_valid": bool(amount > 0),
                    "source": "day.vdat",
                    "source_offset": record_offset,
                    "page_offset": offset,
                    "page_slot": slot,
                }
            )

        # Index-table occurrences have no valid first record and are ignored.
        if page_rows:
            pages.append(
                {
                    "offset": offset,
                    "rows": len(page_rows),
                    "first_date": page_rows[0]["date"].isoformat(),
                    "last_date": page_rows[-1]["date"].isoformat(),
                }
            )
            rows.extend(page_rows)

    if not rows:
        raise ParseError("No valid Z_SK0AMV data pages found")

    frame = pd.DataFrame(rows).sort_values("date", kind="stable").reset_index(drop=True)
    duplicate_dates = frame.loc[frame["date"].duplicated(keep=False), "date"]
    if not duplicate_dates.empty:
        sample = sorted({date.isoformat() for date in duplicate_dates})[:10]
        raise ParseError(f"Duplicate dates found: {sample}")
    if not frame["date"].is_monotonic_increasing:
        raise ParseError("Daily dates are not increasing")

    metadata = {
        "candidate_header_occurrences": len(offsets),
        "data_pages": pages,
        "data_page_count": len(pages),
        "rows": int(len(frame)),
        "first_date": frame.iloc[0]["date"].isoformat(),
        "last_date": frame.iloc[-1]["date"].isoformat(),
        "zero_amount_rows": int((~frame["amount_valid"]).sum()),
    }
    return frame, metadata


def parse_cde(data: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse the current intraday cache into one completed/provisional bar."""
    if len(data) < CDE_HEADER_SIZE or data[:4] != b"XADR":
        raise ParseError("CDE magic/header is not recognized")

    date_value = struct.unpack_from("<I", data, 4)[0]
    date = parse_date(date_value)
    if date is None:
        raise ParseError(f"Invalid CDE date: {date_value}")

    declared_body_size = struct.unpack_from("<I", data, 18)[0]
    body = data[CDE_HEADER_SIZE:]
    if declared_body_size != len(body):
        raise ParseError(
            f"CDE body length mismatch: header={declared_body_size}, actual={len(body)}"
        )
    if not body or len(body) % CDE_RECORD.size:
        raise ParseError(
            f"CDE body is not a multiple of {CDE_RECORD.size}: {len(body)}"
        )

    records = [
        CDE_RECORD.unpack_from(body, offset)
        for offset in range(0, len(body), CDE_RECORD.size)
    ]
    times = [record[0] for record in records]
    if times != sorted(times):
        raise ParseError("CDE times are not increasing")

    for index, record in enumerate(records):
        _, last, volume, amount, _, high, low, *_ = record
        values = (last, volume, amount, high, low)
        if not all(math.isfinite(value) for value in values):
            raise ParseError(f"Non-finite CDE value at record {index}")
        if last <= 0 or high <= 0 or low <= 0 or volume < 0 or amount < 0:
            raise ParseError(f"Invalid CDE value at record {index}")
        if low > last or last > high:
            raise ParseError(f"CDE last outside high/low at record {index}")

    first = records[0]
    last = records[-1]
    observed = [float(record[1]) for record in records]
    open_ = float(first[1])
    high = float(last[5])
    low = float(last[6])
    close = float(last[1])
    range_source = "final_record"
    if high < max(observed) or low > min(observed):
        # Compass may emit a 15:00 closing tick with H=L=close, resetting
        # the cumulative range. Require an intact prior cumulative series;
        # never accept arbitrary truncated ranges or intraday resets.
        prior = records[:-1]
        closing_reset = (
            int(last[0]) >= 150000 and prior and int(prior[-1][0]) < 150000
            and high == low == close
            and all(b[5] >= a[5] and b[6] <= a[6]
                    for a, b in zip(prior, prior[1:]))
            and float(prior[-1][5]) >= max(observed[:-1])
            and float(prior[-1][6]) <= min(observed[:-1])
        )
        if not closing_reset:
            raise ParseError("CDE final high/low does not cover observed values")
        high = max(float(prior[-1][5]), close)
        low = min(float(prior[-1][6]), close)
        range_source = "prior_cumulative_range_plus_closing_tick"

    final_time = int(last[0])
    is_final = final_time >= 150000
    bar = {
        "date": date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": float(last[2]),
        "volume_valid": False,
        "amount": float(last[3]),
        "amount_valid": False,
        "source": "Z_SK0AMV__.cde",
        "source_offset": CDE_HEADER_SIZE + (len(records) - 1) * CDE_RECORD.size,
        "page_offset": pd.NA,
        "page_slot": pd.NA,
    }
    metadata = {
        "date": date.isoformat(),
        "records": len(records),
        "first_time": int(first[0]),
        "last_time": final_time,
        "is_final": is_final,
        "ohlc_authoritative_after_close": is_final,
        "range_source": range_source,
        "volume_amount_authoritative": False,
        "bar": {
            key: bar[key]
            for key in ("open", "high", "low", "close", "volume", "amount")
        },
    }
    return bar, metadata


def merge_current_bar(
    history: pd.DataFrame,
    bar: dict[str, Any],
    include_provisional: bool,
    is_final: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Merge CDE only when it adds a newer date; day.vdat always wins."""
    date = bar["date"]
    result = history.copy()
    existing = result["date"] == date
    comparison: dict[str, float] = {}

    if not is_final and not include_provisional:
        return result, {"action": "skipped_provisional", "comparison": comparison}

    if existing.any():
        old = result.loc[existing].iloc[0]
        for field in ("open", "high", "low", "close", "volume", "amount"):
            comparison[f"{field}_difference"] = float(bar[field] - old[field])
        return result, {
            "action": "kept_day_vdat_existing_date",
            "comparison": comparison,
        }

    latest_history_date = result["date"].max()
    if date < latest_history_date:
        return result, {"action": "skipped_stale_cde", "comparison": comparison}

    result = pd.concat([result, pd.DataFrame([bar])], ignore_index=True)
    result = result.sort_values("date", kind="stable").reset_index(drop=True)
    return result, {"action": "appended_new_date", "comparison": comparison}


def compare_reference(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    reference = pd.read_csv(path, encoding="utf-8-sig", parse_dates=["date"])
    current = frame.copy()
    current["date"] = pd.to_datetime(current["date"])
    merged = reference.merge(
        current, on="date", how="left", suffixes=("_reference", "_current")
    )
    fields = ("open", "high", "low", "close", "volume")
    tolerances = {
        "open": 0.11,
        "high": 0.11,
        "low": 0.11,
        "close": 0.11,
        "volume": 500_000.0,
    }
    max_differences: dict[str, float] = {}
    mismatch_counts: dict[str, int] = {}
    for field in fields:
        difference = (merged[f"{field}_current"] - merged[f"{field}_reference"]).abs()
        max_differences[field] = float(difference.max())
        mismatch_counts[field] = int((difference > tolerances[field]).sum())
    return {
        "path": str(path),
        "reference_rows": int(len(reference)),
        "missing_dates": int(merged["close_current"].isna().sum()),
        "max_absolute_differences": max_differences,
        "mismatch_counts_beyond_tolerance": mismatch_counts,
    }


def file_metadata(path: Path, data: bytes, stat: os.stat_result) -> dict[str, Any]:
    return {
        "path": str(path),
        "size": len(data),
        "mtime": dt.datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        "sha256": sha256(data),
    }


def load_history_fallback(output_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load this tool's previous CSV when Compass has locked day.vdat."""
    path = output_dir / "0amv_daily.csv"
    if not path.exists():
        raise ParseError(
            "day.vdat is locked and no previous 0amv_daily.csv exists; "
            "close Compass once to seed the history"
        )
    data, stat = stable_read(path)
    frame = pd.read_csv(io.BytesIO(data), parse_dates=["date"])
    required_columns = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "volume_valid",
        "amount",
        "amount_valid",
        "source",
    ]
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        raise ParseError(f"History fallback is missing columns: {missing}")
    if frame.empty or frame["date"].isna().any():
        raise ParseError("History fallback has no valid dated rows")

    for field in ("volume_valid", "amount_valid"):
        if frame[field].dtype != bool:
            normalized = frame[field].astype(str).map({"True": True, "False": False})
            if normalized.isna().any():
                raise ParseError(f"History fallback has invalid {field} values")
            frame[field] = normalized.astype(bool)

    frame["date"] = frame["date"].dt.date
    if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
        raise ParseError("History fallback dates are duplicated or unordered")
    for row in frame.itertuples(index=False):
        if not valid_ohlcv(row.open, row.high, row.low, row.close, row.volume):
            raise ParseError(f"History fallback has invalid OHLCV on {row.date}")
        if not math.isfinite(row.amount) or row.amount < 0:
            raise ParseError(f"History fallback has invalid amount on {row.date}")

    frame = frame[required_columns].copy()
    frame["source_offset"] = pd.NA
    frame["page_offset"] = pd.NA
    frame["page_slot"] = pd.NA
    metadata = {
        **file_metadata(path, data, stat),
        "rows": int(len(frame)),
        "first_date": frame.iloc[0]["date"].isoformat(),
        "last_date": frame.iloc[-1]["date"].isoformat(),
    }
    return frame, metadata


def atomic_output(frame: pd.DataFrame, manifest: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "0amv_daily.csv"
    pkl_path = output_dir / "0amv_daily.pkl"
    manifest_path = output_dir / "manifest.json"
    csv_tmp = csv_path.with_suffix(".csv.tmp")
    pkl_tmp = pkl_path.with_suffix(".pkl.tmp")
    manifest_tmp = manifest_path.with_suffix(".json.tmp")

    export = frame.copy()
    export["date"] = pd.to_datetime(export["date"])
    export["change_pct"] = export["close"].pct_change(fill_method=None) * 100.0
    export["is_weekend"] = export["date"].dt.weekday >= 5
    export["is_research_row"] = export["date"].dt.date != INITIALIZATION_DATE
    export = export[
        [
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "volume_valid",
            "amount",
            "amount_valid",
            "change_pct",
            "is_weekend",
            "is_research_row",
            "source",
        ]
    ]

    export.to_csv(csv_tmp, index=False, date_format="%Y-%m-%d")
    export.to_pickle(pkl_tmp)
    manifest_tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(csv_tmp, csv_path)
    os.replace(pkl_tmp, pkl_path)
    os.replace(manifest_tmp, manifest_path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    day_vdat, cde = resolve_source_paths(args)
    output_dir = args.output_dir.expanduser()
    sources: dict[str, Any] = {}
    try:
        day_data, day_stat = stable_read(day_vdat)
        frame, day_info = parse_day_vdat(day_data)
        sources["day_vdat"] = file_metadata(day_vdat, day_data, day_stat)
        day_manifest = {"status": "parsed", **day_info}
    except PermissionError as error:
        if not args.history_fallback:
            raise
        frame, fallback_info = load_history_fallback(output_dir)
        sources["day_vdat"] = {
            "path": str(day_vdat),
            "status": "permission_denied",
            "error": str(error),
        }
        sources["history_fallback"] = fallback_info
        day_manifest = {
            "status": "locked_used_existing_output",
            "rows": int(len(frame)),
            "first_date": frame.iloc[0]["date"].isoformat(),
            "last_date": frame.iloc[-1]["date"].isoformat(),
        }

    manifest: dict[str, Any] = {
        "format_version": 3,
        "extracted_at": dt.datetime.now().astimezone().isoformat(),
        "instrument": "Z_SK0AMV",
        "sources": sources,
        "day_vdat": day_manifest,
        "cde": {"status": "not_available"},
    }

    if cde is not None and cde.exists():
        cde_data, cde_stat = stable_read(cde)
        bar, cde_info = parse_cde(cde_data)
        if bar["date"] > dt.date.today():
            raise ParseError(f"CDE date is in the future: {bar['date']}")
        frame, merge_info = merge_current_bar(
            frame,
            bar,
            include_provisional=args.include_provisional,
            is_final=bool(cde_info["is_final"]),
        )
        manifest["sources"]["cde"] = file_metadata(cde, cde_data, cde_stat)
        manifest["cde"] = {"status": "parsed", **cde_info, "merge": merge_info}

    dates = pd.to_datetime(frame["date"])
    weekend_dates = dates[dates.dt.weekday >= 5].dt.strftime("%Y-%m-%d").tolist()
    long_gaps = []
    for previous, current in zip(dates.iloc[:-1], dates.iloc[1:]):
        days = int((current - previous).days)
        if days > 10:
            long_gaps.append(
                {
                    "previous": previous.strftime("%Y-%m-%d"),
                    "current": current.strftime("%Y-%m-%d"),
                    "calendar_days": days,
                }
            )

    last_date = dates.iloc[-1].date()
    if args.expected_date and last_date != args.expected_date:
        cde_state = manifest["cde"]
        current = (f'{cde_state["date"]}（'
                   f'{"已收盘" if cde_state["is_final"] else "盘中，未作为完整日线"}）'
                   if cde_state["status"] == "parsed" else "不可用")
        if day_manifest["status"] == "locked_used_existing_output":
            reason = (f'指南针正在占用历史文件，备用历史截至 {day_manifest["last_date"]}，'
                      f'当前活跃市值缓存 {current}。请先正常退出指南针，'
                      '让行情保存并释放文件，再重新复盘；仍缺日期时请先更新指南针行情。')
        else:
            reason = (f'指南针历史截至 {day_manifest["last_date"]}，'
                      f'当前活跃市值缓存 {current}。请在指南针更新所需日期的行情，'
                      '收盘后正常退出保存，再重新复盘。')
        raise ParseError(
            f"Expected final date {args.expected_date}, extracted {last_date}。{reason}"
        )

    manifest["result"] = {
        "rows": int(len(frame)),
        "research_rows": int((dates.dt.date != INITIALIZATION_DATE).sum()),
        "first_date": dates.iloc[0].strftime("%Y-%m-%d"),
        "last_date": dates.iloc[-1].strftime("%Y-%m-%d"),
        "duplicate_dates": int(dates.duplicated().sum()),
        "weekend_dates": weekend_dates,
        "long_gaps_over_10_calendar_days": long_gaps,
        "invalid_volume_rows": int((~frame["volume_valid"]).sum()),
        "invalid_amount_rows": int((~frame["amount_valid"]).sum()),
        "zero_amount_rows": int((frame["amount"] == 0).sum()),
    }
    if args.reference_csv:
        manifest["reference_comparison"] = compare_reference(frame, args.reference_csv)

    manifest["output_dir"] = str(output_dir.resolve())
    atomic_output(frame, manifest, output_dir)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Compass Z_SK0AMV daily history")
    parser.add_argument(
        "--compass-root",
        type=Path,
        help="Compass installation root containing WavMain",
    )
    parser.add_argument("--day-vdat", type=Path, help="explicit day.vdat path")
    parser.add_argument("--cde", type=Path, help="explicit Z_SK0AMV__.cde path")
    parser.add_argument("--output-dir", type=Path, default=default_output_dir())
    parser.add_argument("--reference-csv", type=Path)
    parser.add_argument(
        "--expected-date",
        type=dt.date.fromisoformat,
        help="fail without replacing outputs unless the final date equals YYYY-MM-DD",
    )
    parser.add_argument(
        "--include-provisional",
        action="store_true",
        help="include CDE before its last timestamp reaches 15:00:00",
    )
    parser.add_argument(
        "--no-history-fallback",
        dest="history_fallback",
        action="store_false",
        default=True,
        help="fail instead of using the previous CSV when day.vdat is locked",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = run(args)
    except (OSError, ParseError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    result = manifest["result"]
    print(
        f"Z_SK0AMV: {result['rows']} source rows, "
        f"{result['research_rows']} research rows, "
        f"{result['first_date']}..{result['last_date']}"
    )
    print(f"output: {manifest['output_dir']}")
    if manifest["cde"].get("status") == "parsed":
        cde = manifest["cde"]
        print(
            f"CDE: {cde['date']} last_time={cde['last_time']} "
            f"final={cde['is_final']} action={cde['merge']['action']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
