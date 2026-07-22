"""欧易 OKX v5 签名客户端。

鉴权三要素：API Key + Secret + Passphrase。
签名 = base64(HMAC-SHA256(timestamp + method + requestPath + body, secret))，
时间戳为 ISO8601（毫秒，UTC）。HTTP 传输注入，便于单测（不打真网）。

REST 基址：全球 https://www.okx.com（香港节点可达）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Protocol

REST_BASE = "https://www.okx.com"


class Transport(Protocol):
    def request(self, method: str, url: str, headers: dict[str, str], body: str) -> dict[str, Any]:
        ...


def sign(timestamp: str, method: str, request_path: str, body: str, secret: str) -> str:
    mac = hmac.new(secret.encode(), (timestamp + method + request_path + body).encode(),
                   hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


class OKXError(RuntimeError):
    """OKX 返回 code != '0'。"""


class OKXClient:
    def __init__(
        self,
        api_key: str,
        secret: str,
        passphrase: str,
        base_url: str = REST_BASE,
        simulated: bool = True,          # 模拟盘（demo trading）header
        transport: Transport | None = None,
        clock: Any | None = None,        # 注入时间戳来源，便于确定性测试
    ) -> None:
        self._k = api_key
        self._s = secret
        self._p = passphrase
        self._base = base_url.rstrip("/")
        self._sim = simulated
        self._t = transport or _HttpxTransport()
        self._clock = clock

    def _timestamp(self) -> str:
        if self._clock is not None:
            return self._clock()
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"

    def _headers(self, method: str, path: str, body: str) -> dict[str, str]:
        ts = self._timestamp()
        h = {
            "OK-ACCESS-KEY": self._k,
            "OK-ACCESS-SIGN": sign(ts, method, path, body, self._s),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self._p,
            "Content-Type": "application/json",
        }
        if self._sim:
            h["x-simulated-trading"] = "1"   # 模拟盘标记
        return h

    def request(self, method: str, path: str, params: Any = None) -> list[dict]:
        body = json.dumps(params) if (params and method == "POST") else ""
        query = ""
        if params and method == "GET":
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        full_path = path + query
        url = f"{self._base}{full_path}"
        data = self._t.request(method, url, self._headers(method, full_path, body), body)
        if str(data.get("code")) != "0":
            # 批量接口(code=1)的真实原因在 data[0].sCode/sMsg
            inner = ""
            rows = data.get("data") or []
            if rows and isinstance(rows[0], dict):
                inner = f" | sCode={rows[0].get('sCode')} sMsg={rows[0].get('sMsg')}"
            raise OKXError(f"OKX code={data.get('code')} msg={data.get('msg')}{inner}")
        return data.get("data", [])

    # 便捷方法
    def place_order(self, **p: Any) -> list[dict]:
        return self.request("POST", "/api/v5/trade/order", p)

    def cancel_order(self, **p: Any) -> list[dict]:
        return self.request("POST", "/api/v5/trade/cancel-order", p)

    def place_algo_order(self, **p: Any) -> list[dict]:
        """止损/条件单走独立端点 /trade/order-algo（非 /trade/order）。"""
        return self.request("POST", "/api/v5/trade/order-algo", p)

    def cancel_algos(self, orders: list[dict]) -> list[dict]:
        """撤条件单：orders=[{algoId, instId}, ...]（OKX 期望 JSON 数组体）。"""
        return self.request("POST", "/api/v5/trade/cancel-algos", orders)

    def positions(self, inst_type: str = "SWAP") -> list[dict]:
        return self.request("GET", "/api/v5/account/positions", {"instType": inst_type})

    def set_leverage(self, **p: Any) -> list[dict]:
        return self.request("POST", "/api/v5/account/set-leverage", p)

    def instruments(self, inst_type: str = "SWAP") -> list[dict]:
        return self.request("GET", "/api/v5/public/instruments", {"instType": inst_type})


class _HttpxTransport:
    def request(self, method: str, url: str, headers: dict[str, str], body: str) -> dict[str, Any]:
        import httpx

        with httpx.Client(timeout=15.0) as c:
            r = c.request(method, url, headers=headers, content=body or None)
            return r.json()
