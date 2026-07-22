"""认知层 LLM 客户端——grsai OpenAI 兼容端点 /v1/chat/completions。

- 基础节点：全球 https://grsaiapi.com / 国内 https://grsai.dakka.com.cn
  执行节点在香港，两者可达；默认走全球节点，可配置切国内。
- 鉴权：Authorization: Bearer sk-xxx
- 决策层用非流式（stream=false），需完整 output 一次性解析。
- HTTP 传输注入（Transport 协议），便于确定性单测；默认用 httpx。

宪法 II：本客户端只负责「取得 LLM 文本」，输出仍须过 validator→breaker→fusion，
不触及任何权限边界。成本计入 BudgetGuard（超预算即停调，降级纯量化）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

GLOBAL_BASE = "https://grsaiapi.com"
DOMESTIC_BASE = "https://grsai.dakka.com.cn"


class Transport(Protocol):
    def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> dict[str, Any]:
        """发 POST，返回解析后的 JSON dict。失败抛异常。"""
        ...


class LLMError(RuntimeError):
    """端点返回错误（含 400 error.message）。"""


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    request_id: str


class HttpxTransport:
    """默认传输：httpx 同步客户端。"""

    def __init__(self, timeout: float = 60.0) -> None:
        self._timeout = timeout

    def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> dict[str, Any]:
        import httpx

        with httpx.Client(timeout=self._timeout) as c:
            r = c.post(url, headers=headers, json=json)
            data = r.json()
            if r.status_code >= 400:
                msg = data.get("error", {}).get("message", r.text)
                raise LLMError(f"HTTP {r.status_code}: {msg}")
            return data


class GrsaiClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = GLOBAL_BASE,
        transport: Transport | None = None,
    ) -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._t = transport or HttpxTransport()

    def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
    ) -> ChatResult:
        """非流式补全。messages: [{"role": "...", "content": "..."}]。"""
        url = f"{self._base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {"model": model, "stream": False, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature

        data = self._t.post(url, headers, body)
        return parse_completion(data)


def parse_completion(data: dict[str, Any]) -> ChatResult:
    """解析非流式响应；兼容 usage 字段可能缺失。"""
    if "error" in data:
        raise LLMError(data["error"].get("message", "unknown error"))
    choices = data.get("choices") or []
    if not choices:
        raise LLMError("响应无 choices")
    content = choices[0].get("message", {}).get("content", "")
    usage = data.get("usage") or {}
    return ChatResult(
        content=content,
        prompt_tokens=int(usage.get("prompt_tokens", 0)),
        completion_tokens=int(usage.get("completion_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
        model=data.get("model", ""),
        request_id=data.get("id", ""),
    )


def estimate_cost(result: ChatResult, per_1k_total: Decimal) -> Decimal:
    """粗略估算（单一混合价 × total_tokens/1k）。精确计费用 cost_rmb。"""
    return (Decimal(result.total_tokens) / Decimal(1000)) * per_1k_total


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """grsai 计费：¥ / 百万 token，input 与 output 分开（取上限保守估算）。"""
    input_per_m: Decimal
    output_per_m: Decimal


def cost_rmb(result: ChatResult, pricing: ModelPricing) -> Decimal:
    """精确成本（¥）：input×input价 + output×output价。

    价格来自 cognitive.yaml（会随 grsai 调价而变），不在代码写死。
    gpt-5.4 等推理模型的 completion_tokens 含大量推理 token，按 output 计价。
    """
    inp = Decimal(result.prompt_tokens) / Decimal(1_000_000) * pricing.input_per_m
    out = Decimal(result.completion_tokens) / Decimal(1_000_000) * pricing.output_per_m
    return inp + out


def cost_usd(result: ChatResult, pricing: ModelPricing, usd_rmb_rate: Decimal) -> Decimal:
    """折算为 USD，供 BudgetGuard 与宪法 USD 上限比较。汇率来自 config。"""
    return cost_rmb(result, pricing) / usd_rmb_rate


def load_pricing(cfg: dict) -> dict[str, ModelPricing]:
    """从 cognitive.yaml 的 provider.pricing 构建每模型定价表。"""
    out: dict[str, ModelPricing] = {}
    for model, p in cfg.get("pricing", {}).items():
        out[model] = ModelPricing(
            input_per_m=Decimal(str(p["input_per_m"])),
            output_per_m=Decimal(str(p["output_per_m"])),
        )
    return out
