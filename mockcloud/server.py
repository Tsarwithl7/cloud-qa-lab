"""
mockcloud — a fake OpenStack-style cloud platform, for QA practice.

Stateful REST API built on the stdlib http.server (no third-party deps needed
to RUN the platform itself). It deliberately mimics the behaviours a real cloud
control plane shows, so the tests you write against it look like real tests:

  - async provisioning:      create returns BUILDING, later flips to ACTIVE
  - state-machine rules:     can't stop a STOPPED vm, can't delete an in-use volume
  - input validation:        bad flavor / size / cidr  -> 400
  - not found:               unknown id                -> 404
  - conflict:                duplicate name / bad state-> 409
  - quota:                   too many instances        -> 403

Run standalone:   python -m mockcloud          # 127.0.0.1:8080
Env knobs:        MOCKCLOUD_PORT, MOCKCLOUD_BUILD_SECONDS, MOCKCLOUD_MAX_INSTANCES
"""
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DEFAULT_BUILD_SECONDS = float(os.environ.get("MOCKCLOUD_BUILD_SECONDS", "2"))
MAX_INSTANCES = int(os.environ.get("MOCKCLOUD_MAX_INSTANCES", "10"))

FLAVORS = {
    "small":  {"vcpus": 1, "ram_mb": 2048},
    "medium": {"vcpus": 2, "ram_mb": 4096},
    "large":  {"vcpus": 4, "ram_mb": 8192},
}
IMAGES = {"ubuntu-22.04", "centos-7", "debian-12"}
CIDR_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/(\d{1,2})$")
MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")

_lock = threading.Lock()


class State:
    """All platform state lives here, in memory. reset() gives a clean slate."""
    def __init__(self):
        self.instances = {}
        self.volumes = {}
        self.networks = {}
        self.nodes = {}          # bare-metal
        self._ip_counter = 10

    def next_ip(self):
        self._ip_counter += 1
        return "10.0.0.%d" % self._ip_counter

    def reset(self):
        self.instances.clear()
        self.volumes.clear()
        self.networks.clear()
        self.nodes.clear()
        self._ip_counter = 10


STATE = State()


class ApiError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


