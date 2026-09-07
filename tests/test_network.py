import pytest
from cloudsdk.client import CloudError


def test_create_network(client):
    net = client.create_network("prod-net","10.0.0.0/24")
    assert net["status"] == "ACTIVE"
    assert net["cidr"]== "10.0.0.0/24"

def test_invalid_cidr_is_rejected(client):
    with pytest.raises(CloudError) as e:
        client.create_network("bad-net","999.999.999.999/99")
    assert e.value.status == 400

def test_enroll_baremetal_node(client):
    node = client.enroll_node("bm-01", "aa:bb:cc:dd:ee:01")
    assert node["status"] == "enrolling"
    assert node["mac"] == "aa:bb:cc:dd:ee:01"

def test_invalid_mac_is_rejected(client):
    with pytest.raises(CloudError) as e:
        client.enroll_node("bm-bad", "not-a-mac")
    assert e.value.status == 400


def test_baremetal_full_lifecycle(client):
      # 注册 → 等 available → 部署镜像 → 等 active
      node = client.enroll_node("bm-01", "aa:bb:cc:dd:ee:01")
      assert node["status"] == "enrolling"

      client.wait_for_status(client.get_node, node["id"],"available")
      deployed = client.provision_node(node["id"], "ubuntu-22.04")
      assert deployed["status"] == "deploying"
      assert deployed["image"] == "ubuntu-22.04"

      final = client.wait_for_status(client.get_node, node["id"], "active")
      assert final["status"] == "active"

def test_cannot_provision_while_enrolling(client):
    # 节点还没 available 就部署，应该被拒
    node = client.enroll_node("bm-02", "aa:bb:cc:dd:ee:02")
    with pytest.raises(CloudError) as e:
        client.provision_node(node["id"], "ubuntu-22.04")
    assert e.value.status == 409

