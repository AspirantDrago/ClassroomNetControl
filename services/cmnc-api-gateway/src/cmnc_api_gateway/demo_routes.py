from typing import Literal
import ipaddress

import httpx
from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from cmnc_contracts.demo_endpoint import DemoEndpoint

from cmnc_api_gateway import main as gateway
from cmnc_api_gateway.veyon_routes import authorized_layout, authorized_target, bulk_veyon_devices, device_target, service_call


class DemoRequest(BaseModel):
    mode: Literal['demo-fullscreen', 'demo-window']
    source_device_id: int | None = Field(default=None, gt=0)
    confirmed: Literal[True]


def owner(principal):
    return f'{principal.principal_type}:{principal.id}'


async def owned(session_id, request, authorization):
    principal = await gateway.get_current_principal(request, authorization)
    session = (await service_call('GET', f'/internal/demonstrations/{session_id}')).json()
    if session.get('owner') != owner(principal):
        raise HTTPException(403, 'Демонстрация принадлежит другой учётной записи')
    await gateway.ensure_classroom_access(principal, session['classroom_id'])
    if session.get('source_classroom_id'):
        await gateway.ensure_classroom_access(principal, session['source_classroom_id'])
    return session


async def start(layout, targets, payload, principal, request, authorization, skipped=0):
    source = await authorized_target(payload.source_device_id, request, authorization, principal) if payload.source_device_id else None
    targets = [t for t in targets if not source or t['device_id'] != source['device_id']]
    if not targets:
        raise HTTPException(409, 'Нет подходящих получателей демонстрации')
    router_id = gateway.get_classroom_router_id(layout['classroom'])
    router = await gateway.get_router_connection_from_inventory(router_id)
    try:
        endpoint = DemoEndpoint(relay_host=router.get('veyon_demo_host') or '',
                                relay_port=router.get('veyon_demo_port', 11400))
    except ValidationError as exc:
        raise HTTPException(409, 'В настройках MikroTik укажите адрес и порт сервера демонстрации CMNC') from exc
    result = (await service_call('POST', '/internal/demonstrations', {
        'owner': owner(principal), 'classroom_id': layout['classroom']['id'],
        'targets': targets, 'source': source, 'mode': payload.mode, **endpoint.model_dump(),
        'direct_probe_callback_url': router.get('veyon_callback_url') if source and source['router_id'] == router_id
            and ipaddress.ip_address(source['host']) in ipaddress.ip_network(layout['classroom']['subnet_cidr'], strict=False) else None})).json()
    result.pop('owner', None)
    return {**result, 'skipped_count': skipped}


def register_demo_routes(app):
    @app.post('/api/veyon/demonstrations/{session_id}/probes/{device_id}')
    async def probe_result(session_id: str, device_id: int, payload: ProbeResponse,
                           authorization: str | None = Header(default=None)):
        scheme, _, token = (authorization or '').partition(' ')
        if scheme.lower() != 'bearer' or not 20 <= len(token) <= 128:
            raise HTTPException(403, 'Требуется токен проверки')
        return (await service_call('POST', f'/internal/demonstrations/{session_id}/probe-result', {
            'device_id': device_id, 'token': token, 'reachable': payload.reachable})).json()

    @app.get('/api/classrooms/{classroom_id}/veyon/demo-sources')
    async def sources(classroom_id: int, request: Request, authorization: str | None = Header(default=None)):
        layout = await authorized_layout(classroom_id, request, authorization)
        return [{'id': d['id'], 'name': d.get('inventory_name') or d.get('hostname') or d['mac_address']}
                for d in layout['devices'] if not d.get('is_non_pc', False)]

    @app.post('/api/classrooms/{classroom_id}/veyon/demonstrations')
    async def classroom_demo(classroom_id: int, payload: DemoRequest, request: Request, authorization: str | None = Header(default=None)):
        principal = await gateway.get_current_principal(request, authorization)
        layout = await authorized_layout(classroom_id, request, authorization, principal)
        devices = bulk_veyon_devices(layout)
        targets = []
        # Invalid IPs are reported rather than silently dropping configured devices.
        for device in devices:
            targets.append(device_target(layout, device))
        skipped = sum(not d.get('is_non_pc', False) and d.get('veyon_bulk_protected', False) and
                      d['id'] != payload.source_device_id for d in layout['devices'])
        return await start(layout, targets, payload, principal, request, authorization, skipped)

    @app.post('/api/devices/{device_id}/veyon/demonstrations')
    async def device_demo(device_id: int, payload: DemoRequest, request: Request, authorization: str | None = Header(default=None)):
        principal = await gateway.get_current_principal(request, authorization)
        target = await authorized_target(device_id, request, authorization, principal)
        layout = await authorized_layout(target['classroom_id'], request, authorization, principal)
        return await start(layout, [target], payload, principal, request, authorization)

    @app.get('/api/veyon/demonstrations/{session_id}')
    async def demo_status(session_id: str, request: Request, authorization: str | None = Header(default=None)):
        result = await owned(session_id, request, authorization)
        result.pop('owner', None)
        return result

    @app.post('/api/veyon/demonstrations/{session_id}/heartbeat')
    async def demo_heartbeat(session_id: str, request: Request, authorization: str | None = Header(default=None)):
        await owned(session_id, request, authorization)
        return (await service_call('POST', f'/internal/demonstrations/{session_id}/heartbeat')).json()

    @app.delete('/api/veyon/demonstrations/{session_id}')
    async def demo_stop(session_id: str, request: Request, authorization: str | None = Header(default=None)):
        await owned(session_id, request, authorization)
        return (await service_call('DELETE', f'/internal/demonstrations/{session_id}')).json()

    @app.post('/api/veyon/demonstrations/{session_id}/frame')
    async def demo_frame(session_id: str, request: Request, authorization: str | None = Header(default=None)):
        await owned(session_id, request, authorization)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 2 * 1024 * 1024:
                raise HTTPException(413, 'Кадр слишком большой')
        try:
            client = gateway.app.state.veyon_http
            response = await client.post(gateway.settings.veyon_service_url.rstrip('/') +
                f'/internal/demonstrations/{session_id}/frame', content=bytes(data), headers={'Content-Type': 'image/jpeg'})
        except httpx.HTTPError as exc:
            raise HTTPException(503, 'Сервис демонстрации недоступен') from exc
        if not response.is_success:
            raise HTTPException(response.status_code if response.status_code in (404, 409, 413, 422) else 502,
                                'Не удалось передать кадр демонстрации')
        return {'accepted': True}


class ProbeResponse(BaseModel):
    reachable: bool = Field(strict=True)

