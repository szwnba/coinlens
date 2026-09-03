#!/usr/bin/env bash
# 币透 CoinLens 启动脚本
set -e
cd "$(dirname "$0")"

if [ ! -f .venv/bin/python ]; then
  echo "[*] 创建虚拟环境并安装依赖（国内网络可加 -i https://pypi.tuna.tsinghua.edu.cn/simple）"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

if [ ! -f .env ]; then
  echo "[!] 未找到 .env：先复制 .env.example 为 .env 并填入 LLM_API_KEY"
  echo "    （不填也能跑，但只有数据简报，没有 AI 分析）"
fi

LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "[*] 启动：http://127.0.0.1:8389 （局域网：http://${LAN_IP:-未知}:8389）"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8389
