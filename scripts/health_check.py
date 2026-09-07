#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
Platform health check — run this on a cron or after deploy to verify
the control plane is responding and resources are in expected states.

Exit codes:
  0  all checks passed
  1  one or more checks failed
"""
import argparse
import logging
import sys
import time


from cloudsdk.client import CloudClient, CloudError

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("health_check")



def check_platform(client):
    log.info("checking platform health endpoint")
    resp = client.health()
    assert resp["status"] == "ok", "unexpected status: %s" % resp["status"]
    log.info("platform OK  (version=%s)", resp["version"])

def check_instances(client):
    log.info("listing instances...")
    instances = client.list_instances()
    log.info("found %d instance(s)", len(instances))
    for inst in instances:
        if inst["status"] not in ("ACTIVE", "STOPPED", "BUILDING"):
            log.warning("instance %s is in unexpected status: %s",
                        inst["id"], inst["status"])
    return instances    

def check_volumes(client):
    log.info("listing volumes...")
    # mockcloud has no list_volumes endpoint, so we skip silently
    log.info("volume check skipped (no list endpoint on this platform)")



def run_checks(client):
    failures = 0
    checks = [check_platform, check_instances, check_volumes]
    for check in checks:
        try:
            check(client)
        except (CloudError, AssertionError, Exception) as e:
            log.error("FAIL  %s: %s", check.__name__, e)
            failures += 1
    return failures


def main():
    parser = argparse.ArgumentParser(description="mockcloud health check")
    parser.add_argument("--url", default=None, help="platform base URL")
    parser.add_argument("--timeout", type=int, default=5,
                        help="request timeout in seconds")
    args = parser.parse_args()

    client = CloudClient(base_url=args.url, timeout=args.timeout)

    log.info("=== health check started ===")
    start = time.perf_counter()
    failures = run_checks(client)
    elapsed = time.perf_counter() - start

    log.info("=== completed in %.2fs  |  failures: %d ===", elapsed, failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()    