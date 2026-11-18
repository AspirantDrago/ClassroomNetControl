"""Fixed, authenticated recipient-to-source reachability probe.

This is not a general command endpoint: the script only authenticates to one
server-owned source IPv4 and reports a boolean using a per-recipient token.
"""
import asyncio
import base64
import ipaddress
import logging
import re
import secrets
from pathlib import Path

from fastapi import HTTPException
from cmnc_contracts.veyon_actions import DeviceAction
from cmnc_veyon_service.command_jobs import callback_base

logger = logging.getLogger(__name__)


def probe_script(source, source_token, callback, token):
    host = str(ipaddress.IPv4Address(source))
    if len(source_token) != 64 or any(c not in '0123456789abcdef' for c in source_token):
        raise ValueError('Invalid source token')
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,128}', token):
        raise ValueError('Invalid probe token')
    # Neither callback URLs nor arbitrary command text are interpolated as code.
    callback = base64.b64encode(callback.encode()).decode('ascii')
    return (Path(__file__).with_name('demo_probe.ps1').read_text(encoding='utf-8')
        .replace('__SOURCE_HOST__', host).replace('__SOURCE_TOKEN__', source_token)
        .replace('__CALLBACK_B64__', callback).replace('__PROBE_TOKEN__', token))


async def probe_recipients(bridge, session, callback_url):
    callback_url = callback_base(callback_url)
    session.probe_tokens = {t.device_id: secrets.token_urlsafe(32) for t in session.targets}
    capacity = asyncio.Semaphore(30)
    async def send(target):
        try:
            callback = f'{callback_url}/api/veyon/demonstrations/{session.id}/probes/{target.device_id}'
            script = probe_script(session.source.host, session.source_token, callback, session.probe_tokens[target.device_id])
            async with asyncio.timeout(30), capacity:
                arguments = DeviceAction(action='command', text=script).feature_arguments()
                arguments['applications'][0] = arguments['applications'][0].replace('powershell.exe ', 'powershell.exe -WindowStyle Hidden ', 1)
                await bridge.operate(target, 'command', arguments=arguments)
        except (HTTPException, TimeoutError):
            # A late acknowledgement can still arrive. Missing/failed results use relay.
            pass
    await asyncio.gather(*(send(t) for t in session.targets))
    try:
        async with asyncio.timeout(8):
            async with session.changed:
                await session.changed.wait_for(lambda: len(session.probe_results) == len(session.targets) or session.stopping)
    except TimeoutError:
        pass
    ready = {device_id for device_id, ok in session.probe_results.items() if ok}
    logger.info(
        'Veyon demo probe session=%s source_device_id=%s reachable=%s unreachable=%s missing=%s',
        session.id, session.source.device_id, sorted(ready),
        sorted(device_id for device_id, ok in session.probe_results.items() if not ok),
        sorted(t.device_id for t in session.targets if t.device_id not in session.probe_results),
    )
    session.probe_tokens.clear()  # late callbacks cannot alter an established route
    return ready


def accept_probe(session, device_id, token, reachable):
    expected = session.probe_tokens.get(device_id)
    if not expected or session.stopping or not secrets.compare_digest(expected, token):
        raise HTTPException(403, 'Недействительный или завершённый тест доступности')
    if device_id in session.probe_results:
        raise HTTPException(410, 'Результат уже получен')
    session.probe_results[device_id] = reachable
