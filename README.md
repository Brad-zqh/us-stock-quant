# 📈 美股量化选股看板 (US Stock Quant)

多因子综合打分 + 择时信号 + 基本面/分析师/资金流 + 新闻情绪 + ATR 风控 + 回测，
配 Streamlit 交互界面。为「富途牛牛手动下单」场景设计：给你每只票的
**信号、建议仓位、止损价、目标价**，并在你持仓之外扫描高科技股票池找机会。

> ⚠️ 仅作量化研究参考，**不构成投资建议**。数据非实时（yfinance 日线 / 约延迟15分钟）。

## 在线体验

部署到 Streamlit Cloud 后即有公开网址，可分享家人朋友（见底部「部署」）。
本地运行：

```bash
pip install -r requirements.txt
streamlit run app.py          # 浏览器打开 http://localhost:8501
```

## 三个页面

1. **🏆 自选股排名** — 你持仓的综合分 / 信号 / 风控方案一览，颜色热力图
2. **🔍 个股详情** — K线+均线+MACD+RSI、因子雷达、基本面/分析师/资金流明细、新闻情绪、回测
3. **🔭 高科技选股池** — 扫描 ~45 只高科技龙头，推荐你持仓之外的买入候选

## 9 因子综合打分（0~100）

| 因子 | 权重 | 看什么 | 模块 |
|------|------|--------|------|
| 基本面 | 17% | PEG、营收增速、毛利率、ROE、净利率 | factors_plus.py |
| 趋势 | 15% | 价格 vs SMA50/200、金叉死叉 | engine.py |
| 分析师 | 13% | 华尔街评级均值、目标价上行空间、覆盖度 | factors_plus.py |
| 动量 | 12% | MACD、6月/1月动量 | engine.py |
| 资金流 | 10% | OBV 能量潮、Chaikin CMF、放量突破52周高 | factors_plus.py |
| 风险 | 10% | 年化波动率 | engine.py |
| 相对大盘 | 8% | 近63日 vs QQQ | engine.py |
| 新闻情绪 | 8% | 个股新闻 VADER+金融词典情绪 | news.py |
| 强弱 | 7% | RSI、布林 %B | engine.py |

**信号档位**：≥70 强烈买入 · 58~70 买入 · 45~58 持有 · 35~45 减仓 · <35 卖出。
**风控**：止损 = 现价 − 2.5×ATR，目标 = +4×ATR；仓位按分数与波动率调整，单票上限 25%。
（关闭基本面/新闻因子时，权重自动归一化到剩余技术因子。）

## 📤 推送信号（邮件 / 微信）

复制 `config.example.json` 为 `config.json` 填凭证（此文件已被 .gitignore，不会上传）：
- **邮件**：用邮箱「授权码」（非登录密码），网页版邮箱设置里开 SMTP 生成
- **微信**：用 [Server酱](https://sct.ftqq.com)，微信扫码拿 SendKey

界面左侧「📤 推送信号」一键发送；或命令行 `python3 -c "import notify; print(notify.run_and_push())"`。

## 部署到 Streamlit Cloud（拿到可分享网址）

1. 本仓库已推送到 GitHub（公开）。
2. 打开 [share.streamlit.io](https://share.streamlit.io) → 用 GitHub 登录。
3. New app → 选本仓库 → Main file 填 `app.py` → Deploy。
4. 几分钟后得到 `https://<名字>.streamlit.app` 永久网址，发给家人朋友即可。

> 注意：**不要**在 Streamlit Cloud 上配置真实邮箱/微信密码到公开仓库；
> 如需云端推送，用 Streamlit 的 Secrets 功能存凭证。

## 文件结构

| 文件 | 作用 |
|------|------|
| `engine.py` | 数据获取、技术指标、综合打分、风控、回测 |
| `factors_plus.py` | 基本面 / 分析师 / 资金流因子 |
| `news.py` | 新闻抓取 + 金融情绪分析 |
| `universe.py` | 高科技选股池 + 扫描排名 |
| `notify.py` | 邮件 / 微信推送 |
| `app.py` | Streamlit 交互界面 |

## 说明

- **数据非实时**：日线收盘 / 约延迟15分钟，适合中长线择时；盘内秒级看富途。
- **SPCX (SpaceX)** 已上市但样本不足时会标「数据不足·仅供观察」。
- 数据缓存 15~30 分钟，点「🔄 刷新分析」强制更新。
