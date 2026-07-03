#!/usr/bin/env python3
"""生成 Tauri updater 的 latest.json。

因为 productName 是中文（皓量化），Tauri 打出的更新产物文件名首字符是非 ASCII，
上传到 GitHub 后资产名被裁成 "_1.0.6_x64-setup.exe" 之类，tauri-action 无法把
签名和产物对上, 于是跳过 latest.json 上传。这里独立兜底生成。

从环境变量读取:
  BASE      资产下载 URL 前缀, 形如 https://github.com/OWNER/REPO/releases/download/TAG
  VER       版本号(不含 v)
  WIN_SIG / WIN_FILE   Windows 签名文件名 / 安装包资产名
  MAC_SIG / MAC_FILE   macOS 签名文件名 / 更新包资产名
  NOTES     (可选) 更新说明
签名文件需已下载到当前工作目录。输出 latest.json 到当前目录。
"""
import datetime
import json
import os
import urllib.parse


def q(name: str) -> str:
    return os.environ["BASE"] + "/" + urllib.parse.quote(name)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


ver = os.environ["VER"]
win_sig, win_file = os.environ["WIN_SIG"], os.environ["WIN_FILE"]
mac_sig, mac_file = os.environ["MAC_SIG"], os.environ["MAC_FILE"]

obj = {
    "version": ver,
    "notes": os.environ.get("NOTES", "皓量化 %s" % ver),
    "pub_date": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "platforms": {
        "windows-x86_64": {"signature": read(win_sig), "url": q(win_file)},
        "darwin-x86_64": {"signature": read(mac_sig), "url": q(mac_file)},
        "darwin-aarch64": {"signature": read(mac_sig), "url": q(mac_file)},
    },
}

with open("latest.json", "w", encoding="utf-8") as f:
    json.dump(obj, f, ensure_ascii=False, indent=2)

print(json.dumps(obj, ensure_ascii=False, indent=2))
