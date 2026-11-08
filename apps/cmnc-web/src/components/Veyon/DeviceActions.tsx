import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { extractErrorDetail, getCurrentPrincipal, runVeyonAction, type DashboardDevice, type VeyonDeviceAction } from "../../api";

const titles: Record<VeyonDeviceAction, string> = {
    "install-updates-and-power-down": "Установить обновления и выключить",
    "power-down-confirmed": "Выключить после подтверждения", "power-down-delayed": "Выключить по истечению времени",
    login: "Залогиниться", logout: "Разлогиниться", "screen-off": "Погасить экран", "screen-on": "Разрешить экран",
    message: "Сообщение", website: "Открыть сайт", command: "Выполнить команду",
};
type Payload = Parameters<typeof runVeyonAction>[1];

function ActionDialog({ action, busy, error, onClose, onSubmit }: {action: VeyonDeviceAction; busy: boolean; error: string | null; onClose: () => void; onSubmit: (payload: Payload) => void}) {
    const ref = useRef<HTMLDialogElement>(null);
    const [text, setText] = useState("");
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [hours, setHours] = useState("0"), [minutes, setMinutes] = useState("0"), [seconds, setSeconds] = useState("0");
    useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close(); }, []);
    const total = Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds);
    const validTime = [hours, minutes, seconds].every(value => /^\d+$/.test(value)) && Number(minutes) <= 59 && Number(seconds) <= 59 && total >= 1 && total <= 604800;
    const valid = action === "login" ? !!username.trim() && !!password : action === "power-down-delayed" ? validTime : action === "logout" ? true : !!text.trim();
    return createPortal(<dialog ref={ref} className="modal-card recording-settings screen-quality-dialog device-action-dialog" aria-labelledby="device-action-title"
        onCancel={event => {event.preventDefault(); if (!busy) onClose();}} onKeyDown={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
        <h3 id="device-action-title">{titles[action]}</h3>
        <form onSubmit={event => {event.preventDefault(); if (valid && !busy) onSubmit({action, text, username, password: action === "login" ? password : undefined, seconds: action === "power-down-delayed" ? total : undefined, confirmed: action === "logout"});}}>
            {action === "login" ? <>
                <label>Логин<input autoFocus required maxLength={256} autoComplete="off" value={username} onChange={event => setUsername(event.target.value)} disabled={busy}/></label>
                <label>Пароль<input required type="password" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} disabled={busy}/></label>
            </> : action === "power-down-delayed" ? <div className="device-action-time">
                <label>Часы<input autoFocus type="number" min="0" max="168" step="1" required value={hours} onChange={event => setHours(event.target.value)} disabled={busy}/></label>
                <label>Минуты<input type="number" min="0" max="59" step="1" required value={minutes} onChange={event => setMinutes(event.target.value)} disabled={busy}/></label>
                <label>Секунды<input type="number" min="0" max="59" step="1" required value={seconds} onChange={event => setSeconds(event.target.value)} disabled={busy}/></label>
            </div> : action === "logout" ? <p>Завершить сеанс пользователя на удалённом ПК? Несохранённые данные могут быть потеряны.</p> : <label>{action === "website" ? "Адрес сайта (http:// или https://)" : action === "command" ? "Команда (PowerShell)" : "Текст сообщения"}
                {action === "website" ? <input autoFocus type="url" required maxLength={16000} value={text} onChange={event => setText(event.target.value)} disabled={busy}/> : <textarea autoFocus required maxLength={16000} rows={7} value={text} onChange={event => setText(event.target.value)} disabled={busy}/>}
            </label>}
            {error && <div className="device-modal-error" role="alert">{error}</div>}
            <div className="recording-settings-actions">
                <button type="button" className="secondary-button" disabled={busy} onClick={onClose}>Отмена</button>
                <button type="submit" className="primary-button" disabled={busy || !valid}>{busy ? "Отправка…" : "ОК"}</button>
            </div>
        </form>
    </dialog>, document.body);
}

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
