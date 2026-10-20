"""官方 CSV 两种格式解析与快照写入的单测。"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from amv.official import fill_dod, parse_rows, write_snapshots

AMP_HEADER = ['date', 'time_text', 'amplitude_percent', 'raw_ocr_text', 'screenshot']


def _amp_row(d, close, dod):
    raw = f'开:{close} 高:{close} 低:{close} 收:{close} 幅:{dod}%'
    return {'date': d, 'time_text': d.replace('-', ''), 'amplitude_percent': dod,
            'raw_ocr_text': raw, 'screenshot': ''}


def test_parse_amplitude_format(tmp_path):
    src = tmp_path / 'amv.csv'
    with open(src, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=AMP_HEADER)
        w.writeheader()
        w.writerow(_amp_row('2026-10-14', 145788.8, '-3.09'))
        w.writerow(_amp_row('2026-10-15', 142216.5, '-2.45'))
    rows = parse_rows(src)
    assert [r[0] for r in rows] == ['20261014', '20261015']
    assert rows[0][4] == 145788.8
    assert rows[0][5] == -3.09


def test_parse_structured_and_fill_dod(tmp_path):
    src = tmp_path / '0amv_daily.csv'
    with open(src, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['date', 'open', 'high', 'low', 'close',
                                          'is_research_row', 'source'])
        w.writeheader()
        w.writerow({'date': '2026-10-14', 'open': '1', 'high': '2', 'low': '0.5',
                    'close': '1.5', 'is_research_row': 'True', 'source': 'day.vdat'})
        w.writerow({'date': '2026-10-15', 'open': '', 'high': '', 'low': '',
                    'close': '1.6', 'is_research_row': 'True', 'source': 'day.vdat'})
        w.writerow({'date': '2026-10-13', 'open': '1', 'high': '1', 'low': '1',
                    'close': '1', 'is_research_row': 'False', 'source': 'day.vdat'})
    rows = parse_rows(src)
    assert len(rows) == 2  # is_research_row=False 被排除
    rows = fill_dod(rows)
    assert rows[1][5] is not None and abs(rows[1][5] - (1.6 / 1.5 - 1) * 100) < 1e-9

    out = tmp_path / 'work'
    assert write_snapshots(rows, out) == 2
    lines = (out / 'official_amv.csv').read_text(encoding='utf-8').splitlines()
    assert lines[0] == 'date,close,dod'
    assert lines[2].startswith('20261015,1.6,')
    ohlc = (out / 'official_amv_ohlc.csv').read_text(encoding='utf-8').splitlines()
    assert ohlc[2] == '20261015,,,,1.6'


def test_duplicate_date_rejected(tmp_path):
    src = tmp_path / 'bad.csv'
    with open(src, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=AMP_HEADER)
        w.writeheader()
        w.writerow(_amp_row('2026-10-14', 100.0, '1'))
        w.writerow(_amp_row('2026-10-14', 101.0, '1'))
    try:
        parse_rows(src)
        raise AssertionError('应拒绝重复日期')
    except ValueError as e:
        assert '重复或无序' in str(e)
