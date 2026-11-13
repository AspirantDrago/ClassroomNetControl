import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { extractErrorDetail, getOutputCommand, startOutputCommand, type CommandOutputJob } from "../../api";
import "./CommandOutputDialog.css";

export function CommandOutputDialog({scope, targetId, title, onClose}: {
    scope: "devices" | "classrooms"; targetId: number; title: string; onClose: () => void;
}) {
    const ref = useRef<HTMLDialogElement>(null);
    const titleId = useId();
    const [command, setCommand] = useState("");
    const [busy, setBusy] = useState(false);
    const [job, setJob] = useState<CommandOutputJob | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [now, setNow] = useState(Date.now);
    useEffect(() => {const dialog = ref.current!; dialog.showModal(); return () => dialog.close();}, []);
    const jobId = job?.id;
    const finished = job?.finished;
    useEffect(() => {
        if (!jobId || finished) return;
        let stopped = false;
        let timer: ReturnType<typeof setTimeout>;
        const controller = new AbortController();
        async function poll() {
            try {
                const next = await getOutputCommand(jobId!, controller.signal);
                if (stopped) return;
                setJob(next); setError(null);
                if (next.finished) return;
            } catch (err) {if (!stopped) setError(extractErrorDetail(err));}
            if (!stopped) timer = setTimeout(() => void poll(), 1000);
        }
        timer = setTimeout(() => void poll(), 500);
        const clock = setInterval(() => setNow(Date.now()), 1000);
        return () => {stopped = true; controller.abort(); clearTimeout(timer); clearInterval(clock);};
    }, [jobId, finished]);
    async function submit() {
        if (busy || !command.trim()) return;
        setBusy(true); setError(null);
        try {setJob(await startOutputCommand(scope, targetId, command)); setNow(Date.now());}
        catch (err) {setError(extractErrorDetail(err));}
        finally {setBusy(false);}
    }
    return createPortal(<dialog ref={ref} className={`modal-card command-output-dialog${job ? " command-output-dialog-results" : ""}`} aria-labelledby={titleId}
        onCancel={event => {event.preventDefault(); if (!busy) onClose();}}
        onKeyDown={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
        <div className="command-output-header">
            <h3 id={titleId}>Команда с выводом — {title}</h3>
            <button type="button" className="command-output-close" aria-label="Закрыть" title="Закрыть" disabled={busy} onClick={onClose}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>
            </button>
        </div>
        {scope === "classrooms" && <p className="muted">Устройства с защитой от массового управления через Veyon будут пропущены.</p>}
        {error && <div className="device-modal-error" role="alert">{error}</div>}
        {!job ? <form className="command-output-form" onSubmit={event => {event.preventDefault(); event.stopPropagation(); void submit();}}>
            <label>Команда PowerShell<textarea autoFocus required maxLength={16000} rows={7} value={command} disabled={busy} onChange={event => setCommand(event.target.value)}/></label>
            <div className="recording-settings-actions">
                <button type="button" className="secondary-button" disabled={busy} onClick={onClose}>Отмена</button>
                <button type="submit" className="danger-button" disabled={busy || !command.trim()}>{busy ? "Запуск…" : "Выполнить"}</button>
            </div>
        </form> : <>
            <p role="status">{job.finished ? "Сбор результатов завершён" : `Сбор результатов: осталось ${Math.max(0, Math.ceil(job.deadline - now / 1000))} сек.`}
                {job.skipped_count > 0 && ` Пропущено защищённых: ${job.skipped_count}.`}</p>
            {!job.results.length && <p>Нет устройств для выполнения команды.</p>}
            <div className={`command-output-results${job.results.length === 1 ? " command-output-results-single" : ""}`}>{job.results.map(result => <section key={result.device_id} className={`command-output-result command-output-${result.state}`}>
                <h4>{result.name} <span className="muted">{result.host}</span></h4>
                <p>{result.state === "pending" ? "Ожидание результата" : result.state === "timed_out" ? (result.result_received ? "Время выполнения команды истекло" : "Результат не получен за отведённое время") : `Завершено. Код выхода: ${result.exit_code}`}</p>
                {result.dispatch_error && <p className="device-modal-error">Ошибка отправки: {result.dispatch_error}</p>}
                {result.stdout && <OutputStream label="Вывод" text={result.stdout}/>}
                {result.stderr && <OutputStream label="Ошибки" text={result.stderr} errorStream/>}
                {result.state === "completed" && !result.stdout && !result.stderr && <p className="muted">Команда не вернула текст.</p>}
                {Boolean(result.stdout_truncated || result.stderr_truncated) && <p className="muted">Вывод обрезан: лимит 65 536 символов на поток.</p>}
            </section>)}</div>
            {!job.finished && <p className="muted">Закрытие окна не отменяет уже отправленные команды.</p>}
        </>}
    </dialog>, document.body);
}


async function copyOutput(text: string, container: HTMLElement) {
    if (navigator.clipboard?.writeText) {
        try {await navigator.clipboard.writeText(text); return;} catch { /* Support HTTP sites with the selection fallback. */ }
    }
    const focused = document.activeElement;
    const selection = document.createElement("textarea");
    selection.value = text;
    selection.readOnly = true;
    selection.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0";
    // A modal dialog makes elements outside its top layer inert.
    container.appendChild(selection);
    try {
        selection.focus({preventScroll: true});
        selection.select();
        if (!document.execCommand("copy")) throw new Error("Не удалось скопировать. Выделите текст вручную.");
    } finally {
        selection.remove();
        if (focused instanceof HTMLElement) focused.focus({preventScroll: true});
    }
}

function OutputStream({label, text, errorStream = false}: {label: string; text: string; errorStream?: boolean}) {
    const [copied, setCopied] = useState(false);
    const [copyError, setCopyError] = useState<string | null>(null);
    const feedback = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    useEffect(() => () => clearTimeout(feedback.current), []);
    return <div className="command-output-stream" role="group" aria-label={label}>
        <div className="command-output-stream-header">
            <h5>{label}</h5>
            <button type="button" className="secondary-button command-output-copy" aria-label="Скопировать в буфер обмена" title="Скопировать в буфер обмена"
                onClick={async event => {
                    const container = event.currentTarget.closest("dialog")!;
                    setCopyError(null);
                    try {
                        await copyOutput(text, container);
                        setCopied(true); clearTimeout(feedback.current);
                        feedback.current = setTimeout(() => setCopied(false), 2000);
                    } catch (err) {setCopyError(extractErrorDetail(err));}
                }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/></svg>
                <span>{copied ? "Скопировано" : "Скопировать в буфер обмена"}</span>
            </button>
        </div>
        {copyError && <div className="device-modal-error" role="alert">{copyError}</div>}
        <pre className={errorStream ? "command-output-stderr" : undefined}>{text}</pre>
    </div>;
}
