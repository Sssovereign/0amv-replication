#!/usr/bin/env python3
"""v3 基线拟合：多尺度成交记忆+流通市值+成交额 的 log 线性纯水平 ridge。

与定型 v5 的差别仅在回归目标（v3 无差分项），用于对照评估
“纯水平拟合能否满足 ±4%/−2.3% 波段判定”。
产物: work/combo_v3_pred.csv (date,official,fitted,dod_official,dod_fitted)
      work/combo_v3_params.txt
"""
import argparse
import bisect
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from amv import config, core, tdx

WORK = Path(config.WORK)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vol-auto', type=int, default=1,
                    help='自动检测 vol 单位（股/手），0=强制按原值')
    args = ap.parse_args()

    t0 = time.time()
    lad_d, lad_v = core.float_ladders(WORK / 'gbbq_events.csv')
    recs, code_of_sid = core.load_daily_records(
        tdx.a_stock_day_files(config.TDX_ROOT), tdx.code_of_file)
    sid = len(code_of_sid)
    by_day = defaultdict(list)
    for r in recs:
        by_day[r[1]].append(r)
    all_dates = sorted(by_day)
    print(f'{sid} stocks, {len(all_dates)} days {time.time()-t0:.0f}s')

    # vol 单位检测: amount/vol ≈ 股价(股) 或 股价/100(手)
    vol_unit = 1.0
    if args.vol_auto:
        probe = by_day[all_dates[-30]]
        ratios = [it[2] / it[3] for it in probe if it[3] > 0][:200]
        med = float(np.median(ratios))
        prices = [it[4] for it in probe[:200]]
        vol_unit = 1.0 if med > float(np.median(prices)) * 0.5 else 100.0
        print(f'vol unit ×{vol_unit} (amount/vol median {med:.1f})')

    scales = core.SCALES
    mems = {n: np.zeros(sid) for n in scales}
    MEM = {n: {} for n in scales}
    MV, A = {}, {}
    for d in all_dates:
        items = by_day[d]
        idxs = np.fromiter((it[0] for it in items), dtype=np.int64, count=len(items))
        vols = np.fromiter((it[3] for it in items), dtype=np.float64, count=len(items)) * vol_unit
        closes = np.fromiter((it[4] for it in items), dtype=np.float64, count=len(items))
        amounts = np.fromiter((it[2] for it in items), dtype=np.float64, count=len(items))
        fl = np.full(len(items), np.nan)
        for j, st in enumerate(idxs):
            dl = lad_d.get(code_of_sid[st])
            if dl:
                k = bisect.bisect_right(dl, d) - 1
                if k >= 0:
                    fl[j] = lad_v[code_of_sid[st]][k] * 1e4
        has_fl = ~np.isnan(fl)
        for n in scales:
            m = mems[n]
            m[idxs] = m[idxs] * (1 - 1.0 / n) + vols
            m[idxs[has_fl]] = np.minimum(m[idxs[has_fl]], fl[has_fl])
            MEM[n][d] = float(np.dot(m[idxs], closes))
        MV[d] = float(np.nansum(fl * closes))
        A[d] = float(amounts.sum())
    print(f'pools built {time.time()-t0:.0f}s')

    official = {}
    with open(WORK / 'official_amv.csv', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            official[row['date']] = float(row['close'])
    days = [d for d in all_dates if str(d) in official and d >= core.FIT_LO]
    o = np.array([official[str(d)] for d in days])
    logO = np.log(o)

    series = [(f'MEM{n}', MEM[n]) for n in scales] + [('MV', MV), ('A', A)]
    cols, stats = [], []
    for name, sd_ in series:
        arr = np.array([np.log(max(sd_[d], 1e-9)) for d in days])
        trm = (np.array(days) >= core.FIT_LO) & (np.array(days) <= core.FIT_HI)
        mu, sd = arr[trm].mean(), arr[trm].std()
        cols.append((arr - mu) / sd)
        stats.append((name, mu, sd))
    X = np.column_stack(cols + [np.ones(len(days))])

    fit_mask = (np.array(days) >= core.FIT_LO) & (np.array(days) <= core.FIT_HI)
    alpha = 0.01
    beta = np.linalg.solve(X[fit_mask].T @ X[fit_mask] + alpha * np.eye(X.shape[1]),
                           X[fit_mask].T @ logO[fit_mask])
    pred = np.exp(X @ beta)
    print('\n系数（log 线性）:')
    for (name, mu, sd), b in zip(stats, beta[:-1]):
        print(f'  {name:7s} w={b:+.4f}')
    print(f'  const   c={beta[-1]:+.4f}')

    fit_pred = pred
    sim_in = 100 - np.mean(np.abs(fit_pred[fit_mask] / o[fit_mask] - 1)) * 100
    sim_out = 100 - np.mean(np.abs(fit_pred[~fit_mask] / o[~fit_mask] - 1)) * 100
    print(f'\n[拟合内 2011-2023] 相似度={sim_in:.1f}%')
    print(f'[样本外 2024-2026] 相似度={sim_out:.1f}%')

    dod_o = np.concatenate([[0], (o[1:] / o[:-1] - 1) * 100])
    dod_f = np.concatenate([[0], (fit_pred[1:] / fit_pred[:-1] - 1) * 100])
    print(f'[日涨幅] 全窗口 MAE={np.mean(np.abs(dod_f[1:] - dod_o[1:])):.3f}pp')

    _bo, _, _, bull_o, _ = core.triggers(o, dod_o)
    _bf, _, _, bull_f, _ = core.triggers(fit_pred, dod_f)
    jac = len(bull_o & bull_f) / len(bull_o | bull_f)
    print(f'[波段] Jaccard={jac:.4f}  '
          f'官方多头{len(bull_o)}天 vs 估算{len(bull_f)}天')

    WORK.mkdir(parents=True, exist_ok=True)
    with open(WORK / 'combo_v3_pred.csv', 'w', encoding='utf-8') as f:
        f.write('date,official,fitted,dod_official,dod_fitted\n')
        for i, d in enumerate(days):
            f.write(f'{d},{o[i]:.2f},{fit_pred[i]:.2f},{dod_o[i]:.4f},{dod_f[i]:.4f}\n')
    with open(WORK / 'combo_v3_params.txt', 'w', encoding='utf-8') as f:
        for (name, mu, sd), b in zip(stats, beta[:-1]):
            f.write(f'{name}: w={b} z_mu={mu} z_sd={sd}\n')
        f.write(f'const: {beta[-1]}\n')
    print(f'\nwrote {WORK}/combo_v3_pred.csv ({time.time()-t0:.0f}s)')


if __name__ == '__main__':
    main()
