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
    return createPortal(<dialog ref={ref} className="modal-card command-output-dialog" aria-labelledby={titleId}
        onCancel={event => {event.preventDefault(); if (!busy) onClose();}}
        onKeyDown={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
        <h3 id={titleId}>Команда с выводом — {title}</h3>
        {scope === "classrooms" && <p className="muted">Устройства с защитой от массового управления через Veyon будут пропущены.</p>}
        {error && <div className="device-modal-error" role="alert">{error}</div>}
        {!job ? <form onSubmit={event => {event.preventDefault(); event.stopPropagation(); void submit();}}>
            <label>Команда PowerShell<textarea autoFocus required maxLength={16000} rows={7} value={command} disabled={busy} onChange={event => setCommand(event.target.value)}/></label>
            <div className="recording-settings-actions">
                <button type="button" className="secondary-button" disabled={busy} onClick={onClose}>Отмена</button>
                <button type="submit" className="danger-button" disabled={busy || !command.trim()}>{busy ? "Запуск…" : "Выполнить"}</button>
            </div>
        </form> : <>
            <p role="status">{job.finished ? "Сбор результатов завершён" : `Сбор результатов: осталось ${Math.max(0, Math.ceil(job.deadline - now / 1000))} сек.`}
                {job.skipped_count > 0 && ` Пропущено защищённых: ${job.skipped_count}.`}</p>
            {!job.results.length && <p>Нет устройств для выполнения команды.</p>}
            <div className="command-output-results">{job.results.map(result => <section key={result.device_id} className={`command-output-result command-output-${result.state}`}>
                <h4>{result.name} <span className="muted">{result.host}</span></h4>
                <p>{result.state === "pending" ? "Ожидание результата" : result.state === "timed_out" ? (result.result_received ? "Время выполнения команды истекло" : "Результат не получен за отведённое время") : `Завершено. Код выхода: ${result.exit_code}`}</p>
                {result.dispatch_error && <p className="device-modal-error">Ошибка отправки: {result.dispatch_error}</p>}
                {result.stdout && <><h5>Вывод</h5><pre>{result.stdout}</pre></>}
                {result.stderr && <><h5>Ошибки</h5><pre className="command-output-stderr">{result.stderr}</pre></>}
                {result.state === "completed" && !result.stdout && !result.stderr && <p className="muted">Команда не вернула текст.</p>}
                {Boolean(result.stdout_truncated || result.stderr_truncated) && <p className="muted">Вывод обрезан: лимит 65 536 символов на поток.</p>}
            </section>)}</div>
            <div className="recording-settings-actions"><button type="button" className="secondary-button" onClick={onClose}>Закрыть</button></div>
            {!job.finished && <p className="muted">Закрытие окна не отменяет уже отправленные команды.</p>}
        </>}
    </dialog>, document.body);
}
