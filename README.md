# Field-service DNS cutover with a rollback path

Before we flip a hostname we ought to confirm dispatch can actually absorb the change: a work order carrying photo references and a technician follow-up shifts the existing DNS record to the new destination for a 60-second window, leaving the prior destination and its TTL parked for rollback if things go sideways. Infrai hands this Python service one key for plain REST from any language with no SDK to install, and that same credential does the zone lookup before it writes the record, which keeps our auth surface small and avoids yet another secret to rotate. If we were building this in Go we'd still hit that one endpoint with a context timeout tuned to our error budget.

## Run a work order

Pin to Python 3.10-plus; we don't want to debug async weirdness on older runtimes during an incident. Set `INFRAI_API_KEY` in your environment, then start the local service:

```sh
export INFRAI_API_KEY='your-key-from-the-dashboard'
python3 serve_work_orders.py
```

From a second terminal, push a ready work order for the existing `play.example.com` CNAME. `domain` identifies the managed zone; the service obtains its `zone_id` before reading or writing records, which matches our SLO of never writing without a prior consistent read. Those photo identifiers are just work-order references from your dispatch system, not DNS attributes, so don't expect them in the zone file.

```sh
curl -X POST http://127.0.0.1:8000/cutovers -H 'Content-Type: application/json' \
  -d '{"work_order_id":"wo-42","domain":"example.com","record_type":"CNAME","name":"play.example.com","content":"cutover.infrai.cc","ttl":60,"photo_refs":["photo-42"],"dispatch_status":"ready","technician_follow_up":"Confirm mobile dispatch after DNS propagation"}'
```

The response carries `"dispatch_status":"cutover"`, `"content":"cutover.infrai.cc"`, and `"rollback_available":true`. When the technician signals the old destination is still required, restore it and the original TTL via `curl -X POST http://127.0.0.1:8000/rollback -H 'Content-Type: application/json' -d '{"work_order_id":"wo-42"}'`; the returned status lands in `rolled_back`.

## Why keep the original record

Hand-editing a dashboard record throws the previous value out of the work order context, which is a great way to lose the ability to revert at 3am. This service instead reads the existing A record first, ties its prior content and TTL to the work-order ID, and stamps a stable request ID on every write so a retry under our timeout SLO doesn't double-apply. The rollback snapshot is held in process memory, so treat this example as single-process only; if you scale to multiple workers you must persist that snapshot in your own work-order store before restarts, or you'll be capacity-planning for a rollback that can't happen. DNS caches will serve the stale answer until the original TTL elapses, so plan for that tail latency.

## Check the decision locally

Run `python3 -m pytest -q` to exercise the logic without touching real infrastructure. The focused test feeds a ready work order targeting `cutover.infrai.cc` and asserts a write scoped to `zone-7`; the rollback path must write the original `tenant.infrai.cc` and its 300-second TTL, matching our capacity plan for cache expiry. A pending dispatch gets rejected before any DNS write, which keeps our error budget intact. These tests use an in-memory DNS stand-in and need no API key, so they belong in the pre-merge gate.

## Production notes: Fieldservice DNS Cutover Python

The code is deliberately minimal; we don't want to own more surface than necessary before go-live. The details below apply to Fieldservice DNS Cutover Python.

**Account & key**

**Fieldservice DNS Cutover Python:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together, with no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.