"""Run the work-order cutover service with python3 serve_work_orders.py."""

from dataclasses import fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os

from fieldservice_cutover import CutoverRequest, CutoverService, DNSClient, InfraiError


service = None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            if self.path == "/cutovers":
                allowed = {field.name for field in fields(CutoverRequest)}
                if set(payload) != allowed:
                    raise ValueError("Cutover fields do not match the request model")
                result = service.cutover(CutoverRequest.parse(payload))
            elif self.path == "/rollback":
                if set(payload) != {"work_order_id"}:
                    raise ValueError("Rollback requires work_order_id")
                result = service.rollback(payload["work_order_id"])
            else:
                self.send_error(404)
                return
            status = 200
        except (ValueError, TypeError, KeyError) as exc:
            status, result = 400, {"error": str(exc)}
        except InfraiError as exc:
            status = exc.status if 400 <= exc.status < 500 else 502
            result = {"error": exc.code, "detail": exc.detail}
        encoded = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


if __name__ == "__main__":
    service = CutoverService(DNSClient())
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()
