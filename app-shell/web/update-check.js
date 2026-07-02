// 皓哥量化 · 外壳更新检查 + 手动"检查更新"按钮
// - 打开 App 时自动对比云端 version.json, 有新版弹横幅。
// - 右下角常驻"⟳ 更新"按钮, 点开可: 检查版本 / 强制刷新内容 / 下载最新安装包。
// 说明: 行情与分析内容始终来自云端 iframe, 本身实时最新; 更新主要针对 App 外壳。
(function () {
  var LOCAL = window.APP_VERSION || "0.0.0";
  var BASE = "https://brad-zqh.github.io/us-stock-quant/";
  var VURL = BASE + "version.json";
  var DLURL = BASE + "download.html";

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

  function banner(v, notes, url) {
    if (document.getElementById("hg-upd-banner")) return;
    var bar = document.createElement("div");
    bar.id = "hg-upd-banner";
    bar.style.cssText =
      "position:fixed;left:0;right:0;bottom:0;z-index:99999;background:#ef5350;color:#fff;" +
      "font:14px -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;padding:10px 14px;" +
      "display:flex;align-items:center;gap:10px;box-shadow:0 -2px 10px rgba(0,0,0,.35)";
    var msg = document.createElement("div");
    msg.style.cssText = "flex:1;line-height:1.4";
    msg.innerHTML = "🎉 发现新版本 <b>v" + v + "</b>" +
      (notes ? "<span style='opacity:.85'> · " + notes + "</span>" : "");
    var go = document.createElement("a");
    go.href = url; go.target = "_blank"; go.rel = "noopener";
    go.textContent = "下载";
    go.style.cssText =
      "background:#fff;color:#ef5350;font-weight:700;text-decoration:none;" +
      "padding:6px 14px;border-radius:8px;white-space:nowrap";
    var x = document.createElement("button");
    x.textContent = "✕";
    x.style.cssText =
      "background:transparent;border:0;color:#fff;font-size:16px;cursor:pointer;padding:4px 6px";
    x.onclick = function () { bar.remove(); };
    bar.appendChild(msg); bar.appendChild(go); bar.appendChild(x);
    document.body.appendChild(bar);
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

  // 检查版本: manual=true 时无论新旧都给提示
  function checkNow(manual) {
    return fetch(VURL, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.version && cmp(j.version, LOCAL) > 0) {
          banner(j.version, j.notes || "", j.downloadUrl || DLURL);
          return true;
        }
        if (manual) toast("✅ 已是最新版本 v" + LOCAL);
        return false;
      })
      .catch(function () { if (manual) toast("检查失败, 请检查网络"); return false; });
  }

  // 右下角面板
  function openPanel() {
    var old = document.getElementById("hg-upd-panel");
    if (old) { old.remove(); return; }
    var box = document.createElement("div");
    box.id = "hg-upd-panel";
    box.style.cssText =
      "position:fixed;right:14px;bottom:64px;z-index:100000;width:210px;background:#1b2430;" +
      "color:#e8eaed;border:1px solid #33404f;border-radius:14px;padding:12px;" +
      "font:13px -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.5)";
    box.innerHTML =
      "<div style='font-weight:700;margin-bottom:8px'>🛠 更新与刷新</div>" +
      "<div style='opacity:.75;margin-bottom:10px'>当前版本 v" + LOCAL + "</div>";
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
    mkBtn("⬇️ 下载最新安装包", function () { window.open(DLURL, "_blank", "noopener"); });
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