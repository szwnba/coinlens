"""全链路测试：本地起一个 mock 的 OpenAI 兼容服务，验证真实 LLM 调用路径。

用法：python3 tests/test_pipeline_mock_llm.py
"""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# 必须在导入 app 前设置：指向 mock 服务器
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:8390/v1"
os.environ["LLM_API_KEY"] = "test-key"
os.environ["LLM_MODEL"] = "mock-model"

ROLE_REPLY = json.dumps({
    "summary": "技术结构偏强，均线多头排列，但 RSI 已进入超买区，短线有回调风险。",
    "bullish": ["价格站稳 MA25 上方", "放量突破前高"],
    "bearish": ["RSI 超买", "接近摆动阻力位"],
    "confidence": 65,
}, ensure_ascii=False)

SYNTH_REPLY = json.dumps({
    "headline": "强势趋势中的高位整固",
    "bias": "偏多",
    "summary": "多空对比偏多，技术趋势与情绪共振，但短线超买需防回调，建议回踩确认后轻仓参与。",
    "plan": {
        "entry_range": [100000, 104000],
        "stop_loss": 96000,
        "take_profit": [112000, 120000],
        "position_advice": "轻仓试探，不超过 5%",
        "invalidation": "日线收盘跌破 MA25 且资金费率转负",
    },
    "scenarios": {
        "bull": "放量突破阻力位，看向前高",
        "base": "区间震荡消化超买",
        "bear": "跌破支撑，回踩 MA99",
    },
    "key_risks": ["费率过热引发多头踩踏", "宏观突发利空", "流动性不足放大波动"],
    "confidence": 60,
}, ensure_ascii=False)


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        auth = self.headers.get("Authorization", "")
        user_text = body["messages"][-1]["content"]
        if "/chat/completions" not in self.path:
            self.send_response(404); self.end_headers(); return
        if auth != "Bearer test-key":
            self.send_response(401); self.end_headers(); return
        # 综合研判 prompt 含"研究主管"，角色分析含"分析师"
        content = SYNTH_REPLY if "研究主管" in user_text else ROLE_REPLY
        resp = {"choices": [{"message": {"role": "assistant", "content": content}}]}
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # 静默
        pass


def main():
    server = HTTPServer(("127.0.0.1", 8390), MockHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    from app import pipeline  # 导入时读取 env 配置
    from app.llm import parse_json

    # 1) parse_json 鲁棒性
    assert parse_json('前置说明```json\n{"a": 1}\n```后置') == {"a": 1}
    assert parse_json('{"a": [1,2]}') == {"a": [1, 2]}
    print("[ok] parse_json 鲁棒性")

    async def run():
        stages = []
        async def prog(stage, detail=""):
            stages.append(stage)
        rep = await pipeline.run_research("ETH", "", progress=prog)
        assert rep["synthesis"] and rep["synthesis"]["bias"] == "偏多"
        assert all(not r.get("error") for r in rep["roles"].values()), rep["roles"]
        assert len(stages) == 5, stages
        assert rep["data_status"]["klines"].startswith("ok")
        print("[ok] 完整流水线（mock LLM）：四维分析 + 综合研判 + 报告落盘")
        print("     ETH 恐贪:", rep["fear_greed"]["current"]["value"],
              "| 费率:", round(rep["derivatives"]["funding_current_pct"], 4),
              "| 数据源:", rep["data_status"]["klines"], "/",
              rep["derivatives"]["source"])
        from app import report as store
        assert store.get(rep["id"])["id"] == rep["id"]
        print("[ok] 报告读取:", rep["id"])

    asyncio.run(run())
    server.shutdown()
    print("\n全部通过 ✓")


if __name__ == "__main__":
    main()
