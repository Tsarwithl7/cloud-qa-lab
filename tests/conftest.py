"""
Shared PyTest fixtures.

Design decision worth being able to explain in an interview:
  - If CLOUD_URL is set, tests run against an EXTERNAL platform you started
    (`python -m mockcloud`) — this is the "integration / e2e against a real
    environment" mode.
  - Otherwise we spin the platform up IN-PROCESS on a random free port. This
    keeps the suite hermetic and fast (no ports to manage, nothing to clean up
    between runs), which is what you want for CI.

  - `base_url` is session-scoped: one platform for the whole run.
  - `client` is function-scoped and RESETS platform state before each test, so
    tests are independent and order doesn't matter (no shared-state flakiness).
"""
import os
import threading

import pytest

from cloudsdk.client import CloudClient
from mockcloud.server import make_server


@pytest.fixture(scope="session")
def base_url():
    external = os.environ.get("CLOUD_URL")
    if external:
        yield external.rstrip("/")
        return
    # hermetic in-process platform; build fast so the suite stays quick
    httpd = make_server(port=0, build_seconds=0.5)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % port
    httpd.shutdown()


@pytest.fixture
def client(base_url):
    c = CloudClient(base_url)
    c.reset()  # clean slate per test -> tests are independent
    return c
