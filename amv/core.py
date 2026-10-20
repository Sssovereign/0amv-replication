"""0AMV 复现核心数学：股本阶梯、成交记忆池、v5 混合回归、波段触发判定。

数值口径与定型实验逐一一致（差分目标 μ=100、ridge α=0.01、
2011-2023 定系数）；文件遍历采用确定性排序，聚合求和顺序可能带来
末位浮点差异，不影响任何指标。
"""
import bisect
from collections import defaultdict

import numpy as np
import pandas as pd

from .tdx import read_day_file

SCALES = (5, 10, 20, 60, 120, 250)
WARMUP_START = 20100101
FIT_LO, FIT_HI = 20110101, 20231231
MU = 100.0
ALPHA = 0.01
ENTRY_THRESHOLD = 4.0
EXIT_THRESHOLD = -2.3


def float_ladders(gbbq_events_csv):
    """gbbq 事件表 -> 逐股流通股本阶梯 (LAD_D, LAD_V)。

    - cat 2/3（配股/送股）: songgu_qianzongguben = 除权后流通(万股)
    - cat 5/9/10/13/14（股本变动）: hongli_panqianliutong = 变动后流通(万股)
    返回 {code: [date...]}, {code: [万股...]}；使用时 ×1e4 换算为股。
    """
    df = pd.read_csv(gbbq_events_csv, dtype={'code': str})
    ladders = defaultdict(list)
    c23 = df[df['category'].isin([2, 3])]
    for code, dt, fl in zip(c23['code'], c23['datetime'], c23['songgu_qianzongguben']):
        if fl and fl > 0:
            ladders[code].append((int(dt), float(fl)))
    c5 = df[df['category'].isin([5, 9, 10, 13, 14])]
    for code, dt, fl in zip(c5['code'], c5['datetime'], c5['hongli_panqianliutong']):
        if fl and fl > 0:
            ladders[code].append((int(dt), float(fl)))
    lad_d, lad_v = {}, {}
    for code, evs in ladders.items():
        evs = sorted(set(evs))
        lad_d[code] = [e[0] for e in evs]
        lad_v[code] = [e[1] for e in evs]
    return lad_d, lad_v


def load_daily_records(day_files, code_of_file, warmup_start=WARMUP_START):
    """读全市场日线 -> (recs, code_of_sid)。

    recs 元素: (sid, date_int, amount, vol, close)；仅保留
    amount 有限且 close>0、date>=warmup 的记录。
    """
    recs = []
    code_of_sid = {}
    sid = 0
    for f in day_files:
        rec = read_day_file(f)
        code_of_sid[sid] = code_of_file(f)
        if len(rec):
            ok = np.isfinite(rec['amount']) & (rec['close'] > 0)
            for i in np.nonzero(ok)[0]:
                d = int(rec['date'][i])
                if d >= warmup_start:
                    recs.append((sid, d, float(rec['amount'][i]), float(rec['vol'][i]),
                                 rec['close'][i] / 100.0))
        sid += 1
    return recs, code_of_sid


def build_pools(recs, sid, code_of_sid, lad_d, lad_v, scales=SCALES):
    """逐日滚动成交记忆 EMA 池 -> (ALL_DATES, MEM, MV, A)。

    mem_t = mem_{t-1}*(1-1/N) + vol_t, 上限 min(mem, 流通股本)；
    MEM_N = Σ mem×close, MV = Σ 流通股本×close, A = Σ amount。
    """
    by_day = defaultdict(list)
    for r in recs:
        by_day[r[1]].append(r)
    all_dates = sorted(by_day)

    mems = {n: np.zeros(sid) for n in scales}
    MEM = {n: {} for n in scales}
    MV, A = {}, {}
    for d in all_dates:
        items = by_day[d]
        idxs = np.fromiter((it[0] for it in items), dtype=np.int64, count=len(items))
        vols = np.fromiter((it[3] for it in items), dtype=np.float64, count=len(items))
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
    return all_dates, MEM, MV, A


