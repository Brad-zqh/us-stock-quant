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

## 常见问题
- **`未安装 futu-api`**：`pip install futu-api`。
- **`连接 FutuOpenD 失败`**：FutuOpenD 没开或没登录；确认它在跑、端口 11111。
- **`未取到行情`**：yfinance 偶发限流，隔几分钟重试即可。
- **A 股能自动交易吗？** 不能，富途 OpenAPI 不支持 A 股程序化下单，本脚本只做美股。

## 手机端半自动确认（规划中，第 2 阶段）
让电脑机器人把「待下单」推到手机、你在手机网页点确认、电脑再执行——
这需要配好 Supabase 当「信箱」后再接，届时会单独提供。
