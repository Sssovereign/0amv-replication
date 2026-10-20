"""gbbq 阶梯构建与 .day 文件读取的合成数据单测。"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amv.core import float_ladders
from amv.tdx import REC, a_stock_day_files, code_of_file, read_day_file


def test_float_ladders_from_events(tmp_path):
    csv = tmp_path / 'gbbq_events.csv'
    pd.DataFrame({
        'category': [2, 5, 1],  # cat 1 不参与
        'datetime': [20150601, 20200810, 20150601],
        'code': ['600519', '600519', '600519'],
        'songgu_qianzongguben': [12.56, 0.0, 9.9],   # cat5 不用 songgu
        'hongli_panqianliutong': [0.0, 12.56, 0.0],  # cat2 不用 hongli
    }).to_csv(csv, index=False)
    lad_d, lad_v = float_ladders(csv)
    assert lad_d['600519'] == [20150601, 20200810]
    assert lad_v['600519'] == [12.56, 12.56]


def test_read_day_file_and_filters(tmp_path):
    lday = tmp_path / 'vipdoc/sh/lday'
    lday.mkdir(parents=True)
    rec = np.array([(20240102, 1000, 1100, 990, 1050, 1.5e8, 100_000, 1000)],
                   dtype=REC).tobytes()
    (lday / 'sh600000.day').write_bytes(rec * 3)
    (lday / 'sh000001.day').write_bytes(rec)      # 上证指数 → 排除
    (lday / 'sh900001.day').write_bytes(rec)      # B股 → 排除

    files = list(a_stock_day_files(tmp_path))
    assert [f.name for f in files] == ['sh600000.day']
    assert code_of_file(files[0]) == '600000'

    arr = read_day_file(files[0])
    assert len(arr) == 3
    assert arr['date'][0] == 20240102
    assert abs(arr['amount'][0] - 1.5e8) < 1e6
