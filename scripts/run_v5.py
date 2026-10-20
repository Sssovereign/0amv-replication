#!/usr/bin/env python3
"""v5 定型日常驱动：一条命令完成 池重建 -> v5 回归 -> 全历史估算 -> 波段读数。

用法: PYTHONUTF8=1 python scripts/run_v5.py
前置: scripts/parse_official.py 与 scripts/parse_gbbq.py 已生成 work/ 下的
      official_amv.csv 与 gbbq_events.csv；TDX 行情已下载到最新交易日。
产物: work/daily_v5_latest.csv (date,close,dod,ma10,in_bull,is_predicted)
"""
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from amv import config, core, tdx

WORK = Path(config.WORK)


def main():
    t0 = time.time()
    lad_d, lad_v = core.float_ladders(WORK / 'gbbq_events.csv')
    recs, code_of_sid = core.load_daily_records(
        tdx.a_stock_day_files(config.TDX_ROOT), tdx.code_of_file)
    sid = len(code_of_sid)
    print(f'loaded {sid} stocks {time.time()-t0:.0f}s')
    all_dates, MEM, MV, A = core.build_pools(recs, sid, code_of_sid, lad_d, lad_v)
    print(f'pools {len(all_dates)} days {time.time()-t0:.0f}s')

    official = {}
    with open(WORK / 'official_amv.csv', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            official[row['date']] = float(row['close'])
    days_all = [d for d in all_dates if d >= core.FIT_LO]
    days_off = [d for d in days_all if str(d) in official]
    days_fit = [d for d in days_off if core.FIT_LO <= d <= core.FIT_HI]
    last_off = max(int(d) for d in official)
    missing = [d for d in days_all if d > last_off]
    logO_fit = np.log(np.array([official[str(d)] for d in days_fit]))

    X_all, X_off = core.factor_matrix(days_all, days_fit, MEM, MV, A)
    beta = core.solve_hybrid(X_off, logO_fit, X_all.shape[1], days_off=days_fit)

    row_of = {d: i for i, d in enumerate(days_all)}
    pred = np.exp(X_all @ beta)
    dod = np.concatenate([[0.0], (pred[1:] / pred[:-1] - 1) * 100])

    # 定型指标一致性核对（官方日域）
    p_off = np.array([pred[row_of[d]] for d in days_off])
    o_off = np.array([official[str(d)] for d in days_off])
    dod_f = np.concatenate([[0.0], (p_off[1:] / p_off[:-1] - 1) * 100])
    dod_o = np.concatenate([[0.0], (o_off[1:] / o_off[:-1] - 1) * 100])
    err = np.abs(dod_f[1:] - dod_o[1:])
    outm = np.array([d >= 20240101 for d in days_off])
    print(f'\n[一致性核对] dodMAE 全期{err.mean():.3f}pp 样本外{err[outm[1:]].mean():.3f}pp  '
          f'<1pp {np.mean(err < 1)*100:.1f}%  (定型: 0.278pp / 96.5%)')

    entry, exitd, brk, bulls, ma10 = core.triggers(pred, dod)
    bo, eo, bro, bull_o, _ = core.triggers(o_off, dod_o)
    jac = len(bull_o & bulls) / len(bull_o | bulls)
    core.trigger_report('入场触发', bo, entry)
    core.trigger_report('出场触发(跌2.3)', eo, exitd)
    core.trigger_report('MA10破位', bro, brk)
    print(f'    波段Jaccard {jac:.4f}  (定型: 入场81.7/20.7 出场78.3/24.2 Jaccard 0.913)')

    # 日常读数
    last = days_all[-1]
    li = row_of[last]
    in_bull = li in bulls
    if in_bull:
        start_i = li
        while start_i - 1 in bulls:
            start_i -= 1
        band_start = start_i
    print(f'\n{"="*58}\n日常读数（v5 估算，官方最新 {last_off}，缺失日 {missing or "无"}）\n{"="*58}')
    print(f'最新交易日 {last}: 估算收盘 {pred[li]:,.1f}  dod {dod[li]:+.2f}%  MA10 {ma10[li]:,.1f}')
    if in_bull:
        print(f'波段状态: 多头（{days_all[band_start]} 入场至今 {li-band_start+1} 个交易日）')
        print(f'  出场观察位: 单日 dod ≤ {core.EXIT_THRESHOLD}% → 收盘跌破 '
              f'{pred[li]*(1+core.EXIT_THRESHOLD/100):,.0f}')
        print(f'              破 MA10 → 收盘跌破 {ma10[li]:,.0f}（距 '
              f'{(ma10[li]/pred[li]-1)*100:+.1f}%）')
    else:
        print('波段状态: 空仓')
        print(f'  入场观察位: 单日 dod ≥ +{core.ENTRY_THRESHOLD:.0f}% → 收盘涨至 '
              f'{pred[li]*(1+core.ENTRY_THRESHOLD/100):,.0f}')
        if dod[li] > 0:
            print(f'  两日累计: 今日 {dod[li]:+.2f}% 为正，明日 ≥ '
                  f'{core.ENTRY_THRESHOLD-dod[li]:.2f}% 即触发')
        else:
            print(f'  两日累计: 今日 dod {dod[li]:+.2f}% 非正，明日不满足两日连续为正')

    if missing:
        print('\n缺失日预测（待官方 CSV 更新后核对）:')
        for d in missing:
            i = row_of[d]
            print(f'  {d}: 收盘 {pred[i]:,.1f}  dod {dod[i]:+.2f}%  '
                  f'MA10 {ma10[i]:,.1f}  {"多头" if i in bulls else "空仓"}')

    print('\n近12个交易日:')
    print(f'{"date":10s} {"close":>10s} {"dod%":>7s} {"MA10":>10s}  状态')
    for d in days_all[-12:]:
        i = row_of[d]
        tag = '估算' if str(d) not in official else '官方'
        print(f'{d:<10d} {pred[i]:>10,.1f} {dod[i]:>+7.2f} {ma10[i]:>10,.1f}  '
              f'{"多头" if i in bulls else "空仓"} [{tag}]')

    with open(WORK / 'daily_v5_latest.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'close', 'dod', 'ma10', 'in_bull', 'is_predicted'])
        for d in days_all:
            i = row_of[d]
            w.writerow([d, f'{pred[i]:.2f}', f'{dod[i]:.4f}', f'{ma10[i]:.2f}',
                        1 if i in bulls else 0, 0 if str(d) in official else 1])
    print(f'\nwrote {WORK / "daily_v5_latest.csv"} ({time.time()-t0:.0f}s)')


if __name__ == '__main__':
    main()
