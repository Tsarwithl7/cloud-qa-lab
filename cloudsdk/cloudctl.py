"""
cloudctl — a command-line console for the mockcloud platform.

This is what you'd type at a terminal to poke the platform by hand, the same
way you'd use `openstack`, `aws`, or an internal `xxxctl` tool on the job.

Examples:
    python -m cloudsdk.cloudctl health
    python -m cloudsdk.cloudctl instance create web-01 --flavor medium
    python -m cloudsdk.cloudctl instance list
    python -m cloudsdk.cloudctl instance show i-abcd1234
    python -m cloudsdk.cloudctl instance action i-abcd1234 stop
    python -m cloudsdk.cloudctl instance delete i-abcd1234
    python -m cloudsdk.cloudctl volume create data-01 --size 20
    python -m cloudsdk.cloudctl volume attach vol-xxx i-abcd1234
"""
import argparse
import json
import sys

from .client import CloudClient, CloudError


def out(obj):
    print(json.dumps(obj, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="cloudctl", description="console for mockcloud")
    p.add_argument("--url", default=None, help="platform base url (default $CLOUD_URL or :8080)")
    sub = p.add_subparsers(dest="group", required=True)

    sub.add_parser("health")

    inst = sub.add_parser("instance").add_subparsers(dest="cmd", required=True)
    c = inst.add_parser("create"); c.add_argument("name")
    c.add_argument("--flavor", default="small"); c.add_argument("--image", default="ubuntu-22.04")
    inst.add_parser("list")
    inst.add_parser("show").add_argument("id")
    a = inst.add_parser("action"); a.add_argument("id"); a.add_argument("action", choices=["start", "stop", "reboot"])
    inst.add_parser("delete").add_argument("id")
    pg = inst.add_parser("ping"); pg.add_argument("id"); pg.add_argument("target")

    vol = sub.add_parser("volume").add_subparsers(dest="cmd", required=True)
    vc = vol.add_parser("create"); vc.add_argument("name"); vc.add_argument("--size", type=int, required=True)
    vol.add_parser("show").add_argument("id")
    va = vol.add_parser("attach"); va.add_argument("id"); va.add_argument("instance_id")
    vol.add_parser("detach").add_argument("id")
    vol.add_parser("delete").add_argument("id")

    net = sub.add_parser("network").add_subparsers(dest="cmd", required=True)
    nc = net.add_parser("create"); nc.add_argument("name"); nc.add_argument("--cidr", required=True)
    net.add_parser("list")

    bm = sub.add_parser("baremetal").add_subparsers(dest="cmd", required=True)
    bc = bm.add_parser("enroll"); bc.add_argument("name"); bc.add_argument("--mac", required=True)
    bm.add_parser("show").add_argument("id")
    bp = bm.add_parser("provision"); bp.add_argument("id"); bp.add_argument("--image", required=True)

    args = p.parse_args(argv)
    client = CloudClient(args.url)

    try:
        if args.group == "health":
            out(client.health())
        elif args.group == "instance":
            if args.cmd == "create":
                out(client.create_instance(args.name, args.flavor, args.image))
            elif args.cmd == "list":
                out(client.list_instances())
            elif args.cmd == "show":
                out(client.get_instance(args.id))
            elif args.cmd == "action":
                out(client.instance_action(args.id, args.action))
            elif args.cmd == "delete":
                client.delete_instance(args.id); out({"deleted": args.id})
            elif args.cmd == "ping":
                out(client.ping(args.id, args.target))
        elif args.group == "volume":
            if args.cmd == "create":
                out(client.create_volume(args.name, args.size))
            elif args.cmd == "show":
                out(client.get_volume(args.id))
            elif args.cmd == "attach":
                out(client.attach_volume(args.id, args.instance_id))
            elif args.cmd == "detach":
                out(client.detach_volume(args.id))
            elif args.cmd == "delete":
                client.delete_volume(args.id); out({"deleted": args.id})
        elif args.group == "network":
            if args.cmd == "create":
                out(client.create_network(args.name, args.cidr))
            elif args.cmd == "list":
                out(client.list_networks())
        elif args.group == "baremetal":
            if args.cmd == "enroll":
                out(client.enroll_node(args.name, args.mac))
            elif args.cmd == "show":
                out(client.get_node(args.id))
            elif args.cmd == "provision":
                out(client.provision_node(args.id, args.image))
    except CloudError as e:
        # mirror how real CLIs behave: print the error, exit non-zero
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
