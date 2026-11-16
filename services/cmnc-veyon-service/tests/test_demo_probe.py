import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from cmnc_veyon_service.demo_probe import accept_probe, probe_recipients, probe_script
from cmnc_veyon_service.main import Target


def test_probe_only_tests_fixed_authenticated_source_and_encodes_callback():
    source_token = 'a' * 64
    script = probe_script('192.168.1.10', source_token, "https://cmnc.example/probe?value='quoted'", 'probe-token' * 4)
    assert "ConnectAsync('192.168.1.10', 11400)" in script
    assert 'Authentication failed' in script and 'Read-Exact 24' in script
    assert "?value='quoted'" not in script and '__SOURCE_' not in script
    assert 'Invoke-Expression' not in script and 'ScriptBlock' not in script
    assert base64.b64encode(b"https://cmnc.example/probe?value='quoted'").decode() in script
    with pytest.raises(ValueError): probe_script("192.168.1.1'; evil", source_token, 'https://cmnc', 'x' * 32)
    with pytest.raises(ValueError): probe_script('192.168.1.1', "'" * 64, 'https://cmnc', 'x' * 32)


def test_probe_results_are_bound_to_target_token_and_single_use():
    session = SimpleNamespace(probe_tokens={2: 'a' * 32}, probe_results={}, stopping=False)
    for device_id, token in [(3, 'a' * 32), (2, 'b' * 32)]:
        with pytest.raises(HTTPException): accept_probe(session, device_id, token, True)
    accept_probe(session, 2, 'a' * 32, True)
    assert session.probe_results == {2: True}
    with pytest.raises(HTTPException): accept_probe(session, 2, 'a' * 32, False)
    session.stopping = True
    with pytest.raises(HTTPException): accept_probe(session, 2, 'a' * 32, True)


def test_fixed_probes_run_hidden_and_only_verified_results_are_selected():
    async def run():
        targets = [Target(device_id=i, classroom_id=1, router_id=1, host=f'192.168.1.{i}') for i in (2, 3)]
        session = SimpleNamespace(id='session-id', source=Target(device_id=1, classroom_id=1, router_id=1, host='192.168.1.1'),
            source_token='a' * 64, targets=targets, probe_tokens={}, probe_results={}, stopping=False, changed=asyncio.Condition())
        async def operate(target, action, arguments):
            assert action == 'command'
            command = arguments['applications'][0]
            assert '-WindowStyle Hidden' in command
            script = base64.b64decode(command.split('-EncodedCommand ')[1]).decode('utf-16-le')
            assert "ConnectAsync('192.168.1.1', 11400)" in script
            assert session.probe_tokens[target.device_id] in script
            async with session.changed:
                accept_probe(session, target.device_id, session.probe_tokens[target.device_id], target.device_id == 2)
                session.changed.notify_all()
        bridge = SimpleNamespace(operate=AsyncMock(side_effect=operate))
        assert await probe_recipients(bridge, session, 'https://cmnc.example.local') == {2}
        assert not session.probe_tokens and bridge.operate.await_count == 2
    asyncio.run(run())


@pytest.mark.parametrize('valid_token', [True, False])
def test_powershell_probe_reports_authenticated_connection_not_just_open_port(valid_token):
    import json
    import shutil
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from cmnc_veyon_service.demo_relay import DemoRelay
    executable = shutil.which('powershell.exe')
    if executable is None:
        pytest.skip('Windows PowerShell is required for the executable probe test')
    async def run():
        received = []
        class Callback(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.headers.get('Authorization'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            def log_message(self, *args): pass
        callback = ThreadingHTTPServer(('127.0.0.1', 0), Callback)
        thread = threading.Thread(target=callback.serve_forever, daemon=True); thread.start()
        session = SimpleNamespace(id='test', token='a' * 64, source=None, stopping=False, frame_size=(1920, 1080))
        relay = DemoRelay({'test': session}); await relay.start(0)
        port = relay.server.sockets[0].getsockname()[1]
        try:
            script = probe_script('127.0.0.1', ('a' if valid_token else 'b') * 64,
                f'http://127.0.0.1:{callback.server_port}/probe', 'probe-token' * 4)
            script = script.replace("ConnectAsync('127.0.0.1', 11400)", f"ConnectAsync('127.0.0.1', {port})")
            encoded = base64.b64encode(script.encode('utf-16-le')).decode()
            process = await asyncio.create_subprocess_exec(executable, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            async with asyncio.timeout(25):
                await process.communicate()
            assert received == [('Bearer ' + 'probe-token' * 4, {'reachable': valid_token})]
        finally:
            await relay.close()
            await asyncio.to_thread(callback.shutdown)
            callback.server_close(); thread.join(timeout=2)
    asyncio.run(run())
