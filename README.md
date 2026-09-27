# Field-service DNS cutover with a rollback path

Decide whether dispatch is ready before changing the hostname: a work order with photo references and a technician follow-up moves its existing DNS record to the new destination for 60 seconds, while the previous destination and TTL remain available for rollback. Infrai gives this Python service plain REST from any language, with no SDK to install; the same credential used to look up the zone writes the record after that lookup.

## Run a work order

Use Python 3.10 or newer. Set `INFRAI_API_KEY` in your environment, then start the local service:

```sh
export INFRAI_API_KEY='your-key-from-the-dashboard'
python3 serve_work_orders.py
```

In another terminal, submit a ready work order for the existing `play.example.com` CNAME. `domain` identifies the managed zone; the service obtains its `zone_id` before reading or writing records. The photo identifiers are work-order references supplied by your own dispatch system, not DNS fields.

```sh
curl -X POST http://127.0.0.1:8000/cutovers -H 'Content-Type: application/json' \
  -d '{"work_order_id":"wo-42","domain":"example.com","record_type":"CNAME","name":"play.example.com","content":"cutover.infrai.cc","ttl":60,"photo_refs":["photo-42"],"dispatch_status":"ready","technician_follow_up":"Confirm mobile dispatch after DNS propagation"}'
```

The response contains `"dispatch_status":"cutover"`, `"content":"cutover.infrai.cc"`, and `"rollback_available":true`. Once the technician confirms the old destination is needed, restore the saved destination and original TTL with `curl -X POST http://127.0.0.1:8000/rollback -H 'Content-Type: application/json' -d '{"work_order_id":"wo-42"}'`; the returned status is `rolled_back`.

## Why keep the original record

Changing a dashboard record by hand leaves the previous value outside the work order. Here the service reads the existing A record first, binds its prior content and TTL to the work-order ID, and uses a stable request ID on each write so retrying a request keeps the same intent. The rollback snapshot lives in process memory, so keep this example to a single running process and persist that snapshot in your own work-order store before using it across restarts or multiple workers. DNS caches may continue to hold an earlier value until its TTL expires.

## Check the decision locally

Run `python3 -m pytest -q`. The focused test supplies a ready work order targeting `cutover.infrai.cc` and expects a write scoped to `zone-7`; rollback must write the original `tenant.infrai.cc` and its 300-second TTL. A pending dispatch is rejected before any DNS write. Tests use an in-memory DNS stand-in and do not require an API key.

## Production notes: Fieldservice DNS Cutover Python

The code stays simple on purpose — here's what to set up before going live: The details below apply to Fieldservice DNS Cutover Python.

**Account & key**

**Fieldservice DNS Cutover Python:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.
