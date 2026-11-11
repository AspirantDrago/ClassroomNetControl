import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { runVeyonAction, type VeyonDeviceAction } from "../../api";

export const actionTitles: Record<VeyonDeviceAction, string> = {
    "install-updates-and-power-down": "Установить обновления и выключить",
    "power-down-confirmed": "Выключить после подтверждения", "power-down-delayed": "Выключить по истечению времени",
    login: "Залогиниться", logout: "Разлогиниться", "screen-off": "Погасить экран", "screen-on": "Разрешить экран",
    message: "Сообщение", website: "Открыть сайт", command: "Выполнить команду",
};
export type ActionPayload = Parameters<typeof runVeyonAction>[1];

export function ActionDialog({ action, title, description, busy, error, onClose, onSubmit }: {action: VeyonDeviceAction; title?: string; description?: string; busy: boolean; error: string | null; onClose: () => void; onSubmit: (payload: ActionPayload) => void}) {
    const titleId = useId();
    const ref = useRef<HTMLDialogElement>(null);
    const [text, setText] = useState("");
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [hours, setHours] = useState("0"), [minutes, setMinutes] = useState("0"), [seconds, setSeconds] = useState("0");
    useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close(); }, []);
    const total = Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds);
    const validTime = [hours, minutes, seconds].every(value => /^\d+$/.test(value)) && Number(minutes) <= 59 && Number(seconds) <= 59 && total >= 1 && total <= 604800;
    const valid = action === "login" ? !!username.trim() && !!password : action === "power-down-delayed" ? validTime : action === "logout" ? true : !!text.trim();
    return createPortal(<dialog ref={ref} className="modal-card recording-settings screen-quality-dialog device-action-dialog" aria-labelledby={titleId}
        onCancel={event => {event.preventDefault(); if (!busy) onClose();}} onKeyDown={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
        <h3 id={titleId}>{title ?? actionTitles[action]}</h3>
        {description && <p>{description}</p>}
        <form onSubmit={event => {event.preventDefault(); event.stopPropagation(); if (valid && !busy) onSubmit({action, text, username, password: action === "login" ? password : undefined, seconds: action === "power-down-delayed" ? total : undefined, confirmed: action === "logout"});}}>
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

