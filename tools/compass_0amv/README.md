# compass_0amv —— 指南针 Z_SK0AMV 真值提取器

从指南针本地缓存**只读**提取活跃市值 0AMV 的结构化日线历史，不修改指南针任何文件。

```bash
# 依赖：pandas（requirements.txt 已含）
python tools/compass_0amv/extract_0amv.py --compass-root "F:/Compass" --output-dir work/compass_out
```

- 输入：`<compass-root>/WavMain/ANALYSE/Data/ChinaStk/Z_SK/day.vdat`（权威历史）与
  `WavMain/Temp/Z_SK0AMV__.cde`（当日收盘缓存，用于补最新交易日）；
- 输出：`0amv_daily.csv`（date,open,high,low,close,volume,...,is_research_row,source）+
  `0amv_daily.pkl` + `manifest.json`（含来源文件 SHA256）；
- 交给 `scripts/parse_official.py --compass-dir <输出目录>` 即得回归用快照。

行为约定：

- `day.vdat` 被客户端占用或未更新到预期交易日时**明确报错**并保留已有数据（错误信息会分别提示"正常退出指南针释放文件"或"先更新行情"）；
- 缺少指南针依赖或路径时直接失败，不创建输出、不触碰已有数据。

版权提醒：提取结果为指南针商业数据，仅供本人复现研究使用，勿再分发。
