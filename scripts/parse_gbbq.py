#!/usr/bin/env python3
"""通达信 gbbq 股本变迁文件 -> work/gbbq_events.csv（pytdx 解密）。

gbbq 位置: <通达信>/T0002/hq_cache/gbbq，随盘后行情自动更新，
覆盖 19 万+ 条历史股本事件（送股/配股/解禁等）。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amv import config


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--gbbq', default=str(config.GBBQ),
                    help=f'gbbq 文件路径（默认 {config.GBBQ}）')
    args = ap.parse_args()

    from pytdx.reader.gbbq_reader import GbbqReader
    t0 = time.time()
    df = GbbqReader().get_df(args.gbbq)
    print(f'{len(df)} events in {time.time() - t0:.0f}s')
    print(df['category'].value_counts().head(10).to_string())

    out = Path(config.WORK)
    out.mkdir(parents=True, exist_ok=True)
    out = out / 'gbbq_events.csv'
    df.to_csv(out, index=False)
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
