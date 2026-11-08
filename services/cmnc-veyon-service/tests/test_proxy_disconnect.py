"""Opt-in native regression: CMNC_TEST_VEYON_PROXY_IMAGE=<built proxy image>."""
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.mark.skipif(not os.environ.get("CMNC_TEST_VEYON_PROXY_IMAGE"), reason="requires a built Veyon proxy image and Docker")
def test_proxy_survives_clients_disconnecting_during_authentication():
    image = os.environ["CMNC_TEST_VEYON_PROXY_IMAGE"]
    count = int(os.environ.get("CMNC_TEST_VEYON_DISCONNECT_CLIENTS", "100"))
    name = "cmnc-disconnect-test-" + uuid.uuid4().hex[:12]

    def docker(*args):
        return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.STDOUT).strip()

    def probe(port):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/feature", timeout=2) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            exc.close()
            return exc.code

    # An ephemeral test key and a closed port inside this isolated container;
    # no real computers or installed authentication keys are accessed.
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    body = json.dumps({"method": "0c69b301-81b4-42d6-8fae-128cdd113314", "credentials": {"keyname": "TEST", "keydata": pem}}).encode()
    request = (b"POST /api/v1/authentication/127.0.0.1:11999 HTTP/1.1\r\nHost: localhost\r\n"
               b"Content-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    try:
        docker("run", "-d", "--name", name, "-p", "127.0.0.1::11080", image)
        port = int(docker("port", name, "11080/tcp").rsplit(":", 1)[1])
        for _ in range(50):
            try:
                if probe(port) == 401:
                    break
            except OSError:
                pass
            time.sleep(.1)
        else:
            pytest.fail("Proxy did not start: " + docker("logs", name))
        sockets = []
        try:
            for _ in range(count):
                client = socket.create_connection(("127.0.0.1", port), timeout=5)
                sockets.append(client)
                client.sendall(request)
            time.sleep(.2)
        finally:
            for client in sockets:
                client.close()
        # Let the asynchronous authentication responses complete after clients
        # have gone away. The unpatched Qt library segfaults at this point.
        time.sleep(18)
        logs = docker("logs", name)
        assert docker("inspect", "--format", "{{.State.Running}}", name) == "true", logs
        assert "waiting for authentication methods timed out" in logs, logs
        assert "Received signal" not in logs, logs
        assert probe(port) == 401
    finally:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
