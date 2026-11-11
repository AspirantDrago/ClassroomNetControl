import { useEffect, useState } from "react";
import { extractErrorDetail, getCurrentPrincipal, runVeyonAction, type DashboardDevice, type VeyonDeviceAction } from "../../api";
import { ActionDialog, actionTitles as titles, type ActionPayload as Payload } from "./ActionDialog";

export function DeviceActions({device, canControlWan, wanBusy, wakeBusy, powerBusy, onToggleWan, onWake, onPower}: {
    device: DashboardDevice; canControlWan: boolean; wanBusy: boolean; wakeBusy: boolean; powerBusy: boolean;
    onToggleWan: (device: DashboardDevice) => void; onWake: (device: DashboardDevice) => void;
    onPower: (device: DashboardDevice, action: "power-down" | "reboot") => void;
}) {
    const [admin, setAdmin] = useState(false);
    const [dialog, setDialog] = useState<VeyonDeviceAction | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    useEffect(() => {let stopped = false; void getCurrentPrincipal().then(user => {if (!stopped) setAdmin(user.role === "admin" || user.role === "superadmin");}).catch(() => {}); return () => {stopped = true;};}, []);
    async function send(payload: Payload) {
        setBusy(true); setError(null); setMessage(null);
        try { await runVeyonAction(device.id, payload); setDialog(null); setMessage(`«${titles[payload.action]}»: команда отправлена.`); }
        catch (err) { setError(extractErrorDetail(err)); }
        finally {setBusy(false);}
    }
    function open(action: VeyonDeviceAction) {setError(null); setDialog(action);}
    function actionButton(action: VeyonDeviceAction, color: string, input = false) {
        return <button type="button" className={color} disabled={busy || powerBusy} onClick={() => input ? open(action) : void send({action})}>{titles[action]}</button>;
    }
    return <div className="device-action-groups">
        {error && !dialog && <div className="device-modal-error" role="alert">{error}</div>}
        {message && <p role="status">{message}</p>}
        <section><h4>Интернет</h4><div className="device-action-buttons">
            <button type="button" className={device.wan_allowed ? "danger-button" : "success-button"} disabled={wanBusy || !canControlWan || (device.wan_protected && device.wan_allowed)} onClick={() => onToggleWan(device)}>{device.wan_allowed ? "Отключить Интернет" : "Включить Интернет"}</button>
        </div></section>
        <section><h4>Питание</h4><div className="device-action-buttons">
            <button type="button" className="success-button" disabled={wakeBusy} onClick={() => onWake(device)}>Разбудить</button>
            <button type="button" className="danger-button" disabled={powerBusy || busy} onClick={() => onPower(device, "power-down")}>Выключить</button>
            <button type="button" className="secondary-button" disabled={powerBusy || busy} onClick={() => onPower(device, "reboot")}>Перезагрузить</button>
            {admin && actionButton("install-updates-and-power-down", "danger-button")}
            {actionButton("power-down-confirmed", "orange-button")}
            {actionButton("power-down-delayed", "purple-button", true)}
        </div></section>
        <section><h4>Авторизация</h4><div className="device-action-buttons">
            {actionButton("login", "success-button", true)}{actionButton("logout", "danger-button", true)}
        </div></section>
        <section><h4>Внимание</h4><div className="device-action-buttons">
            {actionButton("screen-off", "danger-button")}{actionButton("screen-on", "success-button")}
        </div></section>
        <section><h4>Команды</h4><div className="device-action-buttons">
            {actionButton("message", "success-button", true)}{actionButton("website", "success-button", true)}
            {admin && actionButton("command", "danger-button", true)}
        </div></section>
        {dialog && <ActionDialog key={dialog} action={dialog} busy={busy} error={error} onClose={() => setDialog(null)} onSubmit={payload => void send(payload)}/>}
    </div>;
}
