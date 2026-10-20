"""波段触发判定的合成数据单测（入场/出场/MA10破位/两日累计）。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amv.core import triggers


def test_single_day_entry_then_exit():
    vals = [100.0] * 10
    dods = [0.0, 5.0, 1.0, 1.0, -3.0, 0, 0, 0, 0, 0]
    entry, exitd, brk, bulls, _ = triggers(vals, dods)
    assert entry == {1}
    assert exitd == {4}
    assert brk == set()
    assert bulls == {1, 2, 3}


def test_two_day_cumulative_entry():
    vals = [100.0] * 10
    dods = [0.0, 2.5, 2.0, 1.0, 0, 0, 0, 0, 0, 0]
    entry, _exitd, brk, bulls, _ = triggers(vals, dods)
    assert entry == {2}  # 2.5+2.0=4.5 且两日为正
    assert bulls == set(range(2, 9))
    # 第10天收盘恰好等于 MA10：定型口径 收盘≤MA10 即记破位
    assert brk == {9}


def test_ma10_break_exit():
    # 入场后横盘，第 10 天收盘跌破 MA10（dod 均未到 -2.3）
    vals = [100.0] * 9 + [90.0] + [90.5] * 6
    dods = [0.0] + [5.0] + [-1.0] * 14
    entry, exitd, brk, _bulls, ma10 = triggers(vals, dods)
    assert entry == {1}
    assert exitd == set()
    assert brk == {9}  # vals[9]=90 ≤ ma10(前10均值≈99)
    assert not np.isnan(ma10[9])


def test_exit_priority_over_ma10():
    """同日 dod≤-2.3 与破 MA10 并存时记为跌2.3出场，不记 MA10 破位。"""
    vals = [100.0] * 9 + [50.0] + [50.0] * 6
    dods = [0.0] + [5.0] + [-50.0] + [-1.0] * 13
    _entry, exitd, brk, _bulls, _ = triggers(vals, dods)
    assert exitd == {2}
    assert brk == set()
