# AGENTS.md — 皓量化 (Brad Quant) 项目交接说明

> 给 AI 编码助手（Codex 等）的项目上手指南。功能/因子说明见 `README.md`，
> 本文件专讲**架构、运维、约定、以及容易踩的坑**。仅量化研究，不构成投资建议。

## 一句话架构

Python + Streamlit 的多因子选股看板。核心分析在纯 Python 模块，UI 在 `app.py`。
Web 端部署在 Streamlit Cloud；手机/桌面端用一层「外壳」加载云端网址（不重写业务逻辑）。

- **仓库**：`Brad-zqh/us-stock-quant`（分支 `main`，推 `main` 即触发 Web 重部署）
- **Web 部署**：Streamlit Cloud（自动跟随 `main`）。改完若没生效 → Manage app → Reboot
- **桌面端**：Tauri（Win/Mac），GitHub Actions 打 `v*` tag 构建发布 + 应用内自动更新
- **移动端**：Capacitor（Android/iOS），`server.url` 直接加载云端 Streamlit
- **实盘/模拟对接**：富途 OpenD 网关（本地 `127.0.0.1:11111`）

## 目录/模块速查

| 模块 | 作用 |
|------|------|
| `engine.py` | 数据获取、技术指标、综合打分、风控、回测。**`DEFAULT_WATCHLIST` / `A_SHARE_WATCHLIST` 是默认选股池** |
| `factors_plus.py` | 基本面 / 分析师 / 盈利质量 / 资金流 / 筹码因子 |
| `sector_factor.py` | 板块热度因子 |
| `news.py` / `cn_news.py` / `futu_news.py` | 美股/A股/富途 新闻情绪 |
| `quotes.py` | **行情数据层**：优先富途 OpenD，失败自动回退 yfinance。对上层透明 |
| `resolve.py` | 美股/A股 代码/名称 搜索匹配 |
| `explain.py` | 「策略解读」白话归因 |
| `llm.py` | 大模型点评/新闻速览/翻译（DeepSeek 等，凭据见下） |
| `favorites.py` | 收藏夹（localStorage 本机持久化） |
| `app.py` | Streamlit 全部 UI（个股详情/自选股/模拟盘/AI交易员/选股池…） |
| `futu_trader.py` | 交易机器人：打分→生成订单→下单（dry/paper/live） |
| `futu_loop.py` | 常驻循环，按间隔调用 trader（本地定时自动交易） |
| `futu_status.py` | 富途账户只读速览（模拟盘/实盘资金持仓） |
| `paper.py` / `orderstore.py` / `userstore.py` | 本地模拟盘账户 / 订单 / 用户存储 |
| `app-shell/` | 外壳：`web/`(PWA) `capacitor/`(移动) `tauri/`(桌面) |

## 本地开发环境（重要）

- **本地跑的是嵌入式 Python**：`%LOCALAPPDATA%\StockQuantPy\python.exe`（3.11.x）。
  不是系统 PATH 里的 python。跑脚本用它的绝对路径。
- **中文输出必设**：`PYTHONIOENCODING=utf-8`，否则控制台/日志中文乱码。
- 常用本地命令：
  ```powershell
  $py="$env:LOCALAPPDATA\StockQuantPy\python.exe"; $env:PYTHONIOENCODING="utf-8"
  & $py -m streamlit run app.py         # 本地起 UI
  & $py futu_status.py --paper          # 看富途模拟盘账户
  & $py engine.py                       # 打印默认池打分表
  ```
- 改动验证优先：`ast.parse` 语法检查 + `import` 冒烟；跑打分时优先富途源，
  yfinance 连续多票易被瞬时限流（报 "possibly delisted"，非真退市）。

## 富途 OpenD 网关

- 交易/富途行情都要它在线。GUI 版：`%APPDATA%\Futu_OpenD\Futu_OpenD.exe`，端口 11111。
- 已设开机自启（启动文件夹快捷方式）。判断在线：11111 端口是否 Listen。
- `quotes.py` 探测不到网关会**静默回退 yfinance**，云端（无网关）本就走 yfinance。

## 两个「模拟盘」别混淆

