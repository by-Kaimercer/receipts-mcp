"""Deterministic generator for corpus/app.log (about 6000 lines, one day, planted needles)."""
import os
import random

DAY = "2026-03-14"
N_NOISE = 5980
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus", "app.log")


def ts(sec, ms):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{DAY}T{h:02d}:{m:02d}:{s:02d}.{ms:03d}Z"


def hms(h, m, s):
    return h * 3600 + m * 60 + s


# (second, millisecond, level, component, message) -- the planted needles.
NEEDLES = [
    # deploy of a specific version (start + finish)
    (hms(2, 10, 5), 118, "INFO", "deploy", "rollout started version=4.18.2 previous=4.17.9 strategy=rolling batch=4 by=ci-pipeline-8841"),
    (hms(2, 14, 50), 640, "INFO", "deploy", "rollout finished version=4.18.2 healthy_pods=24/24"),
    # database failover
    (hms(3, 42, 17), 203, "ERROR", "db", "primary db-primary-1 unreachable after 3 heartbeat misses, starting failover"),
    (hms(3, 42, 29), 877, "WARN", "db", "failover complete: promoted replica-db-3 to primary, old primary db-primary-1 fenced"),
    # cert expiry warning
    (hms(5, 0, 1), 12, "WARN", "tls", "certificate for pay.shopfleet-demo.example expires in 9 days (not_after=2026-03-23)"),
    # feature flag rollout
    (hms(7, 31, 12), 455, "INFO", "config", "feature flag new-checkout-flow set to 25% rollout by user ops-lena"),
    # lockout
    (hms(8, 54, 3), 90, "WARN", "auth", "failed login for user u-48213 from 203.0.113.77 (attempt 7 of 7)"),
    (hms(8, 54, 3), 214, "ERROR", "auth", "account u-48213 locked for 30 minutes after 7 consecutive failed logins"),
    # config reload
    (hms(10, 2, 41), 331, "INFO", "config", "reloaded config: cache.ttl_seconds changed from 300 to 900"),
    # worker crash
    (hms(11, 27, 9), 760, "ERROR", "worker", "worker-emailer-2 exited unexpectedly with exit code 137 (signal SIGKILL), 14 jobs requeued"),
    # billing double charge
    (hms(13, 5, 33), 402, "INFO", "billing", "charge succeeded invoice=INV-2026-88417 amount=1249.00 USD gateway_txn=gt_5521a"),
    (hms(13, 5, 36), 118, "ERROR", "billing", "duplicate charge detected: invoice=INV-2026-88417 charged a second time (gateway_txn=gt_5521b), refund queued"),
    # slow query
    (hms(14, 12, 44), 509, "WARN", "db", "slow query on ledger_entries took 8423 ms (threshold 1000 ms): SELECT sum(amount) FROM ledger_entries WHERE period = $1"),
    # webhook failure
    (hms(15, 40, 22), 71, "ERROR", "webhook", "delivery to https://hooks.partner-zeta.example/ingest failed after 5 retries (last status 503), event evt_30912 dropped"),
    # schema migration
    (hms(16, 3, 7), 288, "INFO", "db", "migration 0147_add_ledger_index applied in 212 s"),
    # disk usage
    (hms(17, 18, 55), 640, "WARN", "infra", "disk usage on node ip-10-0-7-23 volume /var/lib/postgresql at 91%"),
    # cache flush by operator
    (hms(18, 20, 14), 12, "WARN", "cache", "full cache flush requested by operator maint-ops-pk, reason=stale-catalog, 48211 keys removed"),
    # rate limit
    (hms(19, 45, 31), 820, "WARN", "api", "rate limit exceeded for tenant acme-logistics: 1200 req/min limit, observed 3350 req/min, throttling for 60 s"),
    # impossible travel
    (hms(21, 8, 40), 150, "INFO", "auth", "login ok user u-77120 from Lisbon (PT)"),
    (hms(21, 20, 52), 377, "WARN", "auth", "suspicious login for user u-77120 from Reykjavik (IS), 12 min after Lisbon (PT), step-up verification required"),
]

PATHS = ["/v1/orders", "/v1/orders/{id}", "/v1/cart", "/v1/cart/items", "/v1/products", "/v1/products/{id}",
         "/v1/search", "/v1/profile", "/v1/sessions", "/v1/invoices", "/v1/health", "/v1/shipping/rates",
         "/v1/inventory", "/v1/reviews"]
