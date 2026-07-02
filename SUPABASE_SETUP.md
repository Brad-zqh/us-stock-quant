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
  qty         integer,
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

# 多用户登录 (可选, 想开登录才填)
REQUIRE_LOGIN = "1"
INVITE_CODES  = "haoge2025,friend888"     # 逗号分隔, 发给朋友注册用
ADMIN_EMAILS  = "你的邮箱@xxx.com"          # 你自己, 免邀请码 + 管理员后台

# 大模型点评 (你之前已配的)
LLM_API_KEY  = "sk-..."
LLM_PROVIDER = "deepseek"
```
保存后 App 会自动重启。

### B. 你的电脑（跑富途机器人用）
在 PowerShell 里设同样的（每次开新窗口要重设，或写进系统环境变量长期生效）：

```powershell
$env:SUPABASE_URL    = "https://xxxx.supabase.co"
$env:SUPABASE_KEY    = "你的 anon public key"
$env:FUTU_USER_EMAIL = "你的邮箱@xxx.com"   # 机器人代表哪个账户推单 (跟你登录网站的邮箱一致)
```

## 完成！怎么用

### 多用户登录
- 你用 `ADMIN_EMAILS` 里的邮箱去网站注册（免邀请码）→ 登录 → 「⚙️ 我的」能看到全部用户。
- 朋友用邀请码注册，各自设自选股/微信 SendKey，AI 交易员每天推到各自微信。
- 也能到 Supabase → **Table Editor → users** 直接看/改。

### 手机确认交易（半自动）
1. **电脑**（Windows，FutuOpenD 已开）：
   ```powershell
   python futu_trader.py --paper --push      # 模拟盘 + 手机确认
   ```
   它算出拟下单 → 推到信箱 → 开始等你确认（每 10 秒查一次，最长 30 分钟）。
2. **手机**：打开 App →「📱 待确认」→ 看到刚推来的单 → 逐笔或「✅ 全部确认」。
3. **电脑**：看到你确认，自动在富途模拟盘下单，手机端状态变「✅已执行」。

> 想真钱：把 `--paper` 换 `--live`，并设 `$env:FUTU_ALLOW_LIVE="1"`。务必先模拟盘跑顺！

## 安全说明
- 表用 anon key + 关 RLS：适合你和朋友小规模私用，**不要把 URL/Key 贴到公开地方**。
- 密码是 pbkdf2 哈希存的，不存明文。SendKey/邮箱只在你私有的 Supabase 里。
- 手机确认是「你点了才下单」，电脑机器人不会自作主张下你没批准的单。
