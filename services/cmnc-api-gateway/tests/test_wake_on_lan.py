import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from cmnc_api_gateway import main
from cmnc_api_gateway import wake_on_lan as wol
from cmnc_api_gateway.schemas import PrincipalResponse


ROUTER = {'id': 42, 'api_host': 'router.test', 'api_port': 443, 'api_use_ssl': True,
          'api_username': 'test', 'api_password': 'password', 'api_verify_tls': True}
CLASSROOM = {'id': 7, 'router_id': 42, 'subnet_cidr': '192.168.7.0/24'}
DEVICE = {'id': 10, 'mac_address': '00:11:22:33:44:55', 'online': True, 'wan_protected': True}


def test_selects_correct_vlan_and_rejects_missing_or_ambiguous_interface():
    addresses = [{'address': '192.168.0.1/16', 'interface': 'bridge'},
                 {'address': '192.168.7.1/24', 'interface': 'vlan7'},
                 {'address': '192.168.7.2/24', 'interface': 'wrong', 'disabled': 'true'}]
    assert wol.select_wol_interface(addresses, CLASSROOM['subnet_cidr']) == 'vlan7'
    with pytest.raises(HTTPException, match='интерфейс'):
        wol.select_wol_interface([], CLASSROOM['subnet_cidr'])
    with pytest.raises(HTTPException, match='несколько'):
        wol.select_wol_interface(addresses + [{'address': '192.168.7.3/24', 'interface': 'other'}], CLASSROOM['subnet_cidr'])


