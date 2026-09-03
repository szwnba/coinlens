"""全局配置：从环境变量 / .env 文件读取。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"


def _load_dotenv() -> None:
    """极简 .env 加载器，避免额外依赖。已有环境变量优先。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# ---- LLM（OpenAI 兼容协议：DeepSeek / 智谱 / OpenAI 均可）----
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "180"))

# ---- 数据源 ----
# K 线/行情：Binance 公开镜像（主）→ OKX（备）；可按网络环境调整顺序
KLINE_SOURCES = [s.strip() for s in os.environ.get(
    "KLINE_SOURCES", "binance,okx").split(",") if s.strip()]
# 衍生品（资金费率/持仓量）：OKX（主）→ Bybit（备）
DERIV_SOURCES = [s.strip() for s in os.environ.get(
    "DERIV_SOURCES", "okx,bybit").split(",") if s.strip()]
# 新闻：cryptopanic（需 token）→ cointelegraph RSS（无需 token）
CRYPTOPANIC_TOKEN = os.environ.get("CRYPTOPANIC_TOKEN", "")

HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "15"))

LLM_CONFIGURED = bool(LLM_API_KEY)


def llm_status() -> dict:
    return {
        "configured": LLM_CONFIGURED,
        "base_url": LLM_BASE_URL,
        "model": LLM_MODEL,
    }
