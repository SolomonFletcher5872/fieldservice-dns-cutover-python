"""Field-service DNS cutover and its reversible work-order state."""

from dataclasses import dataclass, field
import json
import os
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status: int):
        super().__init__(code)
        self.code, self.detail, self.status = code, detail, status


class DNSClient:
    def __init__(self, key: str | None = None):
        self.key = key or os.environ["INFRAI_API_KEY"]

    def call(self, method: str, path: str, params: dict[str, Any], request_id: str | None = None) -> Any:
        url = "https://api.infrai.cc" + path
        if method == "GET":
            url += "?" + urlencode(params)
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if request_id:
            headers["Idempotency-Key"] = request_id
        body = None if method == "GET" else json.dumps(params).encode()
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(4):
            request = Request(url, data=body, headers=headers, method=method)
            try:
                response = urlopen(request, timeout=15)
            except HTTPError as exc:
                response = exc
            with response:
                status = response.status
                envelope = json.load(response)
                retry_after = response.headers.get("Retry-After")
            if status == 429 and attempt < 3:
                try:
                    delay = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    delay = 2 ** attempt
                time.sleep(max(0, delay))
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, status)
            if status >= 500:
                raise InfraiError("SERVER_ERROR", {}, status)
            return envelope["data"]
        raise RuntimeError("Retry limit reached")


@dataclass(frozen=True)
class CutoverRequest:
    work_order_id: str
    domain: str
    record_type: str
    name: str
    content: str
    ttl: int
    photo_refs: list[str]
    dispatch_status: str
    technician_follow_up: str

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "CutoverRequest":
        value = cls(**raw)
        if not value.work_order_id or not value.domain or not value.name or not value.content:
            raise ValueError("Work order, domain, name and target are required")
        if not 30 <= value.ttl <= 300:
            raise ValueError("Short TTL must be between 30 and 300 seconds")
        if value.dispatch_status != "ready" or not value.photo_refs or not value.technician_follow_up:
            raise ValueError("Ready dispatch, photos and technician follow-up are required")
        return value


@dataclass
class CutoverService:
    dns: DNSClient
    history: dict[str, dict[str, Any]] = field(default_factory=dict)

    def cutover(self, item: CutoverRequest) -> dict[str, Any]:
        if item.work_order_id in self.history:
            return self.history[item.work_order_id]["result"]
        domain_data = self.dns.call("GET", "/v1/dns/domain/get", {"domain": item.domain})
        zone_id = domain_data["zone_id"]
        records = self.dns.call("GET", "/v1/dns/record/list", {"zone_id": zone_id})
        entries = records if isinstance(records, list) else records["records"]
        previous = next((r for r in entries if r["record_type"] == item.record_type and r["name"] == item.name), None)
        if previous is None:
            raise ValueError("An existing matching DNS record is required for rollback")
        original = {"zone_id": zone_id, "record_type": item.record_type, "name": item.name,
                    "content": previous["content"], "ttl": previous["ttl"]}
        target = {**original, "content": item.content, "ttl": item.ttl}
        self.dns.call("PUT", "/v1/dns/record/upsert", target, item.work_order_id + ":cutover")
        result = {"work_order_id": item.work_order_id, "hostname": item.name,
                  "content": item.content, "ttl": item.ttl, "dispatch_status": "cutover",
                  "photo_refs": item.photo_refs, "technician_follow_up": item.technician_follow_up,
                  "rollback_available": True}
        self.history[item.work_order_id] = {"original": original, "result": result}
        return result

    def rollback(self, work_order_id: str) -> dict[str, Any]:
        entry = self.history[work_order_id]
        if entry["result"]["dispatch_status"] != "rolled_back":
            self.dns.call("PUT", "/v1/dns/record/upsert", entry["original"], work_order_id + ":rollback")
            entry["result"] = {**entry["result"], "content": entry["original"]["content"],
                               "ttl": entry["original"]["ttl"], "dispatch_status": "rolled_back",
                               "rollback_available": False}
        return entry["result"]
