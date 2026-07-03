// 皓量化 · 外壳更新检查 + 手动"检查更新"按钮
// 两种模式：
//  A. 桌面 App(Tauri, 支持原生更新)：直接在 App 内「下载并安装 → 自动重启」，无需手动重装。
//  B. 浏览器 / PWA / 旧版外壳：回退到对比云端 version.json，有新版引导到下载页手动安装。
// 说明: 行情与分析内容始终来自云端 iframe, 本身实时最新; 更新主要针对 App 外壳。
(function () {
  var LOCAL = window.APP_VERSION || "0.0.0";
  var BASE = "https://brad-zqh.github.io/us-stock-quant/";
  var VURL = BASE + "version.json";
  var DLURL = BASE + "download.html";

  // 原生更新入口(仅桌面 App 有)。withGlobalTauri 下 invoke 在 __TAURI__.core.invoke。
  var TAURI = window.__TAURI__ || null;
  var TInvoke =
    (TAURI && ((TAURI.core && TAURI.core.invoke) || TAURI.invoke)) || null;
  var NATIVE_OK = false; // 首次成功调用原生命令后置真

  function cmp(a, b) {
    var pa = String(a).split(".").map(Number), pb = String(b).split(".").map(Number);
    for (var i = 0; i < 3; i++) {
      var x = pa[i] || 0, y = pb[i] || 0;
      if (x > y) return 1;
      if (x < y) return -1;
    }
    return 0;
  }

  function toast(msg) {
    var t = document.createElement("div");
    t.textContent = msg;
    t.style.cssText =
      "position:fixed;left:50%;bottom:84px;transform:translateX(-50%);z-index:100000;" +
      "background:#263238;color:#fff;padding:10px 16px;border-radius:10px;max-width:80%;" +
      "font:13px -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.4)";
    document.body.appendChild(t);
    setTimeout(function () { t.style.transition = "opacity .4s"; t.style.opacity = "0"; }, 2200);
    setTimeout(function () { t.remove(); }, 2700);
  }

  // 在右下角"⟳"按钮上加一个小红点, 表示有新版可更新 (不打扰, 想更新时点按钮即可)
  function markFabDot() {
    var fab = document.getElementById("hg-upd-fab");
    if (!fab || document.getElementById("hg-upd-dot")) return;
    var dot = document.createElement("span");
    dot.id = "hg-upd-dot";
    dot.style.cssText =
      "position:absolute;top:2px;right:2px;width:10px;height:10px;border-radius:50%;" +
      "background:#ef5350;border:2px solid #0e1117;box-sizing:border-box";
    fab.style.position = "fixed";
    fab.appendChild(dot);
  }

  // 低调提示: 右下角小胶囊, 几秒后自动消失。
  // onGo 为函数时点击执行它(原生一键更新)；为字符串时作为下载链接打开。
  function banner(v, notes, onGo) {
    markFabDot();
    if (document.getElementById("hg-upd-chip")) return;
    var chip = document.createElement("div");
    chip.id = "hg-upd-chip";
    chip.style.cssText =
      "position:fixed;right:14px;bottom:64px;z-index:99999;max-width:240px;" +
      "background:rgba(27,36,48,.96);color:#e8eaed;border:1px solid #33404f;border-radius:12px;" +
      "font:12px -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;padding:8px 10px;" +
      "display:flex;align-items:center;gap:8px;box-shadow:0 6px 20px rgba(0,0,0,.4);" +
      "opacity:0;transition:opacity .3s";
    var msg = document.createElement("div");
    msg.style.cssText = "flex:1;line-height:1.35";
    msg.innerHTML = "有新版 <b>v" + v + "</b>";
    var go;
    if (typeof onGo === "function") {
      go = document.createElement("button");
      go.textContent = "更新";
      go.style.border = "0";
      go.style.cursor = "pointer";
      go.onclick = function () { chip.remove(); onGo(); };
    } else {
      go = document.createElement("a");
      go.href = onGo || DLURL; go.target = "_blank"; go.rel = "noopener";
      go.textContent = "下载";
    }
    go.style.cssText +=
      ";background:#2c3a4b;color:#fff;font-weight:600;text-decoration:none;" +
      "padding:4px 10px;border-radius:8px;white-space:nowrap;font-size:12px";
    var x = document.createElement("button");
    x.textContent = "✕";
    x.title = "关闭";
    x.style.cssText =
      "background:transparent;border:0;color:#9aa0aa;font-size:13px;cursor:pointer;padding:2px 4px";
    x.onclick = function () { chip.remove(); };
    chip.appendChild(msg); chip.appendChild(go); chip.appendChild(x);
    document.body.appendChild(chip);
    requestAnimationFrame(function () { chip.style.opacity = "1"; });
    setTimeout(function () {
      if (!chip.parentNode) return;
      chip.style.opacity = "0";
      setTimeout(function () { chip.remove(); }, 350);
    }, 6000);
  }

  // 强制刷新: 清 Service Worker 缓存并重载, 让 App 外壳/PWA 立即取最新
  function forceRefresh() {
    toast("正在清理缓存并刷新…");
    var done = function () {
      try {
        var u = new URL(window.location.href);
        u.searchParams.set("_r", Date.now());
        window.location.replace(u.toString());
      } catch (e) { window.location.reload(true); }
    };
    var tasks = [];
    if (window.caches && caches.keys) {
      tasks.push(caches.keys().then(function (ks) {
        return Promise.all(ks.map(function (k) { return caches.delete(k); }));
      }).catch(function () {}));
    }
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      tasks.push(navigator.serviceWorker.getRegistrations().then(function (rs) {
        return Promise.all(rs.map(function (r) { return r.unregister(); }));
      }).catch(function () {}));
    }
    Promise.all(tasks).then(done).catch(done);
    setTimeout(done, 1500);
  }

  // —— 原生(桌面 App)更新 ——
  // 下载并安装最新版, 完成后 App 自动重启。
  function nativeInstall() {
    if (!TInvoke) { window.open(DLURL, "_blank", "noopener"); return; }
    toast("正在下载并安装更新, 完成后会自动重启…");
    TInvoke("install_update").then(function () {
      toast("更新完成, 正在重启…");
    }).catch(function (e) {
      // 该版本外壳不支持原生更新 → 回退到手动下载
      toast("无法自动更新, 已打开下载页");
      window.open(DLURL, "_blank", "noopener");
    });
  }

  // 原生检查: 成功即标记 NATIVE_OK。返回是否有新版。
  function nativeCheck(manual) {
    return TInvoke("check_update").then(function (info) {
      NATIVE_OK = true;
      if (info && info.version) {
        banner(info.version, info.notes || "", nativeInstall); // 点"更新"=一键安装
        return true;
      }
      if (manual) toast("✅ 已是最新版本 v" + LOCAL);
      return false;
    });
  }

  // —— 浏览器 / PWA / 旧壳: 对比 version.json, 引导手动下载 ——
  function legacyCheck(manual) {
    return fetch(VURL, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.version && cmp(j.version, LOCAL) > 0) {
          banner(j.version, j.notes || "", j.downloadUrl || DLURL); // 点"下载"=打开下载页
          return true;
        }
        if (manual) toast("✅ 已是最新版本 v" + LOCAL);
        return false;
      })
      .catch(function () { if (manual) toast("检查失败, 请检查网络"); return false; });
  }

  // 统一入口: 桌面 App 优先走原生, 失败(旧壳/浏览器)自动回退。
  function checkNow(manual) {
    if (TInvoke) {
      return nativeCheck(manual).catch(function () { return legacyCheck(manual); });
    }
    return legacyCheck(manual);
  }

  // 右下角面板
  function openPanel() {
    var dot = document.getElementById("hg-upd-dot");
    if (dot) dot.remove();
    var old = document.getElementById("hg-upd-panel");
    if (old) { old.remove(); return; }
    var box = document.createElement("div");
    box.id = "hg-upd-panel";
    box.style.cssText =
      "position:fixed;right:14px;bottom:64px;z-index:100000;width:214px;background:#1b2430;" +
      "color:#e8eaed;border:1px solid #33404f;border-radius:14px;padding:12px;" +
      "font:13px -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.5)";
    box.innerHTML =
      "<div style='font-weight:700;margin-bottom:8px'>🛠 更新与刷新</div>" +
      "<div style='opacity:.75;margin-bottom:10px'>当前版本 v" + LOCAL +
      (TInvoke ? " · 桌面版" : "") + "</div>";
    function mkBtn(label, fn) {
      var b = document.createElement("button");
      b.textContent = label;
      b.style.cssText =
        "display:block;width:100%;margin:6px 0;padding:9px 10px;border:0;border-radius:9px;" +
        "background:#2c3a4b;color:#fff;font-size:13px;cursor:pointer;text-align:left";
      b.onmouseover = function () { b.style.background = "#37485c"; };
      b.onmouseout = function () { b.style.background = "#2c3a4b"; };
      b.onclick = fn;
      box.appendChild(b);
    }
    mkBtn("🔍 检查新版本", function () { checkNow(true); });
    mkBtn("🔄 强制刷新内容", forceRefresh);
    if (TInvoke) {
      // 桌面 App: 一键下载+安装+自动重启
      mkBtn("⬇️ 一键更新 (自动重启)", nativeInstall);
    } else {
      // 浏览器 / PWA: 打开下载页手动安装
      mkBtn("⬇️ 下载最新安装包", function () { window.open(DLURL, "_blank", "noopener"); });
    }
    var close = document.createElement("div");
    close.textContent = "关闭";
    close.style.cssText = "text-align:center;margin-top:6px;opacity:.6;cursor:pointer";
    close.onclick = function () { box.remove(); };
    box.appendChild(close);
    document.body.appendChild(box);
  }

  function mountButton() {
    if (document.getElementById("hg-upd-fab")) return;
    var fab = document.createElement("button");
    fab.id = "hg-upd-fab";
    fab.title = "检查更新";
    fab.textContent = "⟳";
    fab.style.cssText =
      "position:fixed;right:14px;bottom:14px;z-index:99998;width:42px;height:42px;border-radius:50%;" +
      "border:0;background:rgba(38,50,56,.72);color:#fff;font-size:20px;cursor:pointer;" +
      "box-shadow:0 3px 12px rgba(0,0,0,.4);opacity:.55;transition:opacity .2s";
    fab.onmouseover = function () { fab.style.opacity = "1"; };
    fab.onmouseout = function () { fab.style.opacity = ".55"; };
    fab.onclick = openPanel;
    document.body.appendChild(fab);
  }

  // 对外暴露, 方便未来在别处触发
  window.HaoGeCheckUpdate = function () { return checkNow(true); };
  window.HaoGeForceRefresh = forceRefresh;

  function init() { mountButton(); checkNow(false); }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
