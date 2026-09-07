"""
cloudsdk — a thin Python client for the mockcloud platform.

This is the "SDK" your tests and scripts call. It wraps HTTP with friendly
methods and raises CloudError on any 4xx/5xx so tests can assert on failures.
"""
import os
import time

import requests


class CloudError(Exception):
    """Raised on any non-2xx response. Carries .status and .body."""
    def __init__(self, status, body):
        self.status = status
        self.body = body
        msg = body.get("error", {}).get("message") if isinstance(body, dict) else body
        super().__init__("HTTP %s: %s" % (status, msg))


def _json(resp):
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


class CloudClient:
    def __init__(self, base_url=None, timeout=5):
        self.base_url = (base_url or os.environ.get("CLOUD_URL", "http://127.0.0.1:8080")).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _req(self, method, path, **kw):
        resp = self.session.request(method, self.base_url + path, timeout=self.timeout, **kw)
        body = _json(resp)
        if resp.status_code >= 400:
            raise CloudError(resp.status_code, body)
        return body

    # --- platform ---
    def health(self):
        return self._req("GET", "/healthz")

    def reset(self):
        """Wipe platform state — used by tests to start from a clean slate."""
        return self._req("POST", "/admin/reset")

    # --- compute (云主机) ---
    def create_instance(self, name, flavor="small", image="ubuntu-22.04"):
        return self._req("POST", "/v1/instances",
                         json={"name": name, "flavor": flavor, "image": image})

    def get_instance(self, iid):
        return self._req("GET", "/v1/instances/%s" % iid)

    def list_instances(self):
        return self._req("GET", "/v1/instances")["instances"]

    def instance_action(self, iid, action):
        return self._req("POST", "/v1/instances/%s/action" % iid, json={"action": action})

    def delete_instance(self, iid):
        return self._req("DELETE", "/v1/instances/%s" % iid)

    def ping(self, iid, target):
        return self._req("GET", "/v1/instances/%s/ping" % iid, params={"target": target})

    # --- volume (云存储) ---
    def create_volume(self, name, size_gb):
        return self._req("POST", "/v1/volumes", json={"name": name, "size_gb": size_gb})

    def get_volume(self, vid):
        return self._req("GET", "/v1/volumes/%s" % vid)

    def attach_volume(self, vid, instance_id):
        return self._req("POST", "/v1/volumes/%s/action" % vid,
                         json={"action": "attach", "instance_id": instance_id})

    def detach_volume(self, vid):
        return self._req("POST", "/v1/volumes/%s/action" % vid, json={"action": "detach"})

    def delete_volume(self, vid):
        return self._req("DELETE", "/v1/volumes/%s" % vid)

    # --- network (云网络) ---
    def create_network(self, name, cidr):
        return self._req("POST", "/v1/networks", json={"name": name, "cidr": cidr})

    def list_networks(self):
        return self._req("GET", "/v1/networks")["networks"]

    # --- bare metal (裸金属) ---
    def enroll_node(self, name, mac):
        return self._req("POST", "/v1/baremetal/nodes", json={"name": name, "mac": mac})

    def get_node(self, nid):
        return self._req("GET", "/v1/baremetal/nodes/%s" % nid)

    def provision_node(self, nid, image):
        return self._req("POST", "/v1/baremetal/nodes/%s/provision" % nid, json={"image": image})

    # --- the waiter pattern: poll until a resource reaches a status ---
    def wait_for_status(self, getter, iid, target, timeout=10, interval=0.3):
        """Poll getter(iid) until status == target, or raise TimeoutError.

        This is THE core helper in cloud testing: provisioning is async, so you
        never assert on the create response — you poll until the resource
        settles, with a timeout so a stuck resource fails the test instead of
        hanging forever.
        """
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = getter(iid)
            if last["status"] == target:
                return last
            time.sleep(interval)
        raise TimeoutError("%s did not reach %s within %ss (last status=%s)"
                           % (iid, target, timeout, last and last.get("status")))
