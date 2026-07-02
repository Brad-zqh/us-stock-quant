# 📦 app-shell —— 把量化看板封装成 App（手机 + 桌面）

你的软件本体是一个 **Streamlit 网页应用**（`../app.py`，已部署在 Streamlit Cloud）。
这里三套"外壳"都指向同一个云端网址，**不改动、不重写** Python 代码，四端统一：

| 目录 | 平台 | 成本 | 产物 |
|------|------|------|------|
| `web/` | iOS / 安卓 / Mac / Win | **零构建、免费** | PWA（添加到主屏幕/桌面即成 App）|
| `capacitor/` | iOS + Android | 需 Xcode / Android Studio | 可上架 App Store / Google Play 的原生包 |
| `tauri/` | macOS + Windows | 需 Rust 工具链 | `.dmg` / `.exe` / `.msi` 桌面安装包 |

> 云端网址写在各壳的 `index.html` 里的 `STREAMLIT_URL`。换了部署地址就改这里。

---

## ✅ 今天就能装（PWA，无需任何构建）

### 方式 A —— 最快，0 设置（现在就能用）
云端应用本身就是 HTTPS 网页，手机浏览器可直接"装"：
- **iPhone**：Safari 打开
  `https://us-stock-quant-txpjva2xepffh9h2peiaup.streamlit.app/`
  → 点底部「分享」→「添加到主屏幕」。
- **安卓**：Chrome 打开同一网址 → 右上「⋮」→「添加到主屏幕 / 安装应用」。
- **电脑(Mac/Win)**：Chrome / Edge 打开网址 → 地址栏右侧「安装」图标。

装完就有独立图标、全屏打开。**缺点**：图标是 Streamlit 默认的、有浏览器味。

### 方式 B —— 带自定义图标 + 启动页（推荐，仍免费）
把 `web/` 目录托管到 HTTPS（用你已有的 GitHub 仓库 → GitHub Pages 最省事）：

1. 把本仓库推到 GitHub（已是公开仓库即可）。
2. 仓库 **Settings → Pages** → Source 选 `Deploy from a branch` →
   分支选 `main`、目录选 `/root`（或把 `app-shell/web` 内容放到单独的 `docs/`）。
   > 简单做法：新建仓库分支只放 `web/` 内容，或用下面的 Netlify 拖拽。
3. 也可用 **Netlify Drop**（`https://app.netlify.com/drop`）：直接把 `web/` 文件夹
   拖进网页，几秒得到一个 HTTPS 网址，**完全免费、无需登录命令行**。
4. 手机/电脑打开这个网址 → 同上「添加到主屏幕 / 安装」。
   现在图标是我们生成的 📈 折线图标、带启动页、隐藏了浏览器地址栏。

本地预览（可选）：
```bash
cd app-shell/web
python -m http.server 8777
# 浏览器打开 http://localhost:8777
```

---

## 📱 上架应用商店（Capacitor）
见 [`capacitor/README.md`](capacitor/README.md)。iOS 需 Mac + 苹果开发者账号($99/年)。

## 🖥️ 桌面安装包（Tauri）
见 [`tauri/README.md`](tauri/README.md)。需装 Rust 工具链，产物是很小的 `.dmg`/`.exe`。

---

## 图标
`web/icons/` 里的 PNG 由 `gen_icons.py` 生成（纯标准库）。想换成自己的图：
替换这些 PNG，或改脚本后 `python gen_icons.py` 重新生成；Capacitor/Tauri 的图标
用各自 README 里的 `capacitor-assets` / `tauri icon` 命令从 512 图一键派生。
