from pydoc import cli
from socket import timeout
import pytest
from cloudsdk.client import CloudError

def test_create_instance_starts_in_building(client):
    inst = client.create_instance("web_1")

    assert inst["status"] == "BUILDING"
    assert inst["id"].startswith("i-")
    assert inst["private_ip"] is None


def test_instance_becomes_active(client):
     inst = client.create_instance("web_1")
     ready = client.wait_for_status(client.get_instance, inst["id"], "ACTIVE",timeout = 5)
     assert ready["status"] == "ACTIVE"
     assert ready["private_ip"].startswith("10.0.0.")


@pytest.mark.parametrize("flavor,vcpus,ram_mb",
    [
        ("small", 1, 2048),
        ("medium", 2, 4096), 
        ("large", 4, 8192),

    ]
)
def test_flavor_shapes_are_correct(client, flavor, vcpus, ram_mb):
    inst = client.create_instance("vm",flavor = flavor)
    assert inst["vcpus"] == vcpus
    assert inst["ram_mb"] == ram_mb


@pytest.mark.parametrize("bad_flavor",["tiny","xxl","","SMALL"])
def test_invalid_flavor_is_rejected(client, bad_flavor):
    with pytest.raises(CloudError) as e:
        client.create_instance("bad-vm",flavor = bad_flavor)
    assert e.value.status ==400


def test_duplicate_name_conflicts(client):
    client.create_instance("dup")
    with pytest.raises(CloudError) as e:
        client.create_instance("dup")
    assert e.value.status == 409


def test_stop_then_start(client):
    inst = client.create_instance("web_1")
    client.wait_for_status(client.get_instance, inst["id"], "ACTIVE")
    assert client.instance_action(inst["id"], "stop")["status"] == "STOPPED"
    assert client.instance_action(inst["id"], "start")["status"] == "ACTIVE"


@pytest.mark.slow
def test_instance_quota_is_enforced(client):
    for n in range(10):
        client.create_instance("vm-%02d" % n)
    with pytest.raises(CloudError) as e:
        client.create_instance("vm-over")
    assert e.value.status == 403