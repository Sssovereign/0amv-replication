import datetime as dt
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from compass_0amv import extract_0amv as target


class PathResolutionTests(unittest.TestCase):
    def test_compass_root_builds_both_source_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            day = root / target.DAY_VDAT_RELATIVE
            day.parent.mkdir(parents=True)
            day.touch()
            args = SimpleNamespace(compass_root=root, day_vdat=None, cde=None)

            resolved_day, resolved_cde = target.resolve_source_paths(args)

            self.assertEqual(resolved_day, day)
            self.assertEqual(resolved_cde, root / target.CDE_RELATIVE)

    def test_explicit_day_path_works_without_compass_root(self):
        args = SimpleNamespace(
            compass_root=None,
            day_vdat=Path("/tmp/copied-day.vdat"),
            cde=None,
        )

        resolved_day, resolved_cde = target.resolve_source_paths(args)

        self.assertEqual(resolved_day, Path("/tmp/copied-day.vdat"))
        self.assertIsNone(resolved_cde)


class DayVdatTests(unittest.TestCase):
    def test_fixed_page_parser_keeps_values_below_1000(self):
        records = b"".join(
            [
                target.DAY_RECORD.pack(0.0, 19930103, 3.1, 3.3, 3.1, 3.3, 10.0),
                target.DAY_RECORD.pack(
                    317112800.0, 19930104, 10.1, 10.4, 9.9, 10.1, 20.0
                ),
            ]
        )
        frame, metadata = target.parse_day_vdat(b"prefix" + target.PAGE_HEADER + records)

        self.assertEqual(len(frame), 2)
        self.assertAlmostEqual(frame.iloc[0]["close"], 3.3, places=5)
        self.assertFalse(bool(frame.iloc[0]["amount_valid"]))
        self.assertEqual(metadata["data_page_count"], 1)


class CdeTests(unittest.TestCase):
    @staticmethod
    def make_cde() -> bytes:
        body = b"".join(
            [
                target.CDE_RECORD.pack(
                    93001, 100.0, 10.0, 20.0, 0.0, 100.0, 100.0, 0, 0, 0, 0, 0
                ),
                target.CDE_RECORD.pack(
                    150001, 105.0, 30.0, 40.0, 0.0, 110.0, 90.0, 0, 0, 0, 0, 0
                ),
            ]
        )
        header = bytearray(target.CDE_HEADER_SIZE)
        header[:4] = b"XADR"
        struct.pack_into("<I", header, 4, 20260831)
        struct.pack_into("<I", header, 18, len(body))
        return bytes(header) + body

    def test_cde_recovers_final_ohlc_and_marks_volume_amount_invalid(self):
        bar, metadata = target.parse_cde(self.make_cde())

        self.assertEqual(bar["date"], dt.date(2026, 8, 31))
        self.assertEqual((bar["open"], bar["high"], bar["low"], bar["close"]), (100, 110, 90, 105))
        self.assertTrue(metadata["is_final"])
        self.assertFalse(bar["volume_valid"])
        self.assertFalse(bar["amount_valid"])

    def reset_cde(self, final_time=150000, final_high=105, prior_reset=False):
        rows = [(93015,100,100,100),(145942,102,110,90),
                (145950,103,109 if prior_reset else 110,90),
                (final_time,105,final_high,105)]
        body = b"".join(target.CDE_RECORD.pack(t,c,10,20,0,h,l,0,0,0,0,0) for t,c,h,l in rows)
        header = bytearray(self.make_cde()[:target.CDE_HEADER_SIZE])
        struct.pack_into("<I",header,18,len(body))
        return bytes(header)+body

    def test_closing_tick_range_reset_preserves_intraday_extremes(self):
        bar,meta=target.parse_cde(self.reset_cde())
        self.assertEqual((bar['open'],bar['high'],bar['low'],bar['close']),(100,110,90,105))
        self.assertEqual(meta['range_source'],'prior_cumulative_range_plus_closing_tick')

    def test_arbitrary_or_intraday_range_loss_still_fails(self):
        for raw in [self.reset_cde(145959),self.reset_cde(final_high=106),self.reset_cde(prior_reset=True)]:
            with self.assertRaises(target.ParseError):target.parse_cde(raw)


class MergeTests(unittest.TestCase):
    @staticmethod
    def history(dates):
        rows = []
        for index, date in enumerate(dates):
            value = 100.0 + index
            rows.append(
                {
                    "date": date,
                    "open": value,
                    "high": value + 1,
                    "low": value - 1,
                    "close": value,
                    "volume": 1000.0,
                    "volume_valid": True,
                    "amount": 2000.0,
                    "amount_valid": True,
                    "source": "day.vdat",
                    "source_offset": 0,
                    "page_offset": 0,
                    "page_slot": index,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def cde_bar(date):
        return {
            "date": date,
            "open": 200.0,
            "high": 210.0,
            "low": 190.0,
            "close": 205.0,
            "volume": 3000.0,
            "volume_valid": False,
            "amount": 4000.0,
            "amount_valid": False,
            "source": "Z_SK0AMV__.cde",
            "source_offset": 0,
            "page_offset": pd.NA,
            "page_slot": pd.NA,
        }

    def test_newer_final_cde_date_is_appended(self):
        history = self.history([dt.date(2026, 8, 31)])
        result, info = target.merge_current_bar(
            history, self.cde_bar(dt.date(2026, 9, 1)), False, True
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(info["action"], "appended_new_date")
        self.assertEqual(result.iloc[-1]["source"], "Z_SK0AMV__.cde")

    def test_day_vdat_wins_for_existing_date(self):
        history = self.history([dt.date(2026, 8, 31)])
        result, info = target.merge_current_bar(
            history, self.cde_bar(dt.date(2026, 8, 31)), False, True
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(info["action"], "kept_day_vdat_existing_date")
        self.assertEqual(result.iloc[0]["source"], "day.vdat")

    def test_stale_nonexisting_cde_date_is_skipped(self):
        history = self.history([dt.date(2026, 8, 30), dt.date(2026, 9, 1)])
        result, info = target.merge_current_bar(
            history, self.cde_bar(dt.date(2026, 8, 31)), False, True
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(info["action"], "skipped_stale_cde")


class HistoryFallbackTests(unittest.TestCase):
    def test_previous_csv_can_seed_history_when_day_file_is_locked(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            pd.DataFrame(
                [
                    {
                        "date": "2026-08-31",
                        "open": 100.0,
                        "high": 110.0,
                        "low": 90.0,
                        "close": 105.0,
                        "volume": 1000.0,
                        "volume_valid": True,
                        "amount": 2000.0,
                        "amount_valid": True,
                        "source": "day.vdat",
                    }
                ]
            ).to_csv(output_dir / "0amv_daily.csv", index=False)

            frame, metadata = target.load_history_fallback(output_dir)

            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.iloc[0]["date"], dt.date(2026, 8, 31))
            self.assertEqual(metadata["last_date"], "2026-08-31")


if __name__ == "__main__":
    unittest.main()
