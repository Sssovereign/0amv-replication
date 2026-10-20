#!/usr/bin/env python3
"""官方 0AMV 真值 CSV -> work/official_amv.csv + work/official_amv_ohlc.csv。

数据来源见 docs/data.md。两种输入格式自动识别:
- tools/compass_0amv 提取的 0amv_daily.csv（--compass-dir）
- 融合看板运行格式 active_market_amplitude.csv（--src）
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amv import config
from amv.official import fill_dod, parse_rows, write_snapshots


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--src', help='官方 CSV 路径（两种格式自动识别）')
    ap.add_argument('--compass-dir', help='指南针提取器输出目录（含 0amv_daily.csv）')
    args = ap.parse_args()
    if args.src:
        src = Path(args.src)
    elif args.compass_dir:
        src = Path(args.compass_dir) / '0amv_daily.csv'
    else:
        ap.error('需要 --src 或 --compass-dir 之一')
    if not src.is_file():
        raise SystemExit(f'找不到官方 CSV: {src}')

    rows = parse_rows(src)
    n = sum(1 for r in rows if r[5] is None)
    rows = fill_dod(rows)
    count = write_snapshots(rows, Path(config.WORK))
    print(f'{count} days -> {config.WORK}/official_amv.csv + official_amv_ohlc.csv')
    print(f'first: {rows[0][0]}  last: {rows[-1][0]}  dod补算 {n} 天')


if __name__ == '__main__':
    main()