def test_sends_correct_mac_and_interface_with_partial_failure(monkeypatch):
    calls = []
    def handle(request):
        assert request.headers['authorization'].startswith('Basic ')
        if request.url.path.endswith('/ip/address'):
            return httpx.Response(200, json=[{'address': '192.168.7.1/24', 'interface': 'vlan7'}])
        assert request.url.path == '/rest/tool/wol'
        payload = json.loads(request.content)
        assert payload['interface'] == 'vlan7'
        calls.append(payload['mac'])
        return httpx.Response(403, json={'error': 403}) if payload['mac'].endswith('66') else httpx.Response(200, json=[])
    original = httpx.AsyncClient
    monkeypatch.setattr(wol.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    devices = [DEVICE, {**DEVICE, 'id': 11}, {'id': 12, 'mac_address': '00:11:22:33:44:66'}, {'id': 13, 'mac_address': 'bad'}]
    result = asyncio.run(wol.send_wol_packets(ROUTER, 'https://router.test/rest', CLASSROOM['subnet_cidr'], devices))
    assert result['sent_count'] == 1
    assert result['failed_count'] == 2
    assert set(calls) == {'00:11:22:33:44:55', '00:11:22:33:44:66'}


def test_capability_probe_uses_service_mac_and_detects_denial():
    async def run():
        for status in [200, 403]:
            def handle(request):
                if request.method == 'GET':
                    return httpx.Response(200, json=[{'address': '192.168.7.1/24', 'interface': 'vlan7'}])
                assert json.loads(request.content) == {'mac': wol.WOL_PROBE_MAC, 'interface': 'vlan7'}
                return httpx.Response(status, json=[] if status == 200 else {'error': status})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                result = await wol.check_wol_capability(client, 'https://router.test/rest')
                assert result['ok'] == (status == 200)
    asyncio.run(run())


def test_wake_routes_follow_classroom_access_without_wan_permission(monkeypatch):
    async def run():
        principal = PrincipalResponse(principal_type='user', id=1, role='teacher', display_name='Test', classroom_ids=[7], permissions=[])
        auth = AsyncMock(return_value=principal)
        layout = AsyncMock(return_value={'classroom': CLASSROOM, 'devices': [DEVICE]})
        send = AsyncMock(return_value={'sent_count': 1, 'failed_count': 0, 'results': []})
        monkeypatch.setattr(main, 'get_current_principal', auth)
        monkeypatch.setattr(main, 'get_device_classroom_id', AsyncMock(return_value=7))
        monkeypatch.setattr(main, 'get_classroom_or_404', AsyncMock(return_value=CLASSROOM))
        monkeypatch.setattr(main, 'get_wol_classroom_layout', layout)
        monkeypatch.setattr(main, 'get_router_connection_from_inventory', AsyncMock(return_value=ROUTER))
        monkeypatch.setattr(main, 'send_wol_packets', send)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            for role in ['teacher', 'workstation', 'moderator', 'admin', 'superadmin']:
                principal.role = role
                for path in ['/api/devices/10/wake', '/api/classrooms/7/wake-all']:
                    response = await client.post(path)
                    assert response.status_code == 200
            assert send.await_count == 10
            send.return_value = {"sent_count": 0, "failed_count": 1,
                                 "results": [{"error": "RouterOS: interface is not running"}]}
            failed = await client.post('/api/classrooms/7/wake-all')
            assert failed.status_code == 502
            assert "interface is not running" in failed.json()["detail"]
            send.return_value = {"sent_count": 1, "failed_count": 1,
                                 "results": [{"error": "RouterOS error"}]}
            partial = await client.post('/api/classrooms/7/wake-all')
            assert partial.status_code == 200
            assert partial.json()["failed_count"] == 1
            principal.classroom_ids = []
            send.reset_mock()
            layout.reset_mock()
            for path in ['/api/devices/10/wake', '/api/classrooms/7/wake-all']:
                assert (await client.post(path)).status_code == 403
            send.assert_not_awaited()
            layout.assert_not_awaited()
            principal.classroom_ids = [7]
            layout.return_value = {'classroom': CLASSROOM, 'devices': []}
            assert (await client.post('/api/devices/10/wake')).status_code == 404
            assert (await client.post('/api/classrooms/7/wake-all')).json()['sent_count'] == 0
            send.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("status,payload,expected", [
    (500, {"error": 500, "message": "Internal Server Error", "detail": "not enough permissions (9)"}, "право test"),
    (500, {"error": 500, "detail": "not permitted (9)"}, "право test"),
    (500, {"error": 500, "detail": "input does not match any value of interface"}, "input does not match"),
    (500, {"error": 500, "detail": "failure: interface is not running"}, "interface is not running"),
    (403, {"error": 403}, "право test"),
    (200, {"error": 500, "detail": "command failed"}, "command failed"),
])
def test_routeros_command_errors_preserve_details(status, payload, expected):
    error = wol.wol_response_error(httpx.Response(status, json=payload))
    assert expected in error
    if "право test" not in expected:
        assert "право test" not in error


def test_empty_success_and_invalid_wol_responses():
    assert wol.wol_response_error(httpx.Response(204)) is None
    assert wol.wol_response_error(httpx.Response(200, json=[])) is None
    assert "некорректный" in wol.wol_response_error(httpx.Response(200, text="<html>Login</html>"))
    assert "HTTP 500" in wol.wol_response_error(httpx.Response(500))


def test_capability_probe_recognizes_http_500_permission_error():
    async def run():
        def handle(request):
            if request.method == "GET":
                return httpx.Response(200, json=[{"address": "192.168.7.1/24", "interface": "vlan7"}])
            return httpx.Response(500, json={"error": 500, "message": "Internal Server Error", "detail": "not enough permissions (9)"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            result = await wol.check_wol_capability(client, "https://router.test/rest")
            assert result["ok"] is False
            assert result["status_code"] == 500
            assert "право test" in result["error"]
            assert "not enough permissions (9)" in result["error"]
    asyncio.run(run())



def test_routeros_failure_is_logged_without_credentials(monkeypatch, caplog):
    import logging
    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json=[{"address": "192.168.7.1/24", "interface": "vlan7"}])
        return httpx.Response(500, json={"error": 500, "detail": "failure: interface is not running", "sensitive": ROUTER["api_password"]})
    original = httpx.AsyncClient
    monkeypatch.setattr(wol.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    with caplog.at_level(logging.INFO, logger="uvicorn.error.wol"):
        result = asyncio.run(wol.send_wol_packets(ROUTER, 'https://router.test/rest', CLASSROOM['subnet_cidr'], [DEVICE]))
    assert result["failed_count"] == 1
    assert "routeros_status=500" in caplog.text
    assert "device_id=10" in caplog.text
    assert "interface=vlan7" in caplog.text
    assert "interface is not running" in caplog.text
    assert '"error":500' in caplog.text
    assert ROUTER["api_password"] not in caplog.text


def test_wol_protection_only_excludes_bulk_wake(monkeypatch):
    async def run():
        protected = {**DEVICE, 'wol_protected': True}
        regular = {**DEVICE, 'id': 11, 'wol_protected': False}
        veyon_only = {**DEVICE, 'id': 12, 'veyon_bulk_protected': True}
        layout = {'classroom': CLASSROOM, 'devices': [protected, regular, veyon_only]}
        principal = PrincipalResponse(principal_type='user', id=1, role='teacher', display_name='Test', classroom_ids=[7], permissions=[])
        monkeypatch.setattr(main, 'get_current_principal', AsyncMock(return_value=principal))
        monkeypatch.setattr(main, 'get_device_classroom_id', AsyncMock(return_value=7))
        monkeypatch.setattr(main, 'get_classroom_or_404', AsyncMock(return_value=CLASSROOM))
        monkeypatch.setattr(main, 'get_wol_classroom_layout', AsyncMock(return_value=layout))
        router = AsyncMock(return_value=ROUTER)
        monkeypatch.setattr(main, 'get_router_connection_from_inventory', router)
        send = AsyncMock(return_value={'sent_count': 2, 'failed_count': 0, 'results': []})
        monkeypatch.setattr(main, 'send_wol_packets', send)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            batch = await client.post('/api/classrooms/7/wake-all')
            assert batch.status_code == 200
            assert batch.json()['skipped_count'] == 1
            assert [device['id'] for device in send.await_args.args[-1]] == [11, 12]
            send.reset_mock()
            assert (await client.post('/api/devices/10/wake')).status_code == 200
            assert send.await_args.args[-1] == [protected]
            layout['devices'] = [protected]
            router.reset_mock()
            send.reset_mock()
            result = (await client.post('/api/classrooms/7/wake-all')).json()
            assert result == {'sent_count': 0, 'failed_count': 0, 'skipped_count': 1, 'results': []}
            send.assert_not_awaited()
            router.assert_not_awaited()
    asyncio.run(run())
