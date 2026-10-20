# 0AMV 活跃市值复现管线

用通达信本地公开行情数据，**纯离线**拟合指南针"活跃市值 0AMV"指标，精度达到波段择时可用（±4% 入场 / −2.3% 出场 / MA10 破位规则）。

> ⚠️ 研究复现项目，非投资建议；未接入任何实盘交易。

## 成果（v5 定型，全部可复现）

| 指标 | 数值 |
|------|------|
| 日涨幅 MAE（相对官方序列） | **0.278pp** |
| 日涨幅误差 <1pp 占比 | **96.5%** |
| 波段一致性 Jaccard | **0.910** |
| 入场触发召回 / 假信号（官方 131 次） | 80.9% / 21.5% |
| 出场触发召回 / 假信号（官方 60 次） | 76.7% / 25.8% |
| 水平相似度（拟合内 / 2024+ 样本外） | 97.2% / 98.0% |
| walk-forward 逐年样本外（10 折） | 90.5% ~ 99.1%，平均 96.34% |

附带结论：0AMV 公式不在指南针客户端（数值由服务端下发），复现只能走数据拟合；纯水平拟合（v3 基线）波段假信号率 31%，差分目标（v5）降至 21.5%。

## 快速开始

```bash
pip install -r requirements.txt

# 1. 准备数据（通达信 + 指南针，一次性和日常维护）
#    详见 docs/data.md —— 全部来自公开渠道，仓库不分发任何数据

# 2. 解析官方真值 CSV（指南针提取器输出或同格式 CSV）
python scripts/parse_official.py --compass-dir <提取器输出目录>

# 3. 解析股本变迁（通达信 gbbq，约 15 秒）
python scripts/parse_gbbq.py

# 4. v5 定型拟合 + 全历史估算 + 波段读数（约 60-90 秒）
python scripts/run_v5.py
```

`run_v5.py` 会打印定型指标一致性核对（应得到 0.278pp / 96.5% / Jaccard 0.910）与最新交易日波段判定读数，产物写入 `work/daily_v5_latest.csv`。每个交易日盘后更新通达信数据后重跑第 4 步即可。

## 仓库结构

```
amv/                  核心包：路径配置、TDX 读取、股本阶梯/成交记忆池/v5 回归/触发判定
scripts/
  parse_official.py   官方真值 CSV -> work/official_amv.csv (+OHLC 快照)
  parse_gbbq.py       通达信 gbbq -> work/gbbq_events.csv（pytdx 解密）
  run_v5.py           v5 定型日常驱动（拟合+评估+读数）
  fit_v3.py           v3 纯水平基线拟合（对照组）
  eval_v3.py          v3 波段判定评估（触发日对照/逐波段对齐/年度分布）
  combo_ohlc.py       OHLC 四价估算 + walk-forward + 缺失日预测
  viz_v3.py           v3 vs 官方对比可视化（离线 HTML）
tools/compass_0amv/   指南针 Z_SK0AMV 真值提取器（只读本地缓存）
tests/                合成数据单测（无需任何真实数据，CI 可跑）
docs/
  data.md             ★ 数据获取指南：公开渠道逐项说明
  replication.md      完整复现手册：步骤、预期数字、配方、已否决路线
```

路径默认 `TDX_ROOT=F:/tdx`、`COMPASS_ROOT=F:/Compass`，均可用环境变量覆盖（见 `amv/config.py`）。

## 数据与合规

本仓库**只含代码，不含任何数据**。所需数据全部从公开渠道获取：通达信免费行情终端（日线 + gbbq）、指南针客户端（官方真值，自行提取自用）。逐项说明与版权边界见 **[docs/data.md](docs/data.md)**；逐步复现与预期输出见 **[docs/replication.md](docs/replication.md)**。

## 致谢

- B 站 up 主 **光头老**（[BV1Rypn6GEuK](https://www.bilibili.com/video/BV1Rypn6GEuK)）——"成交记忆+市值+当天成交"的拟合思路与本管线独立收敛，互为验证；
- [指南针](https://www.compass.cn)——Z_SK0AMV 活跃市值指标为本项目的复现目标与真值来源；
- [通达信](https://www.tdx.com.cn)——本地行情与股本变迁数据；
- [pytdx](https://github.com/rainx/pytdx)——gbbq 文件解密。

## License

[MIT](LICENSE)
