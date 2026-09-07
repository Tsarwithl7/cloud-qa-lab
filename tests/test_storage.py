import pytest
from cloudsdk.client import CloudError

def test_attach_volume_to_active_instance(client):
    inst = client.create_instance("web-01")
    client.wait_for_status(client.get_instance, inst["id"], "ACTIVE")
    vol = client.create_volume("data-01", 50)
    result = client.attach_volume(vol["id"], inst["id"])
    assert result["status"] == "in-use"
    assert result["attached_to"] == inst["id"]


def test_cannot_delete_in_use_volume(client):
    inst = client.create_instance("web-01")
    client.wait_for_status(client.get_instance, inst["id"], "ACTIVE")
    vol = client.create_volume("data-01", 50)
    client.attach_volume(vol["id"], inst["id"])
    with pytest.raises(CloudError) as e:
        client.delete_volume(vol["id"])
    assert e.value.status == 409    