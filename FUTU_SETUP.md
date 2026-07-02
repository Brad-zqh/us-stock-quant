# 富途美股 自动/半自动交易机器人 · 使用说明

> `futu_trader.py` 跑在**你自己的电脑上**（Windows 主力，Mac 也行），把量化信号
> 下到富途账户。**默认模拟盘（假钱真流程），安全第一。** 只支持美股。
> 全部为工具，不构成投资建议；实盘有风险，后果自负。

## 为什么必须在电脑上跑（手机说明）
富途下单要经过本地网关程序 **FutuOpenD**，它只有 Windows/Mac/Linux 版，**手机跑不了**。
所以架构是：

```
量化信号(futu_trader.py) → FutuOpenD(常开·登录你账号) → 富途服务器 → 下单
```

手机可当**遥控器**（收信号、点确认），执行始终在电脑上。手机确认功能见「第 2 步」。

---

## 第 1 步：今天就能跑（无需富途，先看信号）

```powershell
# 在项目目录，用你平时跑 app 的同一个 Python 环境
python futu_trader.py --dry-run
```

会打印「今天打算买/卖什么、几股、什么价、什么理由」，**不连富途、不下任何单**。
先用它确认策略信号是否合理。

自定义股票池（可选）：

```powershell
$env:FUTU_WATCHLIST = "AAPL,NVDA,MSFT,TSLA"   # 不设则用默认科技池
python futu_trader.py --dry-run
```

---

## 第 2 步：接富途模拟盘（假钱真流程）

### A. 一次性准备
1. **开通 OpenAPI**：富途牛牛 → 我的 → API → 开通 OpenAPI 权限。
2. **装并启动 FutuOpenD 网关**：到富途官网下载 FutuOpenD（Windows 版），
   运行后用你的富途账号登录，保持它开着（默认监听 `127.0.0.1:11111`）。
3. **装 SDK**（用跑本脚本的同一个 Python）：
   ```powershell
   pip install futu-api
   ```

### B. 跑模拟盘
```powershell
python futu_trader.py --paper            # 半自动：先列全部单，再逐笔问 y/n
python futu_trader.py --paper --yes      # 全自动：不逐笔问（仅模拟盘允许）
```
下单后到富途牛牛 App / 客户端就能看到模拟盘的订单与持仓。

> 模拟盘一般不需要交易密码；如提示需要解锁，设 `FUTU_TRADE_PWD` 环境变量。

---

## 第 3 步（可选）：真实盘（真金，谨慎）

真金下单**默认禁用**。确需开启时：
```powershell
$env:FUTU_ALLOW_LIVE = "1"       # 明确授权
$env:FUTU_TRADE_PWD  = "你的交易解锁密码"
python futu_trader.py --live     # 强制逐笔确认，无法全自动
```
建议先在模拟盘跑顺一两周再考虑。

---

## 决策逻辑（与 AI 交易员模拟账户完全一致）
复用 `paper.py` 的阈值，保证你在网页上看到的模拟账户和这里下单一致：

| 综合分 | 动作 |
|---|---|
| ≥ 58 | 建/加仓到「建议仓位%」（单票上限 25%） |
| 45 ~ 58 | 维持不动（持有） |
| < 45 | 清仓 |

- 只买整数股，按现金约束、分高者优先分配。
- 小于 $50 的碎单忽略。

## 环境变量速查
| 变量 | 作用 | 默认 |
|---|---|---|
| `FUTU_HOST` / `FUTU_PORT` | FutuOpenD 地址/端口 | `127.0.0.1` / `11111` |
| `FUTU_WATCHLIST` | 美股池，逗号分隔 | engine 默认池 |
| `FUTU_TRADE_PWD` | 交易解锁密码（实盘） | 空 |
| `FUTU_ALLOW_LIVE` | 设 `1` 才允许真实盘 | 未设=禁用 |
| `FUTU_START_CASH` | dry-run 假设起始资金 | 100000 |
| `FUTU_BUDGET` | **投入预算上限**（美元）。模拟盘固定发$100万改不了，用它让机器人只按你的真实资金建仓 | 未设=用账户全部资产 |
| `FUTU_MAX_POSITIONS` | **最多持有几只**（持仓集中度）。小资金建议 3~4，只买综合分最高的几只 | `0`=不限 |
| `FUTU_REBAL_BAND` | **再平衡死区**。目标与当前偏离小于 `总资产×此值` 就不调仓，减少无谓交易/手续费 | `0.03`（3%） |

### 💡 小资金推荐配置（真实约 $3,600）
```powershell
$env:FUTU_BUDGET        = "3600"   # 按真实资金建仓，不按模拟盘的100万
$env:FUTU_MAX_POSITIONS = "4"      # 最多持 4 只，避免碎单、手续费吃掉收益
$env:FUTU_REBAL_BAND    = "0.03"   # 偏离<3%不动，降低交易频率
python futu_trader.py --paper --yes
```
> **建议周频而非日频**：小资金每笔手续费占比高，一周调一次仓即可。不要设日频定时任务真金交易。

## 常见问题
- **`未安装 futu-api`**：`pip install futu-api`。
- **`连接 FutuOpenD 失败`**：FutuOpenD 没开或没登录；确认它在跑、端口 11111。
- **`未取到行情`**：yfinance 偶发限流，隔几分钟重试即可。
- **A 股能自动交易吗？** 不能，富途 OpenAPI 不支持 A 股程序化下单，本脚本只做美股。

## 手机端半自动确认（`--push`）
让电脑机器人把「待下单」推到手机、你在手机 App 点确认、电脑再执行：

1. 先按 **`SUPABASE_SETUP.md`** 配好 Supabase（手机和电脑共用同一个信箱）。
2. 电脑（Windows，FutuOpenD 已开）：
   ```powershell
   python futu_trader.py --paper --push       # 模拟盘 + 手机确认
   ```
   机器人算出拟下单 → 推到信箱 → 每 10 秒轮询等你确认（最长 30 分钟）。
3. 手机：打开 App →「📱 待确认」→ 逐笔或「✅ 全部确认」。
4. 电脑：看到确认后自动在富途下单，手机端状态变「✅已执行」。

> 真钱：把 `--paper` 换 `--live` 并设 `$env:FUTU_ALLOW_LIVE="1"`。手机确认即代替逐笔 y/n。
