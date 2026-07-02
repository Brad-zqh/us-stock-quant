// 皓哥量化 · 外壳更新检查
// 打开 App 时对比云端 version.json 与本地 APP_VERSION, 有新外壳则弹可关闭横幅。
// 内容(行情/分析)始终来自云端 iframe, 本身就是实时最新, 无需更新提示。
(function () {
  // 各外壳在引入本脚本前, 请先设置 window.APP_VERSION = "x.y.z"
  var LOCAL = window.APP_VERSION || "0.0.0";
  var VURL = "https://brad-zqh.github.io/us-stock-quant/version.json";

  function cmp(a, b) {
    var pa = String(a).split(".").map(Number), pb = String(b).split(".").map(Number);
    for (var i = 0; i < 3; i++) {
      var x = pa[i] || 0, y = pb[i] || 0;
      if (x > y) return 1;
      if (x < y) return -1;
    }
    return 0;
  }

  function banner(v, notes, url) {
    if (localStorage.getItem("dismiss_ver") === v) return; // 用户已忽略此版本
    var bar = document.createElement("div");
    bar.style.cssText =
      "position:fixed;left:0;right:0;bottom:0;z-index:9999;background:#ef5350;color:#fff;" +
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
    x.onclick = function () { localStorage.setItem("dismiss_ver", v); bar.remove(); };
    bar.appendChild(msg); bar.appendChild(go); bar.appendChild(x);
    document.body.appendChild(bar);
  }

  try {
    fetch(VURL, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.version && cmp(j.version, LOCAL) > 0) {
          banner(j.version, j.notes || "", j.downloadUrl ||
            "https://brad-zqh.github.io/us-stock-quant/download.html");
        }
      })
      .catch(function () {});
  } catch (e) {}
})();