def factor_matrix(days_all, days_fit, MEM, MV, A, scales=SCALES):
    """log 因子 z-score 矩阵（全日域 + 官方拟合日域），z 统计量取拟合窗口。"""
    series = [(f'MEM{n}', MEM[n]) for n in scales] + [('MV', MV), ('A', A)]
    cols_all, cols_off = [], []
    row_of_all = {d: i for i, d in enumerate(days_all)}
    for name, series_d in series:
        arr_fit = np.array([np.log(max(series_d[d], 1e-9)) for d in days_fit])
        mu, sd = arr_fit.mean(), arr_fit.std()
        ca = (np.array([np.log(max(series_d[d], 1e-9)) for d in days_all]) - mu) / sd
        cols_all.append(ca)
        cols_off.append(ca[[row_of_all[d] for d in days_fit]])
    X_all = np.column_stack(cols_all + [np.ones(len(days_all))])
    X_off = np.column_stack(cols_off + [np.ones(len(days_fit))])
    return X_all, X_off


def solve_hybrid(X_off, logO_off, n, mu=MU, alpha=ALPHA, fit_lo=FIT_LO, fit_hi=FIT_HI,
                 days_off=None):
    """v5 混合目标闭式解: min ‖Xβ−logO‖² + μ·‖ΔXβ−ΔlogO‖² + α‖β‖²。"""
    trm = np.array([fit_lo <= d <= fit_hi for d in days_off])
    DXf = X_off[1:] - X_off[:-1]
    Dy = logO_off[1:] - logO_off[:-1]
    dtrm = trm[1:] & trm[:-1]
    H = X_off[trm].T @ X_off[trm] + mu * (DXf[dtrm].T @ DXf[dtrm]) + alpha * np.eye(n)
    g = X_off[trm].T @ logO_off[trm] + mu * (DXf[dtrm].T @ Dy[dtrm])
    return np.linalg.solve(H, g)


def ma10_series(vals):
    vals = np.asarray(vals, dtype=float)
    out = np.full(len(vals), np.nan)
    for i in range(9, len(vals)):
        out[i] = vals[i - 9:i + 1].mean()
    return out


def triggers(vals, dods, entry_threshold=ENTRY_THRESHOLD, exit_threshold=EXIT_THRESHOLD):
    """波段触发判定（生产 amv_filter 同口径）。

    入场: 单日 dod≥+4% 或 连续两日为正且累计≥+4%；
    出场: 单日 dod≤−2.3%（先查）或 收盘≤MA10；
    返回 (入场日idx集合, 出场日idx集合, MA10破位日idx集合, 多头日idx集合, MA10序列)。
    """
    ma10 = ma10_series(vals)
    vals = np.asarray(vals, dtype=float)
    dods = np.asarray(dods, dtype=float)
    entry, exitd, brk, bulls = set(), set(), set(), set()
    i = 0
    while i < len(vals):
        t1 = dods[i] >= entry_threshold
        t2 = (i > 0 and dods[i] > 0 and dods[i - 1] > 0
              and dods[i - 1] + dods[i] >= entry_threshold)
        if t1 or t2:
            entry.add(i)
            bulls.add(i)
            i += 1
            while i < len(vals):
                if dods[i] <= exit_threshold:
                    exitd.add(i)
                    break
                if not np.isnan(ma10[i]) and vals[i] <= ma10[i]:
                    brk.add(i)
                    break
                bulls.add(i)
                i += 1
        i += 1
    return entry, exitd, brk, bulls, ma10


def trigger_report(name, off_set, fit_set):
    """召回率（官方触发日中模型也触发）与假信号率（模型触发中官方未触发）。"""
    rec = len(off_set & fit_set) / max(len(off_set), 1)
    fas = len(fit_set - off_set) / max(len(fit_set), 1)
    print(f'    {name:14s} 官方{len(off_set):4d}  估算{len(fit_set):4d}  '
          f'召回 {rec*100:5.1f}%  假信号 {fas*100:5.1f}%')
    return rec, fas
