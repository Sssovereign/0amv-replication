# compass_0amv —— 指南针 Z_SK0AMV 真值提取器

> **实现唯一化（2026-10-22）**：解析实现唯一收敛到随仓保存的 canonical 制品
> `artifact/compass-0amv-parser-0.1.0/`（与 [Release compass-0amv-parser-0.1.0](https://github.com/Sssovereign/0amv-replication/releases/tag/compass-0amv-parser-0.1.0)
> 附件逐字节一致，zip SHA256 `325efda1…983f`，来源证明见制品内 `SOURCE.json`）。
> `extract_0amv.py` 现为启动器：只执行通过校验的随仓 ZIP 内代码，不加载本机同名包，
> 每次运行核对制品哈希。单独克隆即可使用，无需私有仓权限。

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

## Verified execution

The entry reads the pinned ZIP once, verifies SHA256, and executes parser bytes from that same buffer. Installed packages and the expanded inspection tree are never execution sources. A missing or modified ZIP fails before parsing. The expanded tree is retained only for source inspection and the artifact self-tests.