1. **本地模拟盘**：`state/paper_account.json`，由 `futu_loop.py`/`paper.py` 驱动，
   **不经过富途网关**。这是自动交易真正在跑的账户。
2. **富途网关模拟盘**：富途官方 SIMULATE 账户，`futu_status.py --paper` 查询，需网关在线。

## 自动交易（本地常驻）

- `futu_loop.py` 常驻，`mode=paper`，每 900s 检查、每交易日按综合分调仓。
- 选股池 = `engine.DEFAULT_WATCHLIST`（实时读取，改池子**无需重启** loop，
  下个交易日开盘即用新池）。也可用环境变量 `FUTU_WATCHLIST="AAPL,NVDA,..."` 覆盖。
- 计划任务名目前是「皓哥量化-模拟盘自动交易」（旧名，待统一为「皓量化」）。
- 选股逻辑：全池打分，**综合分 ≥ 58 建/加仓**，分高权重大；单票权重有上限、带 ATR 止损。

## 桌面端 / 自动更新（Tauri）

- `app-shell/tauri/`。`productName="皓量化"`（中文），`mainBinaryName="BradQuant"`。
- 发版：打 `v*` tag → `.github/workflows/desktop.yml` 构建 Win/Mac + 签名 + 发布 Release。
- **已知坑**：中文 productName 导致 tauri-action 无法自动生成 `latest.json`（updater 端点），
  故 workflow 末尾有独立 `updater-json` job：用 `app-shell/tauri/scripts/gen_latest_json.py`
  从 Release 的 `.sig` 资产手动组装并上传 `latest.json`。改发版流程时勿破坏这一步。
- **签名私钥备份**：`%LOCALAPPDATA%\StockQuantPy\updater-key\`（私钥 + 密码）。
  丢了就无法再发被旧版验证的更新——务必让用户存进密码管理器。
- GitHub Secrets：`TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`。

## 移动端（Capacitor）

- `app-shell/capacitor/capacitor.config.json` 用 `server.url` 直接加载云端 Streamlit
  （不再用 iframe 套壳，安卓 WebView 更稳）。`allowNavigation` 放行 `*.streamlit.app`。
- 安卓构建：`.github/workflows/android.yml`（可 workflow_dispatch 触发，APK 传到 Release）。

## 密钥 / 配置（都不进仓库）

- `config.json`（已 gitignore）：邮件授权码 / 微信 Server酱 SendKey / LLM key 等。
  模板见 `config.example.json`。
- 云端凭据走 Streamlit **Secrets**（`LLM_API_KEY` / `LLM_PROVIDER` 等），不要写进公开仓库。
- **切勿把任何密钥提交进 git 或写进本文件**。历史上 DeepSeek key 曾明文出现过，建议已吊销。

## 提交约定

- 提交信息用中文；**必带**结尾 trailer：
  `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>`
- 含中文的 commit：Windows 上先把信息写文件再
  `git -c core.autocrlf=false commit -F <file>`（避免编码乱码）。
- `git push` 在 PowerShell 里常把进度写 stderr 导致 exit=1，但看到 `old..new` 即为成功。

## 常见坑一览

- **PowerShell 内联中文会乱码**：写含中文的文件用 `[System.IO.File]::WriteAllText(path, text,
  (New-Object System.Text.UTF8Encoding($false)))`，或从文件读，别内联。
- **yfinance 批量限流**：连续多票请求报 "possibly delisted; no price data" 多为瞬时限流，
  换富途源或逐票重试，不是真退市。
- **新股样本不足**：上市 < 60 交易日的票（如 SPCX）均线/MACD 为 NaN，`engine` 标
  `insufficient`、信号「观察(次新股)」，UI 有「数据不足」提示——属正常，非 bug。
- **改名遗留**：仍可能有「皓哥量化」旧名散落在计划任务/脚本标题里，统一目标是「皓量化」。

## 快速验证清单（改完代码跑一遍）

1. `ast.parse` + `import` 冒烟
2. 涉及打分：`& $py engine.py` 看默认池是否正常出表（优先富途源避免限流）
3. 涉及 UI：本地 `streamlit run app.py` 打开对应页
4. 提交推送 `main` → 若 Web 未变，Streamlit Manage app → Reboot