METHODS = ["GET", "GET", "GET", "POST", "PUT", "DELETE"]
KEYS = ["catalog", "session", "cart", "price", "rec", "geo", "inv"]
TABLES = ["orders", "carts", "products", "sessions", "users", "shipments", "reviews"]
JOBS = ["email-digest", "thumbnail-resize", "inventory-sync", "report-export", "search-reindex", "cleanup-temp"]
WORKERS = ["worker-emailer-1", "worker-emailer-3", "worker-media-1", "worker-media-2", "worker-sync-1"]


def noise_line(r, sec):
    ms = r.randrange(1000)
    comp = r.choices(["api", "auth", "db", "cache", "worker", "billing"], weights=[40, 10, 18, 14, 12, 6])[0]
    roll = r.random()
    rid = "req-%06x" % r.randrange(0x1000000)
    uid = "u-%04d" % r.randrange(1000, 10000)  # 4-digit ids; needle users have 5 digits
    if comp == "api":
        status = r.choices([200, 201, 204, 301, 400, 404, 429, 500, 502], weights=[70, 8, 4, 2, 5, 5, 1, 2, 1])[0]
        lat = int(r.lognormvariate(4.3, 0.7))
        lvl = "ERROR" if status >= 500 else ("WARN" if status >= 400 else ("DEBUG" if roll < 0.2 else "INFO"))
        msg = f"{rid} {r.choice(METHODS)} {r.choice(PATHS)} -> {status} in {lat} ms user={uid}"
        if status >= 500:
            msg += " upstream error"
    elif comp == "auth":
        if roll < 0.55:
            lvl, msg = "INFO", f"login ok user {uid} from 198.51.100.{r.randrange(1, 255)} {rid}"
        elif roll < 0.8:
            lvl, msg = "DEBUG", f"token refreshed user {uid} ttl=3600s"
        elif roll < 0.95:
            lvl, msg = "WARN", f"failed login for user {uid} from 192.0.2.{r.randrange(1, 255)} (attempt {r.randrange(1, 4)} of 7)"
        else:
            lvl, msg = "INFO", f"logout user {uid} {rid}"
    elif comp == "db":
        lat = int(r.lognormvariate(2.5, 0.8))
        if roll < 0.7:
            lvl, msg = "DEBUG", f"query on {r.choice(TABLES)} took {lat} ms rows={r.randrange(0, 400)}"
        elif roll < 0.9:
            lvl, msg = "INFO", f"pool stats active={r.randrange(2, 30)} idle={r.randrange(0, 20)} waiting={r.randrange(0, 3)}"
        else:
            lvl, msg = "WARN", f"query on {r.choice(TABLES)} took {r.randrange(1100, 3500)} ms (threshold 1000 ms)"
    elif comp == "cache":
        if roll < 0.6:
            lvl, msg = "DEBUG", f"hit key={r.choice(KEYS)}:{r.randrange(100000)}"
        elif roll < 0.9:
            lvl, msg = "DEBUG", f"miss key={r.choice(KEYS)}:{r.randrange(100000)}"
        else:
            lvl, msg = "INFO", f"evicted {r.randrange(5, 300)} entries from segment {r.randrange(8)}"
    elif comp == "worker":
        w = r.choice(WORKERS)
        if roll < 0.75:
            lvl, msg = "INFO", f"{w} finished job {r.choice(JOBS)} id={r.randrange(100000, 999999)} in {r.randrange(20, 4000)} ms"
        elif roll < 0.92:
            lvl, msg = "DEBUG", f"{w} polling queue depth={r.randrange(0, 60)}"
        else:
            lvl, msg = "WARN", f"{w} job {r.choice(JOBS)} retry {r.randrange(1, 3)} of 3 after timeout"
    else:
        if roll < 0.7:
            lvl, msg = "INFO", f"charge succeeded invoice=INV-2026-{r.randrange(10000, 80000)} amount={r.randrange(5, 900)}.{r.randrange(100):02d} USD"
        elif roll < 0.9:
            lvl, msg = "INFO", f"payout batch {r.randrange(1, 400)} settled items={r.randrange(3, 60)}"
        else:
            lvl, msg = "WARN", f"card declined for user {uid} invoice=INV-2026-{r.randrange(10000, 80000)}"
    return (sec, ms, lvl, comp, msg)


def main():
    r = random.Random(1234)
    rows = [noise_line(r, r.randrange(86400)) for _ in range(N_NOISE)]
    rows.extend(NEEDLES)
    rows.sort(key=lambda t: (t[0], t[1]))
    lines = [f"{ts(s, ms)} {lvl:<5} {comp:<7} {msg}" for s, ms, lvl, comp, msg in rows]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} lines to {OUT}")


if __name__ == "__main__":
    main()
