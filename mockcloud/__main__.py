"""Entry point: `python -m mockcloud` starts the fake platform."""
import os

from .server import make_server, DEFAULT_BUILD_SECONDS

if __name__ == "__main__":
    port = int(os.environ.get("MOCKCLOUD_PORT", "8080"))
    httpd = make_server(port)
    print("mockcloud listening on http://127.0.0.1:%d  (build_seconds=%s)"
          % (port, DEFAULT_BUILD_SECONDS))
    print("health:  curl http://127.0.0.1:%d/healthz" % port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        httpd.shutdown()