# ----------------------------------------------------------------------------
# resource logic  (the "rules" — what the platform allows / rejects)
# ----------------------------------------------------------------------------
def _public(obj):
    """Strip internal bookkeeping keys (those starting with '_')."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def _advance_instance(inst, build_seconds):
    if inst["status"] == "BUILDING" and time.time() >= inst["_active_at"]:
        inst["status"] = "ACTIVE"
        inst["private_ip"] = STATE.next_ip()


def _advance_node(node, build_seconds):
    if node["status"] in ("enrolling", "deploying") and time.time() >= node["_ready_at"]:
        node["status"] = "available" if node["status"] == "enrolling" else "active"


# ---- compute -----------------------------------------------------------------
def create_instance(body, build_seconds):
    name = body.get("name")
    flavor = body.get("flavor", "small")
    image = body.get("image", "ubuntu-22.04")
    if not name:
        raise ApiError(400, "field 'name' is required")
    if flavor not in FLAVORS:
        raise ApiError(400, "invalid flavor '%s' (valid: %s)" % (flavor, ",".join(FLAVORS)))
    if image not in IMAGES:
        raise ApiError(400, "invalid image '%s' (valid: %s)" % (image, ",".join(sorted(IMAGES))))
    if any(i["name"] == name for i in STATE.instances.values()):
        raise ApiError(409, "instance name '%s' already exists" % name)
    if len(STATE.instances) >= MAX_INSTANCES:
        raise ApiError(403, "instance quota exceeded (max %d)" % MAX_INSTANCES)
    iid = "i-" + uuid.uuid4().hex[:8]
    now = time.time()
    inst = {
        "id": iid, "name": name, "flavor": flavor, "image": image,
        "status": "BUILDING", "private_ip": None,
        "vcpus": FLAVORS[flavor]["vcpus"], "ram_mb": FLAVORS[flavor]["ram_mb"],
        "attached_volumes": [],
        "_active_at": now + build_seconds, "_created": now,
    }
    STATE.instances[iid] = inst
    return 202, _public(inst)


def get_instance(iid, build_seconds):
    inst = STATE.instances.get(iid)
    if not inst:
        raise ApiError(404, "instance '%s' not found" % iid)
    _advance_instance(inst, build_seconds)
    return 200, _public(inst)


def list_instances(build_seconds):
    for inst in STATE.instances.values():
        _advance_instance(inst, build_seconds)
    return 200, {"instances": [_public(i) for i in STATE.instances.values()]}


def instance_action(iid, body, build_seconds):
    inst = STATE.instances.get(iid)
    if not inst:
        raise ApiError(404, "instance '%s' not found" % iid)
    _advance_instance(inst, build_seconds)
    action = body.get("action")
    valid = {"start", "stop", "reboot"}
    if action not in valid:
        raise ApiError(400, "invalid action '%s' (valid: %s)" % (action, ",".join(sorted(valid))))
    st = inst["status"]
    if action == "stop":
        if st != "ACTIVE":
            raise ApiError(409, "cannot stop instance in status %s" % st)
        inst["status"] = "STOPPED"
    elif action == "start":
        if st != "STOPPED":
            raise ApiError(409, "cannot start instance in status %s" % st)
        inst["status"] = "ACTIVE"
    elif action == "reboot":
        if st != "ACTIVE":
            raise ApiError(409, "cannot reboot instance in status %s" % st)
        inst["status"] = "ACTIVE"
    return 200, _public(inst)


def delete_instance(iid):
    inst = STATE.instances.get(iid)
    if not inst:
        raise ApiError(404, "instance '%s' not found" % iid)
    if inst["attached_volumes"]:
        raise ApiError(409, "instance has attached volumes %s; detach first"
                       % inst["attached_volumes"])
    del STATE.instances[iid]
    return 204, None


def ping_from_instance(iid, target, build_seconds):
    inst = STATE.instances.get(iid)
    if not inst:
        raise ApiError(404, "instance '%s' not found" % iid)
    _advance_instance(inst, build_seconds)
    if inst["status"] != "ACTIVE":
        raise ApiError(409, "source instance is %s, must be ACTIVE to ping" % inst["status"])
    if not target:
        raise ApiError(400, "query param 'target' is required")
    active_ips = {i["private_ip"] for i in STATE.instances.values() if i["status"] == "ACTIVE"}
    reachable = target in active_ips
    return 200, {"source": inst["private_ip"], "target": target,
                 "reachable": reachable,
                 "latency_ms": 0.4 if reachable else None,
                 "packet_loss_pct": 0 if reachable else 100}


# ---- volume (云存储 / 云内存) ------------------------------------------------
def create_volume(body):
    name = body.get("name")
    size = body.get("size_gb")
    if not name:
        raise ApiError(400, "field 'name' is required")
    if not isinstance(size, int) or isinstance(size, bool):
        raise ApiError(400, "field 'size_gb' must be an integer")
    if not (1 <= size <= 1024):
        raise ApiError(400, "size_gb must be between 1 and 1024")
    if any(v["name"] == name for v in STATE.volumes.values()):
        raise ApiError(409, "volume name '%s' already exists" % name)
    vid = "vol-" + uuid.uuid4().hex[:8]
    vol = {"id": vid, "name": name, "size_gb": size,
           "status": "available", "attached_to": None}
    STATE.volumes[vid] = vol
    return 202, _public(vol)


def get_volume(vid):
    vol = STATE.volumes.get(vid)
    if not vol:
        raise ApiError(404, "volume '%s' not found" % vid)
    return 200, _public(vol)


def volume_action(vid, body, build_seconds):
    vol = STATE.volumes.get(vid)
    if not vol:
        raise ApiError(404, "volume '%s' not found" % vid)
    action = body.get("action")
    if action == "attach":
        instance_id = body.get("instance_id")
        inst = STATE.instances.get(instance_id)
        if not inst:
            raise ApiError(404, "instance '%s' not found" % instance_id)
        _advance_instance(inst, build_seconds)
        if vol["status"] != "available":
            raise ApiError(409, "volume is %s, must be 'available' to attach" % vol["status"])
        if inst["status"] != "ACTIVE":
            raise ApiError(409, "instance is %s, must be ACTIVE to attach a volume" % inst["status"])
        vol["status"] = "in-use"
        vol["attached_to"] = instance_id
        inst["attached_volumes"].append(vid)
    elif action == "detach":
        if vol["status"] != "in-use":
            raise ApiError(409, "volume is %s, nothing to detach" % vol["status"])
        inst = STATE.instances.get(vol["attached_to"])
        if inst and vid in inst["attached_volumes"]:
            inst["attached_volumes"].remove(vid)
        vol["status"] = "available"
        vol["attached_to"] = None
    else:
        raise ApiError(400, "invalid action '%s' (valid: attach,detach)" % action)
    return 200, _public(vol)


def delete_volume(vid):
    vol = STATE.volumes.get(vid)
    if not vol:
        raise ApiError(404, "volume '%s' not found" % vid)
    if vol["status"] == "in-use":
        raise ApiError(409, "volume is in-use by %s; detach first" % vol["attached_to"])
    del STATE.volumes[vid]
    return 204, None


# ---- network (云网络) --------------------------------------------------------
def create_network(body):
    name = body.get("name")
    cidr = body.get("cidr")
    if not name:
        raise ApiError(400, "field 'name' is required")
    if not cidr or not CIDR_RE.match(cidr):
        raise ApiError(400, "invalid cidr '%s' (expected e.g. 10.0.0.0/24)" % cidr)
    octets = CIDR_RE.match(cidr).groups()
    if any(int(o) > 255 for o in octets[:4]) or int(octets[4]) > 32:
        raise ApiError(400, "cidr octets out of range")
    nid = "net-" + uuid.uuid4().hex[:8]
    net = {"id": nid, "name": name, "cidr": cidr, "status": "ACTIVE"}
    STATE.networks[nid] = net
    return 201, _public(net)


def list_networks():
    return 200, {"networks": [_public(n) for n in STATE.networks.values()]}


# ---- bare metal (裸金属) -----------------------------------------------------
def enroll_node(body, build_seconds):
    name = body.get("name")
    mac = body.get("mac")
    if not name:
        raise ApiError(400, "field 'name' is required")
    if not mac or not MAC_RE.match(mac):
        raise ApiError(400, "invalid mac '%s' (expected aa:bb:cc:dd:ee:ff)" % mac)
    nid = "bm-" + uuid.uuid4().hex[:8]
    node = {"id": nid, "name": name, "mac": mac, "status": "enrolling",
            "image": None, "_ready_at": time.time() + build_seconds}
    STATE.nodes[nid] = node
    return 202, _public(node)


def get_node(nid, build_seconds):
    node = STATE.nodes.get(nid)
    if not node:
        raise ApiError(404, "bare-metal node '%s' not found" % nid)
    _advance_node(node, build_seconds)
    return 200, _public(node)


def provision_node(nid, body, build_seconds):
    node = STATE.nodes.get(nid)
    if not node:
        raise ApiError(404, "bare-metal node '%s' not found" % nid)
    _advance_node(node, build_seconds)
    image = body.get("image")
    if image not in IMAGES:
        raise ApiError(400, "invalid image '%s'" % image)
    if node["status"] != "available":
        raise ApiError(409, "node is %s, must be 'available' to provision" % node["status"])
    node["status"] = "deploying"
    node["image"] = image
    node["_ready_at"] = time.time() + build_seconds
    return 202, _public(node)


# ----------------------------------------------------------------------------
# HTTP layer  (routing)
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "mockcloud/1.0"

    # keep the test output clean
    def log_message(self, *args):
        pass

    @property
    def build_seconds(self):
        return getattr(self.server, "build_seconds", DEFAULT_BUILD_SECONDS)

    def _send(self, status, payload):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ApiError(400, "request body is not valid JSON")

    def _dispatch(self, method):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)
        with _lock:
            body = self._read_json() if method in ("POST", "PUT") else {}

            # health / ping
            if method == "GET" and path in ("/", "/healthz"):
                return 200, {"service": "mockcloud", "version": "1.0", "status": "ok"}
            if method == "POST" and path == "/admin/reset":
                STATE.reset()
                return 200, {"status": "reset"}

            # compute
            if method == "POST" and path == "/v1/instances":
                return create_instance(body, self.build_seconds)
            if method == "GET" and path == "/v1/instances":
                return list_instances(self.build_seconds)
            m = re.match(r"^/v1/instances/([^/]+)$", path)
            if m and method == "GET":
                return get_instance(m.group(1), self.build_seconds)
            if m and method == "DELETE":
                return delete_instance(m.group(1))
            m = re.match(r"^/v1/instances/([^/]+)/action$", path)
            if m and method == "POST":
                return instance_action(m.group(1), body, self.build_seconds)
            m = re.match(r"^/v1/instances/([^/]+)/ping$", path)
            if m and method == "GET":
                return ping_from_instance(m.group(1), (qs.get("target") or [None])[0], self.build_seconds)

            # volumes
            if method == "POST" and path == "/v1/volumes":
                return create_volume(body)
            m = re.match(r"^/v1/volumes/([^/]+)$", path)
            if m and method == "GET":
                return get_volume(m.group(1))
            if m and method == "DELETE":
                return delete_volume(m.group(1))
            m = re.match(r"^/v1/volumes/([^/]+)/action$", path)
            if m and method == "POST":
                return volume_action(m.group(1), body, self.build_seconds)

            # networks
            if method == "POST" and path == "/v1/networks":
                return create_network(body)
            if method == "GET" and path == "/v1/networks":
                return list_networks()

            # bare metal
            if method == "POST" and path == "/v1/baremetal/nodes":
                return enroll_node(body, self.build_seconds)
            m = re.match(r"^/v1/baremetal/nodes/([^/]+)$", path)
            if m and method == "GET":
                return get_node(m.group(1), self.build_seconds)
            m = re.match(r"^/v1/baremetal/nodes/([^/]+)/provision$", path)
            if m and method == "POST":
                return provision_node(m.group(1), body, self.build_seconds)

            raise ApiError(404, "no route for %s %s" % (method, path))

    def _handle(self, method):
        try:
            status, payload = self._dispatch(method)
            self._send(status, payload)
        except ApiError as e:
            self._send(e.status, {"error": {"code": e.status, "message": e.message}})
        except Exception as e:  # noqa: BLE001 - platform must never crash mid-request
            self._send(500, {"error": {"code": 500, "message": "internal error: %s" % e}})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")


def make_server(port=8080, build_seconds=DEFAULT_BUILD_SECONDS):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.build_seconds = build_seconds
    return httpd
