#!/usr/bin/env python3
"""v3 波段判定评估：定型同口径的触发日对照 + 逐波段对齐 + 年度分布。

回答“纯水平拟合（v3）能否正确反应 ±4%/−2.3% 波段”。
用法: PYTHONUTF8=1 python scripts/eval_v3.py [--pred work/combo_v3_pred.csv]
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amv import config, core


def bands_of(bulls):
    out, run = [], None
    for i in sorted(bulls):
        if run and i == run[1] + 1:
            run[1] = i
        else:
            run = [i, i]
            out.append(run)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pred', default=str(Path(config.WORK) / 'combo_v3_pred.csv'))
    args = ap.parse_args()

    rows = []
    with open(args.pred, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append((int(r['date']), float(r['official']), float(r['fitted']),
                         float(r['dod_official']), float(r['dod_fitted'])))
    dates = [r[0] for r in rows]
    o = [r[1] for r in rows]
    f3 = [r[2] for r in rows]
    do_ = [r[3] for r in rows]
    df_ = [r[4] for r in rows]
    n = len(rows)

    bo, eo, bro, bull_o, _ = core.triggers(o, do_)
    bf, ef, brf, bull_f, _ = core.triggers(f3, df_)

    print('== 触发日对照（全期，定型同口径）==')
    core.trigger_report('入场触发', bo, bf)
    core.trigger_report('出场触发', eo, ef)
    core.trigger_report('MA10破位', bro, brf)
    jac = len(bull_o & bull_f) / len(bull_o | bull_f)
    agree = sum(1 for i in range(n) if (i in bull_o) == (i in bull_f))
    print(f'  波段Jaccard {jac:.3f}   多头状态逐日一致率 {agree/n*100:.1f}%')

    bo24 = {i for i in bo if dates[i] >= 20240101}
    bf24 = {i for i in bf if dates[i] >= 20240101}
    eo24 = {i for i in eo if dates[i] >= 20240101}
    ef24 = {i for i in ef if dates[i] >= 20240101}
    print('\n== 样本外 2024+ ==')
    core.trigger_report('入场触发', bo24, bf24)
    core.trigger_report('出场触发', eo24, ef24)

    bo_bands, bf_bands = bands_of(bull_o), bands_of(bull_f)
    covered, missed, delays = 0, [], []
    for s, e in bo_bands:
        ov = [b for b in bf_bands if b[0] <= e and b[1] >= s]
        if ov:
            covered += 1
            delays.append(max(ov[0][0] - s, 0))
        else:
            missed.append((dates[s], dates[e]))
    print(f'\n== 逐官方波段（{len(bo_bands)}个）==')
    print(f'  覆盖 {covered}/{len(bo_bands)}  完全错过 {len(missed)} 个 {missed[:6]}')
    if delays:
        delays.sort()
        print(f'  入场延迟: 中位 {delays[len(delays)//2]} 天  均值 {sum(delays)/len(delays):.1f} 天  '
              f'>2天 {sum(1 for d in delays if d > 2)}个  最大 {delays[-1]} 天')

    by_year_f, by_year_m = defaultdict(int), defaultdict(int)
    for i in bf - bo:
        by_year_f[dates[i] // 10000] += 1
    for i in bo - bf:
        by_year_m[dates[i] // 10000] += 1
    print(f'\n== 假入场 {len(bf - bo)} 个 / 漏入场 {len(bo - bf)} 个 年度分布 ==')
    print('  年份:  假入场  漏入场')
    for y in sorted(set(by_year_f) | set(by_year_m)):
        print(f'  {y}:  {by_year_f.get(y, 0):4d}   {by_year_m.get(y, 0):4d}')


if __name__ == '__main__':
    main()
