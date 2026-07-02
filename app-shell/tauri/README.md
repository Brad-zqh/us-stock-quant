# 🖥️ Tauri 桌面壳 (macOS + Windows)

把云端 Streamlit 打包成体积很小的桌面 App（`.dmg` / `.app` / `.exe` / `.msi`）。
本地 `www/index.html` 内嵌 iframe 加载你的云端网址 + 启动页。

> 想改地址：编辑 `www/index.html` 里的 `STREAMLIT_URL`。

## 前置环境
- Node.js 18+
- Rust 工具链（`https://rustup.rs`，装完有 `cargo`）
- **Windows**：Microsoft C++ Build Tools + WebView2（Win10/11 一般自带）
- **macOS**：Xcode Command Line Tools（`xcode-select --install`）
- Linux 额外需 `libwebkit2gtk-4.1-dev` 等（仅在 Linux 打包时）

## 生成图标（必做一次，否则打包会因缺图标失败）
```bash
cd app-shell/tauri
npm install
npx tauri icon ../web/icons/icon-512.png
# 会在 src-tauri/icons/ 生成 icon.ico / icon.icns / 各尺寸 png
```

## 开发预览
```bash
npm run dev      # 打开桌面窗口, 热调试
```

## 打包安装包
```bash
npm run build
# 产物在 src-tauri/target/release/bundle/
#   macOS  -> dmg / macos(.app)
#   Windows-> msi / nsis(.exe)
```

> 交叉编译不便：Mac 安装包在 macOS 上打，Windows 安装包在 Windows 上打。
> 想给别人 Win 版但你用 Mac：可用 GitHub Actions 的 windows runner 自动出包。
