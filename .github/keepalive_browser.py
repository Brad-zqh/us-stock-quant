"""真实无头浏览器保活脚本 (供 keepalive-loop.yml 调用)。

Streamlit Community Cloud 的休眠计时器只认"真实会话"(建立 websocket
连到 /_stcore/stream 的访客)。单纯 curl GET 只从 CDN 边缘拿到静态外壳,
reset 不了休眠计时器。所以这里用 Playwright 真正打开页面、等应用渲染、
停留一会儿, 相当于一个真访客, 才能有效防休眠。

单次运行循环 ~5.5h, 每 ~6 分钟打开一次并停留 25s。
配合 workflow 的 concurrency, 上一轮结束时新一轮无缝接力 -> 全天候。
"""
import time
from playwright.sync_api import sync_playwright

APP = "https://us-stock-quant-txpjva2xepffh9h2peiaup.streamlit.app/"
ITERS = 55        # 55 次 * ~6 分钟 ≈ 5.5h
GAP = 360         # 每轮间隔 6 分钟
HOLD = 25         # 每次停留 25s, 让 websocket 会话计入活跃
READY_MARKERS = ("皓量化", "个股详情", "配置", "大盘环境")


def wake_once(pw, i):
    browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    ok = False
    try:
        page.goto(APP, wait_until="domcontentloaded", timeout=90000)
        # 等应用真正渲染出内容, 最长 ~90s
        for _ in range(18):
            try:
                body = page.inner_text("body")
            except Exception:
                body = ""
            if any(m in body for m in READY_MARKERS):
                ok = True
                break
            time.sleep(5)
        time.sleep(HOLD)  # 保持会话活跃
        try:
            blen = len(page.inner_text("body") or "")
        except Exception:
            blen = -1
        print(f"[{i}/{ITERS}] loaded_ok={ok} body_len={blen}", flush=True)
    except Exception as e:
        print(f"[{i}/{ITERS}] error: {e}", flush=True)
    finally:
        try:
            ctx.close()
        finally:
            browser.close()


def main():
    with sync_playwright() as pw:
        for i in range(1, ITERS + 1):
            wake_once(pw, i)
            if i < ITERS:
                time.sleep(GAP)
    print("本轮浏览器保活结束, 交由下一轮接力。", flush=True)


if __name__ == "__main__":
    main()
