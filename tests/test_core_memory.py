"""成交记忆池构建的合成数据单测。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amv.core import build_pools


def test_ema_recursion_and_cap():
    """mem_t = mem_{t-1}*(1-1/N)+vol_t, 上限=流通股本；MEM=Σmem×close。"""
    # 2 只股票：s0 有阶梯(100万股)，s1 无阶梯(不设上限、不入 MV)
    recs = [
        (0, 20240101, 4.0e8, 400_000, 10.0),   # s0 vol 40万股, close 10
        (1, 20240101, 1.0e8, 100_000, 5.0),
        (0, 20240102, 5.0e8, 900_000, 11.0),   # s0 vol 90万股 → 触发上限 100万
        (1, 20240102, 1.0e8, 100_000, 5.0),
    ]
    code_of_sid = {0: '600001', 1: '000001'}
    lad_d = {'600001': [20240101]}
    lad_v = {'600001': [100.0]}  # 万股 → 1e6 股

    dates, MEM, MV, A = build_pools(recs, 2, code_of_sid, lad_d, lad_v)
    assert dates == [20240101, 20240102]

    # N=5, 第1天: s0 mem=min(40万,100万)=40万; s1 无阶梯不加 Caps
    assert MEM[5][20240101] == 400_000 * 10.0 + 100_000 * 5.0
    # 第2天: s0 mem = 40万*0.8 + 90万 = 122万 → cap 100万; s1 = 10万*0.8+10万=18万
    assert MEM[5][20240102] == 1_000_000 * 11.0 + 180_000 * 5.0

    # MV: s0 有流通股本 100万股×close；s1 无阶梯不入 MV
    assert MV[20240101] == 1_000_000 * 10.0
    assert MV[20240102] == 1_000_000 * 11.0
    # A: 成交额直接求和
    assert A[20240101] == 5.0e8


def test_ladder_step_changes_over_time():
    """阶梯按日期取 ≤d 的最近一次变动。"""
    recs = [
        (0, 20240101, 1.0e8, 2_000_000, 10.0),
        (0, 20240102, 1.0e8, 2_000_000, 10.0),
    ]
    lad_d = {'600001': [20231201, 20240102]}
    lad_v = {'600001': [100.0, 200.0]}  # 1月2日起流通翻倍至 200万股
    dates, _MEM, MV, _A = build_pools(recs, 1, {0: '600001'}, lad_d, lad_v)
    assert dates == [20240101, 20240102]
    assert MV[20240101] == 1_000_000 * 10.0
    assert MV[20240102] == 2_000_000 * 10.0


def test_pool_values_are_floats():
    recs = [(0, 20240101, 1.0, 1.0, 1.0)]
    dates, MEM, MV, A = build_pools(recs, 1, {0: '600001'}, {}, {})
    assert dates == [20240101]
    assert isinstance(MEM[5][20240101], float)
    assert isinstance(MV[20240101], float)
    assert isinstance(A[20240101], float)
    assert MV[20240101] == 0.0  # 无阶梯 → nansum 全 NaN = 0
    assert not np.isnan(MEM[5][20240101])
