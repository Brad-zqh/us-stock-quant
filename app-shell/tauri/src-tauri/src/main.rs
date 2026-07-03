// 桌面壳入口：窗口与加载逻辑由 tauri.conf.json 定义。
// 本地 www/index.html 内嵌 iframe 加载云端 Streamlit（含启动页）。
// 自动更新：注册 updater 插件，并暴露两个命令给前端 update-check.js 调用：
//   - check_update  : 查询是否有新版（不安装），返回 {version, notes} 或 null
//   - install_update: 下载并安装最新版，完成后自动重启
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri_plugin_updater::UpdaterExt;

#[derive(serde::Serialize)]
struct UpdateInfo {
    version: String,
    notes: String,
}

// 只检查，不安装。有新版返回 Some(信息)，已最新返回 None。
#[tauri::command]
async fn check_update(app: tauri::AppHandle) -> Result<Option<UpdateInfo>, String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    match updater.check().await {
        Ok(Some(update)) => Ok(Some(UpdateInfo {
            version: update.version.clone(),
            notes: update.body.clone().unwrap_or_default(),
        })),
        Ok(None) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

// 下载并安装最新版，装好后自动重启到新版本。
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    if let Some(update) = updater.check().await.map_err(|e| e.to_string())? {
        update
            .download_and_install(|_chunk, _total| {}, || {})
            .await
            .map_err(|e| e.to_string())?;
        app.restart();
    }
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![check_update, install_update])
        .run(tauri::generate_context!())
        .expect("运行 Tauri 应用出错");
}
