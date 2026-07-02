// 桌面壳入口：窗口与加载逻辑由 tauri.conf.json 定义。
// 本地 www/index.html 内嵌 iframe 加载云端 Streamlit（含启动页）。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("运行 Tauri 应用出错");
}
