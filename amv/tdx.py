"""通达信本地数据读取：.day 二进制日线与 A 股文件过滤。

.day 每记录 32 字节: date(i32 YYYYMMDD), OHLC(i32, 价格×100),
amount(f32 元), vol(i32), prev_close(i32)。
"""
from collections.abc import Iterator
from pathlib import Path

import numpy as np

REC = np.dtype([('date', '<i4'), ('open', '<i4'), ('high', '<i4'), ('low', '<i4'),
                ('close', '<i4'), ('amount', '<f4'), ('vol', '<i4'), ('prev', '<i4')])

SH_A_PREFIXES = ('600', '601', '603', '605', '688', '689')
SZ_A_PREFIXES = ('000', '001', '002', '003', '300', '301')


def a_stock_day_files(tdx_root) -> Iterator[Path]:
    """全市场 A 股日线文件（沪深主板/创业板/科创板，排除指数/B股/基金/北交所）。"""
    root = Path(tdx_root)
    for f in sorted((root / 'vipdoc/sh/lday').glob('*.day')):
        if f.name[2:5] in SH_A_PREFIXES:
            yield f
    for f in sorted((root / 'vipdoc/sz/lday').glob('*.day')):
        if f.name[2:5] in SZ_A_PREFIXES:
            yield f


def code_of_file(path) -> str:
    """sh600519.day -> 600519"""
    return Path(path).name[2:8]


def read_day_file(path) -> np.ndarray:
    """读取单只股票全部日线记录（结构化数组，可能有无效尾部需调用方过滤）。"""
    data = Path(path).read_bytes()
    cnt = len(data) // 32
    if cnt == 0:
        return np.empty(0, dtype=REC)
    return np.frombuffer(data[:cnt * 32], dtype=REC)
