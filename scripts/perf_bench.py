#!/usr/bin/env python3
"""
Performance benchmark — measures API response latency and throughput.
Run after deploy to establish a baseline, or to catch regressions.

Exit codes:
  0  all metrics within threshold
  1  one or more metrics exceeded threshold
"""
import sys
import os
import time
import statistics
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cloudsdk.client import CloudClient, CloudError

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("perf_bench")

THRESHOLDS_MS = {
    "health":          50,
    "create_instance": 200,
    "get_instance":    100,
    "list_instances":  150,
}


def measure(label, fn, iterations=10):
    samples = []
    errors = 0
    for _ in range(iterations):
        try:
            start = time.perf_counter()
            fn()
            elapsed_ms = (time.perf_counter() - start) * 1000
            samples.append(elapsed_ms)
        except CloudError as e:
            errors += 1
            log.warning("%s returned error: %s", label, e)

    if not samples:
        log.error("%s  — all %d calls failed", label, errors)
        return None

    result = {
        "label":    label,
        "n":        len(samples),
        "errors":   errors,
        "min_ms":   min(samples),
        "max_ms":   max(samples),
        "mean_ms":  statistics.mean(samples),
        "p95_ms":   sorted(samples)[int(len(samples) * 0.95)],
    }
    return result

def print_report(results, thresholds):
    failures = 0
    log.info("%-20s  %6s  %6s  %6s  %6s  %s",
             "operation", "mean", "p95", "min", "max", "status")
    log.info("-" * 65)
    for r in results:
        if r is None:
            failures += 1
            continue
        threshold = thresholds.get(r["label"])
        over = threshold and r["p95_ms"] > threshold
        status = "FAIL (p95 > %dms)" % threshold if over else "OK"
        if over:
            failures += 1
        log.info("%-20s  %5.1fms  %5.1fms  %5.1fms  %5.1fms  %s",
                 r["label"], r["mean_ms"], r["p95_ms"],
                 r["min_ms"], r["max_ms"], status)
    return failures


def main():
    parser = argparse.ArgumentParser(description="mockcloud perf benchmark")
    parser.add_argument("--url", default=None)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()

    client = CloudClient(base_url=args.url)
    client.reset()

    log.info("=== perf benchmark started (iterations=%d) ===", args.iterations)

    results = [
        measure("health",          lambda: client.health(),               args.iterations),
        measure("create_instance", lambda: client.create_instance("perf-vm"), args.iterations),
        measure("list_instances",  lambda: client.list_instances(),        args.iterations),
    ]

    failures = print_report(results, THRESHOLDS_MS)
    log.info("=== done  |  threshold breaches: %d ===", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
