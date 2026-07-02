# 📱 Capacitor 移动壳 (iOS + Android)

把已部署的云端 Streamlit（`app.py`）包成可上架 App Store / Google Play 的原生 App。
壳内是一个全屏 WebView，加载 `www/index.html`（再 iframe 你的云端网址 + 启动页）。

> 想改地址：编辑 `www/index.html` 里的 `STREAMLIT_URL`。

## 前置环境
- Node.js 18+（`node -v`）
- **iOS**：macOS + Xcode + 苹果开发者账号（$99/年，用于真机/上架）
- **Android**：Android Studio（含 JDK 17）

## 一次性初始化
```bash
cd app-shell/capacitor
npm install
npx cap add ios        # 生成 ios/ 原生工程 (仅 macOS)
npx cap add android    # 生成 android/ 原生工程
```

## 生成 App 图标（用仓库里已有的图标源）
```bash
# 安装图标生成器, 用 512 图一键生成所有尺寸
npm i -D @capacitor/assets
npx capacitor-assets generate --iconBackgroundColor "#0e1117" \
  --iconBackgroundColorDark "#0e1117"
# 若提示缺少 resources/icon.png, 先把 ../web/icons/icon-512.png 复制为 resources/icon.png
```

## 每次改了 www/ 后同步
```bash
npx cap sync
```

## 打开原生工程 → 运行 / 打包
```bash
npx cap open ios       # Xcode: 选真机/模拟器 Run; Product > Archive 上架
npx cap open android   # Android Studio: Run; Build > Generate Signed Bundle 上架
```

## ⚠️ 上架注意
- 苹果对"纯网页套壳"审核较严（Guideline 4.2 minimum functionality）。建议：
  用原生启动页 + 让 App 有清晰功能定位（本 App 是"个股量化分析工具"，可通过）。
  必要时后续把关键交互做成原生页面以提高通过率。
- Android/Google Play 对套壳更宽松。
