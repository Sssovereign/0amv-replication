#!/usr/bin/env python3
"""OHLC 四价估算 + walk-forward 过拟合检验 + 官方缺失日预测（v4 扩展）。

日内口径: 昨日记忆(未含今日量) × 今日 open/high/low —— 筹码盘中不变、收盘后更新；
收盘口径: 今日更新后记忆 × close（同 v5 池）。
产物: work/combo_v4_ohlc.csv (date,open,high,low,close,is_predicted)
"""
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
    t0 = time.time()
    lad_d, lad_v = core.float_ladders(WORK / 'gbbq_events.csv')

    recs = []
    sid = 0
    code_by_sid = {}
    for f in tdx.a_stock_day_files(config.TDX_ROOT):
        code = tdx.code_of_file(f)
        rec = tdx.read_day_file(f)
        code_by_sid[sid] = code
        if len(rec):
            ok = (np.isfinite(rec['amount']) & (rec['close'] > 0) & (rec['open'] > 0))
            for i in np.nonzero(ok)[0]:
                d = int(rec['date'][i])
                if d < core.WARMUP_START:
                    continue
                recs.append((sid, d, float(rec['amount'][i]), float(rec['vol'][i]),
                             rec['open'][i] / 100.0, rec['high'][i] / 100.0,
                             rec['low'][i] / 100.0, rec['close'][i] / 100.0))
        sid += 1
    by_day = defaultdict(list)
    for r in recs:
        by_day[r[1]].append((r[0], *r[2:]))
    del recs
    all_dates = sorted(by_day)
    print(f'{sid} stocks, {len(all_dates)} days, loaded {time.time()-t0:.0f}s')

    scales = core.SCALES
    mems = {n: np.zeros(sid) for n in scales}
    AGG = {px: {n: {} for n in scales} for px in ('open', 'high', 'low', 'close')}
    MVX = {px: {} for px in ('open', 'high', 'low', 'close')}
    A = {}
    for d in all_dates:
        items = by_day[d]
        idxs = np.fromiter((it[0] for it in items), dtype=np.int64, count=len(items))
        vols = np.fromiter((it[2] for it in items), dtype=np.float64, count=len(items))
        px = {p: np.fromiter((it[k] for it in items), dtype=np.float64, count=len(items))
              for k, p in zip((3, 4, 5, 6), ('open', 'high', 'low', 'close'))}
        amounts = np.fromiter((it[1] for it in items), dtype=np.float64, count=len(items))
        fl = np.full(len(items), np.nan)
        for j, st in enumerate(idxs):
            dl = lad_d.get(code_by_sid[st])
            if dl:
                k = bisect.bisect_right(dl, d) - 1
                if k >= 0:
                    fl[j] = lad_v[code_by_sid[st]][k] * 1e4
        has_fl = ~np.isnan(fl)
        # 日内口径：昨日记忆 × 今日 OHLC
        for n in scales:
            m = mems[n]
            cur = m[idxs]
            for p in ('open', 'high', 'low'):
                AGG[p][n][d] = float(np.dot(cur, px[p]))
        # 收盘口径：今日更新后记忆 × close
        for n in scales:
            m = mems[n]
            m[idxs] = m[idxs] * (1 - 1.0 / n) + vols
            m[idxs[has_fl]] = np.minimum(m[idxs[has_fl]], fl[has_fl])
            AGG['close'][n][d] = float(np.dot(m[idxs], px['close']))
        for p in ('open', 'high', 'low'):
            MVX[p][d] = float(np.nansum(fl * px[p]))
        MVX['close'][d] = float(np.nansum(fl * px['close']))
        A[d] = float(amounts.sum())
    print(f'pools built {time.time()-t0:.0f}s')

    official = {}
    with open(WORK / 'official_amv_ohlc.csv', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            official[row['date']] = {k: (float(row[k]) if row[k] else None)
                                     for k in ('open', 'high', 'low', 'close')}

    full_days = [d for d in all_dates if d >= core.FIT_LO]
    train_days = [d for d in full_days if str(d) in official
                  and core.FIT_LO <= d <= core.FIT_HI]
    print(f'train days {len(train_days)}, full {len(full_days)}')
    row_of = {d: i for i, d in enumerate(full_days)}

    def fit_and_predict(target):
        y = np.array([np.log(official[str(d)][target]) for d in train_days])
        cols = []
        series_map = {n: AGG[target][n] for n in scales}
        for name, series in ([(f'MEM{n}', series_map[n]) for n in scales]
                             + [('MV', MVX[target]), ('A', A)]):
            arr = np.array([np.log(max(series[d], 1e-9)) for d in train_days])
            mu, sd = arr.mean(), arr.std()
            cols.append((np.array([np.log(max(series[d], 1e-9)) for d in full_days]) - mu) / sd)
        Xf = np.column_stack(cols + [np.ones(len(full_days))])
        Xtr = Xf[[row_of[d] for d in train_days]]
        beta = np.linalg.solve(Xtr.T @ Xtr + core.ALPHA * np.eye(Xtr.shape[1]), Xtr.T @ y)
        return beta, np.exp(Xf @ beta)

    results = {}
    print('\n各价回归系数（拟合窗口 2011-2023）:')
    for target in ('close', 'open', 'high', 'low'):
        beta, pred_full = fit_and_predict(target)
        results[target] = pred_full
        o_tr = np.array([official[str(d)][target] for d in train_days])
        p_tr = np.array([pred_full[row_of[d]] for d in train_days])
        print(f'[{target:5s}] 拟合内相似度 {100-np.mean(np.abs(p_tr/o_tr-1))*100:.1f}%')

    print('\n[walk-forward, close] train 2011..Y → test Y+1:')
    sims = []
    for Y in range(2016, 2026):
        tr = [d for d in train_days if d <= Y * 10000 + 1231]
        te = [d for d in full_days if Y * 10000 + 1231 < d <= (Y + 1) * 10000 + 1231
              and str(d) in official]
        if not tr or not te:
            continue
        y = np.array([np.log(official[str(d)]['close']) for d in tr])
        cols = []
        for name, series in ([(f'MEM{n}', AGG['close'][n]) for n in scales]
                             + [('MV', MVX['close']), ('A', A)]):
            arr = np.array([np.log(max(series[d], 1e-9)) for d in tr])
            mu, sd = arr.mean(), arr.std()
            cols.append((np.array([np.log(max(series[d], 1e-9)) for d in full_days]) - mu) / sd)
        Xf = np.column_stack(cols + [np.ones(len(full_days))])
        Xtr = Xf[[row_of[d] for d in tr]]
        beta_wf = np.linalg.solve(Xtr.T @ Xtr + core.ALPHA * np.eye(Xtr.shape[1]), Xtr.T @ y)
        pf = np.exp(Xf @ beta_wf)
        o_te = np.array([official[str(d)]['close'] for d in te])
        p_te = np.array([pf[row_of[d]] for d in te])
        sim = 100 - np.mean(np.abs(p_te / o_te - 1)) * 100
        sims.append(sim)
        print(f'  train→{Y} test {Y+1}: 相似度 {sim:.1f}%  ({len(te)} 天)')
    print(f'walk-forward 平均相似度: {np.mean(sims):.2f}%  最差 {np.min(sims):.1f}%')

    last_off = max(int(d) for d in official)
    missing = [d for d in full_days if d > last_off]
    print(f'\n[缺失日预测] 官方最后 {last_off}, 预测: {missing}')
    for d in missing:
        i = row_of[d]
        vals = {t: results[t][i] for t in ('open', 'high', 'low', 'close')}
        top, bot = max(vals['open'], vals['close']), min(vals['open'], vals['close'])
        vals['high'] = max(top, vals['high'])
        vals['low'] = min(bot, vals['low'])
        print(f'{d}  开 {vals["open"]:9.1f}  高 {vals["high"]:9.1f}  '
              f'低 {vals["low"]:9.1f}  收 {vals["close"]:9.1f}')
        assert vals['low'] <= vals['open'] <= vals['high']
        assert vals['low'] <= vals['close'] <= vals['high']

    WORK.mkdir(parents=True, exist_ok=True)
    with open(WORK / 'combo_v4_ohlc.csv', 'w', encoding='utf-8') as f:
        f.write('date,open,high,low,close,is_predicted\n')
        for d in full_days:
            i = row_of[d]
            is_pred = 0 if str(d) in official else 1
            vals = [results[t][i] for t in ('open', 'high', 'low', 'close')]
            f.write(f'{d},{vals[0]:.2f},{vals[1]:.2f},{vals[2]:.2f},{vals[3]:.2f},{is_pred}\n')
    print(f'\nwrote {WORK}/combo_v4_ohlc.csv ({time.time()-t0:.0f}s)')


if __name__ == '__main__':
    main()
