from fieldservice_cutover import CutoverRequest, CutoverService


class FakeDNS:
    def __init__(self):
        self.writes = []

    def call(self, method, path, params, request_id=None):
        if path == "/v1/dns/domain/get":
            return {"zone_id": "zone-7"}
        if path == "/v1/dns/record/list":
            return [{"record_type": "CNAME", "name": "play.example.com", "content": "tenant.infrai.cc", "ttl": 300}]
        self.writes.append((method, path, params, request_id))
        return {}


def test_ready_work_order_cutover_and_rollback():
    dns = FakeDNS()
    service = CutoverService(dns)
    request = CutoverRequest.parse({"work_order_id": "wo-42", "domain": "example.com",
        "record_type": "CNAME", "name": "play.example.com", "content": "cutover.infrai.cc", "ttl": 60,
        "photo_refs": ["photo-42"], "dispatch_status": "ready",
        "technician_follow_up": "Confirm mobile dispatch after DNS propagation"})
    assert service.cutover(request)["dispatch_status"] == "cutover"
    assert dns.writes[0][2]["content"] == "cutover.infrai.cc"
    assert dns.writes[0][2]["zone_id"] == "zone-7"
    assert service.rollback("wo-42")["dispatch_status"] == "rolled_back"
    assert dns.writes[1][2]["content"] == "tenant.infrai.cc"
    assert dns.writes[1][2]["ttl"] == 300
    assert len(dns.writes) == 2


def test_dispatch_must_be_ready():
    try:
        CutoverRequest.parse({"work_order_id": "wo-42", "domain": "example.com",
            "record_type": "CNAME", "name": "play.example.com", "content": "cutover.infrai.cc", "ttl": 60,
            "photo_refs": ["photo-42"], "dispatch_status": "pending",
            "technician_follow_up": "Confirm dispatch"})
    except ValueError as exc:
        assert "Ready dispatch" in str(exc)
    else:
        raise AssertionError("Pending dispatch should not change DNS")
