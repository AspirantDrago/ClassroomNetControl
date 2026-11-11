import asyncio
import base64
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from cmnc_contracts.veyon_actions import DeviceAction, FEATURE_IDS
from cmnc_veyon_service.main import VeyonBridge, Target
from cmnc_api_gateway import main as gateway, veyon_routes
from cmnc_api_gateway.schemas import PrincipalResponse


@pytest.mark.parametrize('action,extra,expected', [
    ('power-down-confirmed', {}, {}),
    ('power-down-delayed', {'seconds': 3661}, {'shutdownTimeout': 3661}),
    ('login', {'username':' test ', 'password':'secret-example'}, {'username':'test', 'password':'secret-example'}),
    ('logout', {'confirmed':True}, {}),
    ('screen-off', {}, {}), ('screen-on', {}, {}),
    ('message', {'text':'First\nSecond'}, {'text':'First\nSecond'}),
    ('website', {'text':'https://example.com'}, {'websiteUrls':['https://example.com']}),
    ('install-updates-and-power-down', {}, {}),
])
def test_native_action_mapping_and_activation(action, extra, expected):
    class Store:
        def resolve(self, *_): return 'test', 'test-key'
    async def run():
        calls = []
        def handle(request):
            if request.method == 'POST': return httpx.Response(200, json={'connection-uid':'test'})
            calls.append(request)
            return httpx.Response(200, json={})
        payload = DeviceAction(action=action, **extra)
        assert payload.feature_arguments() == expected
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(Store(), client)
            await bridge.operate(Target(device_id=1, router_id=1, classroom_id=1, host='192.168.1.10'), action, arguments=payload.feature_arguments(), active=action != 'screen-on')
        import json
        assert calls[0].url.path.endswith(FEATURE_IDS[action])
        assert json.loads(calls[0].content) == {'active':action != 'screen-on', 'arguments':expected}
    asyncio.run(run())


@pytest.mark.parametrize('payload', [
    {'action':'power-down-delayed','seconds':0}, {'action':'power-down-delayed','seconds':604801},
    {'action':'logout'}, {'action':'login','username':'x'},
    {'action':'website','text':'file:///C:/x'}, {'action':'website','text':'javascript:alert(1)'},
    {'action':'message','text':' '}, {'action':'command','text':''},
])
def test_action_rejects_invalid_input(payload):
    with pytest.raises(ValidationError): DeviceAction(**payload)


def test_password_masking_and_multiline_command_transport():
    payload = DeviceAction(action='login', username='u', password='private-test-value')
    assert 'private-test-value' not in repr(payload)
    assert 'private-test-value' not in payload.model_dump_json()
    assert payload.wire()['password'] == 'private-test-value'
    script = 'Write-Output "Привет"\nGet-Date'
    arguments = DeviceAction(action='command', text=script).feature_arguments()
    encoded = arguments['applications'][0].split()[-1]
    assert base64.b64decode(encoded).decode('utf-16-le') == script


@pytest.mark.parametrize('role,allowed', [('teacher',False),('moderator',False),('admin',True),('superadmin',True)])
@pytest.mark.parametrize('action', ['command','install-updates-and-power-down'])
def test_gateway_restricts_admin_actions(monkeypatch, role, allowed, action):
    async def run():
        principal = PrincipalResponse(principal_type='user', id=1, role=role, display_name='Test', classroom_ids=[1], permissions=[])
        monkeypatch.setattr(gateway,'get_current_principal',AsyncMock(return_value=principal))
        target = AsyncMock(return_value={'device_id':1,'router_id':1,'classroom_id':1,'host':'192.168.1.10'})
        monkeypatch.setattr(veyon_routes,'authorized_target',target)
        service = AsyncMock(return_value=httpx.Response(200,json={'accepted':True}))
        monkeypatch.setattr(veyon_routes,'service_call',service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),base_url='http://test') as client:
            response = await client.post('/api/devices/1/veyon/action',json={'action':action,'text':'Get-Date'})
        assert response.status_code == (200 if allowed else 403)
        if not allowed:
            target.assert_not_awaited(); service.assert_not_awaited()
        else:
            target.assert_awaited_once()
            assert service.call_args.args[1] == '/internal/device/action'
    asyncio.run(run())


@pytest.mark.parametrize('value,expected', [
    ('example.com', 'http://example.com'),
    (' example.com/path?q=1#part ', 'http://example.com/path?q=1#part'),
    ('localhost:8080/path', 'http://localhost:8080/path'),
    ('192.168.1.10:8080', 'http://192.168.1.10:8080'),
    ('//example.com/path', 'http://example.com/path'),
    ('http://example.com', 'http://example.com'),
    ('https://example.com/path', 'https://example.com/path'),
])
def test_website_without_protocol_defaults_to_http(value, expected):
    payload = DeviceAction(action='website', text=value)
    assert payload.wire()['text'] == expected
    assert payload.feature_arguments() == {'websiteUrls': [expected]}


@pytest.mark.parametrize('value', ['javascript:alert(1)', 'data:text/html,test', 'ftp://example.com',
    'file:///C:/test', 'http://user:pass@example.com', 'example.com:99999'])
def test_website_normalization_does_not_allow_unsupported_urls(value):
    with pytest.raises(ValidationError):
        DeviceAction(action='website', text=value)


@pytest.mark.parametrize("response_status", [None, 408, 504])
def test_proxy_timeout_is_reported_as_gateway_timeout(response_status):
    async def run():
        def handle(request):
            if response_status is None:
                raise httpx.ReadTimeout("slow proxy", request=request)
            return httpx.Response(response_status, json={"error": {"message": "timeout"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            bridge = VeyonBridge(None, client)
            with pytest.raises(gateway.HTTPException) as error:
                await bridge.checked("POST", "/api/v1/authentication/test")
            assert error.value.status_code == 504
    asyncio.run(run())
