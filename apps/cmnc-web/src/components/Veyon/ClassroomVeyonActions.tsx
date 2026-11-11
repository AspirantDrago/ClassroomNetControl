import { useState, type ReactNode } from "react";
import { extractErrorDetail, runVeyonClassroomAction, type VeyonDeviceAction } from "../../api";
import { ActionDialog, actionTitles, type ActionPayload } from "./ActionDialog";

const titles: Record<VeyonDeviceAction, string> = {
    ...actionTitles,
    "power-down-confirmed": "Выключить все после подтверждения",
    "power-down-delayed": "Выключить все по истечению времени",
    login: "Залогиниться всем", logout: "Разлогиниться всем",
    "screen-off": "Погасить все экраны", "screen-on": "Разрешить все экраны",
    message: "Сообщение всем", website: "Открыть сайт всем", command: "Выполнить команду всем",
};

export function ClassroomVeyonActions({classroomId, classroomName, targetCount, showPowerRow, role, disabled, onBusyChange, children}: {
    classroomId: number; classroomName: string; targetCount: number; showPowerRow: boolean;
    role?: string; disabled: boolean; onBusyChange: (busy: boolean) => void; children: ReactNode;
}) {
    const [dialog, setDialog] = useState<VeyonDeviceAction | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const admin = role === "admin" || role === "superadmin";
    const description = `Аудитория «${classroomName}»: устройств ${targetCount}. Устройства с защитой от массового управления через Veyon будут пропущены.`;

    async function send(payload: ActionPayload) {
        if (busy || disabled) return;
        setBusy(true); onBusyChange(true); setError(null); setMessage(null);
        try {
            const result = await runVeyonClassroomAction(classroomId, payload);
            const failure = result.results.find(item => !item.accepted)?.error ?? "";
            if (!result.accepted_count && result.failed_count) throw new Error(failure || "Не удалось отправить команды");
            setDialog(null);
            setMessage(`«${titles[payload.action]}»: отправлено ${result.accepted_count}. Пропущено защищённых: ${result.skipped_count}.${result.failed_count ? ` Ошибок: ${result.failed_count}. ${failure}` : ""}`);
        } catch (err) { setError(extractErrorDetail(err)); }
        finally {setBusy(false); onBusyChange(false);}
    }
    function button(action: VeyonDeviceAction, color: string, input = false) {
        return <button type="button" className={color} disabled={busy || disabled} onClick={() => {
            setError(null);
            if (input) setDialog(action);
            else if (window.confirm(`${titles[action]}? ${description}`)) void send({action});
        }}>{titles[action]}</button>;
    }
    return <>
        {showPowerRow && <section className="classroom-action-row" aria-label="Питание">
            <span className="classroom-action-label">Питание:</span>
            <div className="classroom-actions">
                {children}
                {targetCount > 0 && <>
                    {button("power-down-confirmed", "orange-button")}
                    {button("power-down-delayed", "purple-button", true)}
                </>}
            </div>
        </section>}
        {targetCount > 0 && <>
            <section className="classroom-action-row" aria-label="Авторизация">
                <span className="classroom-action-label">Авторизация:</span>
                <div className="classroom-actions">{button("login", "success-button", true)}{button("logout", "danger-button", true)}</div>
            </section>
            <section className="classroom-action-row" aria-label="Внимание">
                <span className="classroom-action-label">Внимание:</span>
                <div className="classroom-actions">{button("screen-off", "danger-button")}{button("screen-on", "success-button")}</div>
            </section>
            <section className="classroom-action-row" aria-label="Команды">
                <span className="classroom-action-label">Команды:</span>
                <div className="classroom-actions">{button("message", "success-button", true)}{button("website", "success-button", true)}{admin && button("command", "danger-button", true)}</div>
            </section>
        </>}
        {error && !dialog && <div className="device-modal-error" role="alert">{error}</div>}
        {message && <p role="status">{message}</p>}
        {dialog && <ActionDialog key={dialog} action={dialog} title={titles[dialog]} description={description} busy={busy} error={error}
            onClose={() => setDialog(null)} onSubmit={payload => void send(payload)}/>}
    </>;
}
