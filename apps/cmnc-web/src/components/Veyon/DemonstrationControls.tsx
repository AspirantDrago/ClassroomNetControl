import {useCallback, useEffect, useRef, useState} from "react";
import {createPortal} from "react-dom";
import {extractErrorDetail, getDemoSources, getDemonstration, sendDemonstrationFrame, startDemonstration, stopDemonstration, touchDemonstration} from "../../api";
import {useNotify, bulkNotification} from "../Notifications/notificationContext";

type Running = {id: string; stream?: MediaStream; video?: HTMLVideoElement; timer?: number; polling?: number; skipped: number; reported: boolean};
export function DemonstrationControls({scope, targetId, classroomId, disabled = false}: {
    scope: "devices" | "classrooms"; targetId: number; classroomId: number; disabled?: boolean;
}) {
    const running = useRef<Running | null>(null);
    const mounted = useRef(true);
    const starting = useRef(false);
    const [routeInfo, setRouteInfo] = useState("");
    const [active, setActive] = useState(false), [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [selection, setSelection] = useState<boolean | null>(null);
    const [sources, setSources] = useState<{id: number; name: string}[]>([]);
    const [source, setSource] = useState("");
    const dialog = useRef<HTMLDialogElement>(null);
    const notify = useNotify();

    const stop = useCallback(async () => {
        const current = running.current;
        running.current = null;
        if (mounted.current) {setActive(false); setRouteInfo("");}
        if (!current) return;
        clearTimeout(current.timer); clearTimeout(current.polling);
        current.stream?.getTracks().forEach(track => {track.onended = null; track.stop();});
        current.video?.pause();
        if (current.video) current.video.srcObject = null;
        try {await stopDemonstration(current.id);}
        catch (err) {if (mounted.current) setError(`${extractErrorDetail(err)}. Сервер автоматически завершит демонстрацию после потери связи.`);}
    }, []);
    useEffect(() => {
        mounted.current = true;
        const unload = () => {void stop();};
        window.addEventListener("pagehide", unload);
        return () => {mounted.current = false; window.removeEventListener("pagehide", unload); void stop();};
    }, [stop]);
    useEffect(() => {
        if (selection === null) return;
        dialog.current?.showModal();
        let live = true;
        getDemoSources(classroomId).then(items => {if (live) setSources(items.filter(item => scope !== "devices" || item.id !== targetId));})
            .catch(err => {if (live) setError(extractErrorDetail(err));});
        return () => {live = false;};
    }, [selection, classroomId, scope, targetId]);

    async function start(fullscreen: boolean, browser: boolean, sourceId?: number) {
        if (starting.current || running.current || disabled) return;
        starting.current = true; setBusy(true); setError(null);
        let stream: MediaStream | undefined;
        let sessionId: string | undefined;
        try {
            if (browser) {
                if (!window.isSecureContext || !navigator.mediaDevices?.getDisplayMedia)
                    throw new Error("Для выбора экрана или окна откройте сайт через HTTPS. Браузер запрещает демонстрацию через обычный HTTP.");
                // Must be the first asynchronous operation after the user's click.
                stream = await navigator.mediaDevices.getDisplayMedia({video: {frameRate: 10}, audio: false});
            }
            const session = await startDemonstration(scope, targetId, fullscreen, sourceId);
            sessionId = session.id;
            if (!mounted.current) {await stopDemonstration(session.id); stream?.getTracks().forEach(track => track.stop()); return;}
            const current: Running = {id: session.id, stream, skipped: session.skipped_count ?? 0, reported: false};
            running.current = current; setActive(true); setSelection(null);
            if (stream) {
                const video = document.createElement("video"); current.video = video;
                video.srcObject = stream; video.muted = true; video.playsInline = true;
                stream.getVideoTracks()[0].onended = () => {void stop();};
                await video.play();
                const canvas = document.createElement("canvas"); canvas.width = 1280; canvas.height = 720;
                const ctx = canvas.getContext("2d");
                if (!ctx) throw new Error("Браузер не поддерживает захват изображения");
                const frame = async () => {
                    if (running.current !== current) return;
                    try {
                        if (video.videoWidth && video.videoHeight) {
                            ctx.fillStyle = "black"; ctx.fillRect(0, 0, 1280, 720);
                            const scale = Math.min(1280 / video.videoWidth, 720 / video.videoHeight);
                            const width = video.videoWidth * scale, height = video.videoHeight * scale;
                            ctx.drawImage(video, (1280 - width) / 2, (720 - height) / 2, width, height);
                            const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/jpeg", 0.8));
                            if (blob && running.current === current) await sendDemonstrationFrame(current.id, blob);
                        }
                        if (running.current === current) current.timer = window.setTimeout(() => void frame(), 100);
                    } catch (err) {if (mounted.current) setError(extractErrorDetail(err)); await stop();}
                };
                void frame();
            }
            const poll = async () => {
                if (running.current !== current) return;
                try {
                    await touchDemonstration(current.id);
                    const status = await getDemonstration(current.id);
                    if (status.error) throw new Error(status.error);
                    if (status.ready && mounted.current) setRouteInfo(
                        `Напрямую: ${status.direct_count ?? 0}. Через CMNC: ${status.relay_count ?? 0}.`);
                    if (status.ready && !current.reported) {
                        current.reported = true;
                        const accepted = status.results.filter(item => item.accepted).length;
                        const timedOut = status.results.filter(item => item.timed_out).length;
                        const notification = bulkNotification("Демонстрация", fullscreen ? "Полноэкранный режим" : "Оконный режим", {
                            accepted_count: accepted, failed_count: status.results.length - accepted,
                            timeout_count: timedOut, skipped_count: current.skipped, results: status.results.map(item => ({...item, error: item.error ?? null}))});
                        notify(notification.content, notification.kind);
                        if (!accepted) {await stop(); return;}
                    }
                    if (running.current === current) current.polling = window.setTimeout(() => void poll(), 5000);
                } catch (err) {if (mounted.current) setError(extractErrorDetail(err)); await stop();}
            };
            void poll();
        } catch (err) {
            if (running.current?.id === sessionId) await stop();
            else {stream?.getTracks().forEach(track => track.stop()); if (sessionId) await stopDemonstration(sessionId).catch(() => {});}
            if (mounted.current && !(err instanceof DOMException && err.name === "NotAllowedError")) setError(extractErrorDetail(err));
        } finally {starting.current = false; if (mounted.current) setBusy(false);}
    }
    return <>
        <div className="device-action-buttons">
            {[true, false].map(fullscreen => <button key={`own-${fullscreen}`} type="button" className="secondary-button" disabled={disabled || busy || active}
                onClick={() => void start(fullscreen, true)}>Демонстрировать собственный экран в {fullscreen ? "полноэкранном" : "оконном"} режиме</button>)}
            {[true, false].map(fullscreen => <button key={`pc-${fullscreen}`} type="button" className="secondary-button" disabled={disabled || busy || active}
                onClick={() => {setError(null); setSources([]); setSource(""); setSelection(fullscreen);}}>Демонстрировать экран выбранного пользователя в {fullscreen ? "полноэкранном" : "оконном"} режиме</button>)}
            {active && <button type="button" className="danger-button" onClick={() => void stop()}>Остановить демонстрацию</button>}
        </div>
        {busy && <p role="status">Запуск демонстрации…</p>}
        {active && !busy && <p role="status">{routeInfo ? `Демонстрация активна. ${routeInfo}` : "Проверка подключений и запуск демонстрации…"}</p>}
        {error && <div className="device-modal-error" role="alert">{error}</div>}
        {selection !== null && createPortal(<dialog ref={dialog} className="modal-card recording-settings device-action-dialog" onCancel={event => {event.preventDefault(); if (!busy) setSelection(null);}}>
            <h3>Источник демонстрации</h3>
            <form onSubmit={event => {event.preventDefault(); void start(selection, false, Number(source));}}>
                <label>Устройство<select autoFocus required disabled={busy} value={source} onChange={event => setSource(event.target.value)}>
                    <option value="">Выберите устройство</option>{sources.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select></label>
                {!sources.length && <p>Нет доступных источников или список ещё загружается.</p>}
                {error && <p role="alert">{error}</p>}
                <div className="recording-settings-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => setSelection(null)}>Отмена</button>
                    <button type="submit" className="primary-button" disabled={!source || busy}>ОК</button></div>
            </form>
        </dialog>, document.body)}
    </>;
}
