"""官方 0AMV 真值序列解析。

支持两种输入格式（自动按表头识别）:
- compass 结构化: tools/compass_0amv 提取的 0amv_daily.csv
  (date,open,high,low,close,...,change_pct,is_weekend,is_research_row,source)
- amplitude 运行格式: date,time_text,amplitude_percent,raw_ocr_text,screenshot

输出快照:
- official_amv.csv      (date, close, dod)
- official_amv_ohlc.csv (date, open, high, low, close)
"""
import csv
import re

_RE_O = re.compile(r'开:+\s*([\d.]+)')
_RE_H = re.compile(r'高:+\s*([\d.]+)')
_RE_L = re.compile(r'低:+\s*([\d.]+)')
_RE_C = re.compile(r'收:+\s*([\d.]+)')


def _is_amplitude_format(header):
    return 'raw_ocr_text' in header


def parse_rows(src_path):
    """-> rows: [(date8, open|None, high|None, low|None, close, dod|None), ...] 按日期升序。"""
    with open(src_path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        header = set(reader.fieldnames or [])
        if _is_amplitude_format(header):
            rows = _parse_amplitude(reader)
        else:
            rows = _parse_structured(reader)
    rows.sort(key=lambda r: r[0])
    _validate_ascending(rows)
    return rows


def _parse_amplitude(reader):
    out = []
    for row in reader:
        d = (row.get('date') or '').replace('-', '')
        if not d:
            continue
        raw = row.get('raw_ocr_text') or ''
        mc = _RE_C.search(raw)
        if not mc:
            continue
        close = float(mc.group(1))
        mo, mh, ml = _RE_O.search(raw), _RE_H.search(raw), _RE_L.search(raw)
        amp = (row.get('amplitude_percent') or '').strip().replace('%', '').replace('+', '')
        dod = float(amp) if amp else None
        out.append((d,
                    float(mo.group(1)) if mo else None,
                    float(mh.group(1)) if mh else None,
                    float(ml.group(1)) if ml else None,
                    close, dod))
    return out


def _parse_structured(reader):
    out = []
    for row in reader:
        if row.get('is_research_row') != 'True':
            continue
        d = (row.get('date') or '').replace('-', '')
        try:
            close = float(row['close'])
            o = float(row['open']) if row.get('open') else None
            h = float(row['high']) if row.get('high') else None
            low = float(row['low']) if row.get('low') else None
        except (KeyError, TypeError, ValueError):
            continue
        out.append((d, o, h, low, close, None))
    return out


def _validate_ascending(rows):
    prev = None
    for r in rows:
        if prev is not None and r[0] <= prev:
            raise ValueError(f'日期重复或无序: {r[0]}')
        prev = r[0]


def fill_dod(rows):
    """缺 dod 的行用相邻收盘补算（首行无法补则保持 None）。"""
    out = []
    prev_close = None
    for d, o, h, low, close, dod in rows:
        if dod is None and prev_close:
            dod = (close / prev_close - 1) * 100
        out.append((d, o, h, low, close, dod))
        prev_close = close
    return out


def write_snapshots(rows, work_dir):
    """写 official_amv.csv 与 official_amv_ohlc.csv；返回写入天数。"""
    work_dir.mkdir(parents=True, exist_ok=True)
    with open(work_dir / 'official_amv.csv', 'w', encoding='utf-8') as f:
        f.write('date,close,dod\n')
        for d, _o, _h, _low, close, dod in rows:
            f.write(f'{d},{close},{"" if dod is None else dod}\n')
    with open(work_dir / 'official_amv_ohlc.csv', 'w', encoding='utf-8') as f:
        f.write('date,open,high,low,close\n')
        for d, o, h, low, close, _dod in rows:
            f.write(','.join('' if v is None else f'{v}' for v in (d, o, h, low, close)) + '\n')
    return len(rows)
