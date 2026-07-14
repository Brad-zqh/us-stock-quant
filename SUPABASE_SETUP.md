# Supabase 配置（一次搞定：多用户登录 + 手机确认交易）

> Supabase = 免费云数据库，给两件事当后端：
> 1. **多用户登录**（每人自选股/邮箱/微信推送 + 你的管理员后台）
> 2. **手机确认交易**（电脑机器人把拟下单推到手机，你在手机点确认，电脑再下单）
>
> 全程约 10 分钟，只需点几下 + 复制粘贴。

---

## 第 1 步：建免费项目
1. 打开 https://supabase.com → 用 GitHub 登录 → **New project**。
2. 名字随便（如 `haoge-quant`），数据库密码自己设一个记住，区域选 `Singapore` 或 `Tokyo`（离你近）。
3. 等 1-2 分钟项目初始化完成。

## 第 2 步：建两张表（直接粘 SQL）
左侧 **SQL Editor** → New query → 把下面整段粘进去 → **Run**：

```sql
-- 用户表 (多用户登录)
create table if not exists users (
  email          text primary key,
  pw_hash        text,
  salt           text,
  watchlist_text text default '',
  sendkey        text default '',
  notify_email   text default '',
  is_admin       boolean default false,
  created_at     text,
  last_login     text
);

-- 待确认交易表 (手机确认)
create table if not exists orders (
  id          text primary key,
  batch_id    text,
  user_email  text,
  side        text,
  ticker      text,
  name        text,
  qty         double precision,
  price       double precision,
  amount      double precision,
  reason      text,
  env         text,
  status      text default 'pending',
  result      text default '',
  created_at  text,
  decided_at  text
);
create index if not exists orders_user_status on orders (user_email, status);

-- 关闭行级安全 (用 anon key 直连读写; 小规模私用够安全, 不公开表内容)
alter table users  disable row level security;
alter table orders disable row level security;
```

## 第 3 步：拿到 URL 和 Key
左侧 **Project Settings → API**：
- 复制 **Project URL**（形如 `https://xxxx.supabase.co`）
- 复制 **anon public** key（很长一串）

## 第 4 步：填到两个地方

### A. Streamlit 云端（网站 + 手机 App 用）
Streamlit Cloud → 你的 App → **Settings → Secrets**，粘贴：

```toml
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_KEY = "你的 anon public key"
BRAD_QUANT_CONFIRM_URL = "https://你的Streamlit域名.streamlit.app/?confirm=1"

# 多用户登录 (可选, 想开登录才填)
REQUIRE_LOGIN = "1"
INVITE_CODES  = "haoge2025,friend888"     # 逗号分隔, 发给朋友注册用
ADMIN_EMAILS  = "你的邮箱@xxx.com"          # 你自己, 免邀请码 + 管理员后台

# 大模型点评 (你之前已配的)
LLM_API_KEY  = "sk-..."
LLM_PROVIDER = "deepseek"
LLM_SENTIMENT = "1"                        # 可选: 开启后用大模型给新闻情绪打分, 叠加到"新闻情绪"因子(默认关)
```
保存后 App 会自动重启。

### B. 你的电脑（跑富途机器人用）
在 PowerShell 里设同样的（每次开新窗口要重设，或写进系统环境变量长期生效）：

```powershell
$env:SUPABASE_URL    = "https://xxxx.supabase.co"
$env:SUPABASE_KEY    = "你的 anon public key"
$env:FUTU_USER_EMAIL = "你的邮箱@xxx.com"   # 机器人代表哪个账户推单 (跟你登录网站的邮箱一致)
$env:BRAD_QUANT_CONFIRM_URL = "https://你的Streamlit域名.streamlit.app/?confirm=1"
```

也可以把上面配置写进本机 `config.json`（该文件已 gitignore，不会进仓库）：

```json
{
  "confirm_url": "https://你的Streamlit域名.streamlit.app/?confirm=1",
  "supabase": {
    "url": "https://xxxx.supabase.co",
    "key": "你的 anon public key"
  }
}
```

## 完成！怎么用

### 多用户登录
- 你用 `ADMIN_EMAILS` 里的邮箱去网站注册（免邀请码）→ 登录 → 「⚙️ 我的」能看到全部用户。
- 朋友用邀请码注册，各自设自选股/微信 SendKey，AI 交易员每天推到各自微信。
- 也能到 Supabase → **Table Editor → users** 直接看/改。

### 手机确认交易（半自动）
1. **电脑**（Windows，FutuOpenD 已开）：
   ```powershell
   python futu_live_guard.py --push          # 生成实盘控仓建议 + 推送到手机确认页
   ```
   它算出拟下单 → 推到云端信箱 → 邮件/微信带确认链接。
2. **手机**：打开 App →「📱 待确认」→ 看到刚推来的单 → 逐笔或「✅ 全部确认」。
3. **电脑**：常驻执行器看到你确认，自动通过 Futu OpenD 下单，手机端状态变「✅已执行」。

实盘执行器（只执行你已确认的 `live_guard` 订单）：

```powershell
$env:FUTU_ALLOW_LIVE = "1"
python futu_live_guard.py --executor-loop
```

如果 Windows 关机或 Futu OpenD 不在线，已确认订单会停在「已确认待执行」，等执行器上线后再处理。不要让多台电脑同时常驻执行；即使双开，代码也会先领取订单锁再下单，避免重复提交。

如果你之前已经在本机 `orders.json` 里生成过待确认单，配置好 Supabase 后可迁移一次：

```powershell
python scripts/migrate_local_orders_to_supabase.py
```

Windows 开机常驻执行器推荐安装计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_live_guard_executor_task.ps1
```

卸载：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_live_guard_executor_task.ps1
```

手动临时静默启动也可用：

```powershell
scripts\run_live_guard_executor_hidden.vbs
```

## 安全说明
- 表用 anon key + 关 RLS：适合你和朋友小规模私用，**不要把 URL/Key 贴到公开地方**。
- 密码是 pbkdf2 哈希存的，不存明文。SendKey/邮箱只在你私有的 Supabase 里。
- 手机确认是「你点了才下单」，电脑机器人不会自作主张下你没批准的单。
