import { useEffect, useRef, useState } from "react";
import { ScreenIcon } from "./ScreenIcon";
import { extractErrorDetail, refreshVeyonScreen, getVeyonFrame, getVeyonSnapshot, getCurrentPrincipal, type VeyonShortcut } from "../../api";
import "./Veyon.css";
import { ScreenQualitySettings } from "./ScreenQualitySettings";
import { SCREEN_QUALITIES, readScreenQuality, saveScreenQuality } from "./screenQuality";
import { RecordingSettings } from "./RecordingSettings";
import { useScreenRecording } from "./useScreenRecording";
import { downloadMedia, mediaFilename, recordingClock, RECORDING_MAX_SECONDS, RECORDING_QUALITIES } from "./recording";
import { RemoteControlImage } from "./RemoteControlImage";

export function DeviceScreen({ deviceId, deviceName, classroomName, standalone = false, control = false, onFps }: { deviceId: number; deviceName?: string; classroomName?: string; standalone?: boolean; control?: boolean; onFps?: (fps: number) => void }) {
    const [source, setSource] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [popup, setPopup] = useState<Window | null>(null);
    const [screenQuality, setScreenQuality] = useState(readScreenQuality);
    const [qualitySettings, setQualitySettings] = useState(false);
    useEffect(() => {
        const refreshQuality = () => setScreenQuality(readScreenQuality());
        window.addEventListener("focus", refreshQuality);
        return () => window.removeEventListener("focus", refreshQuality);
    }, []);
    const [fps, setFps] = useState(0);
    const commandRef = useRef<((shortcut: VeyonShortcut) => Promise<void>) | null>(null);
    const [canSendAdminShortcut, setCanSendAdminShortcut] = useState(false);
    const [shortcutBusy, setShortcutBusy] = useState(false);
    useEffect(() => {
        if (!control) return;
        let disposed = false;
        void getCurrentPrincipal().then(principal => {
            if (!disposed) setCanSendAdminShortcut(principal.role === "admin" || principal.role === "superadmin");
        }).catch(() => {});
        return () => { disposed = true; };
    }, [control]);
    async function sendShortcut(shortcut: VeyonShortcut) {
        if (!commandRef.current || shortcutBusy) return;
        setShortcutBusy(true);
        try { await commandRef.current(shortcut); }
        catch (err) { setError(extractErrorDetail(err)); }
        finally { setShortcutBusy(false); }
    }
    const imageRef = useRef<HTMLImageElement>(null);
    const snapshotRequest = useRef<AbortController | null>(null);
    const recording = useScreenRecording(deviceId, deviceName, classroomName);
    const [recordingSettings, setRecordingSettings] = useState(false);
    const capture = recording.paused ? null : recording.options;
    const onRecordingFrame = recording.onFrame;
    const [savingSnapshot, setSavingSnapshot] = useState(false);
    useEffect(() => () => snapshotRequest.current?.abort(), [deviceId]);

    async function saveSnapshot() {
        if (snapshotRequest.current) return;
        const controller = new AbortController();
        snapshotRequest.current = controller;
        setSavingSnapshot(true);
        try {
            const blob = await getVeyonSnapshot(deviceId, controller.signal);
            if (controller.signal.aborted) return;
            downloadMedia(blob, mediaFilename(classroomName, deviceName, deviceId, "png"));
        } catch (err) {
            if (!controller.signal.aborted) setError(extractErrorDetail(err));
        } finally {
            if (snapshotRequest.current === controller) snapshotRequest.current = null;
            if (!controller.signal.aborted) setSavingSnapshot(false);
        }
    }
    const viewDocument = document;

    useEffect(() => {
        if (!popup) return;
        const timer = setInterval(() => { if (popup.closed) setPopup(null); }, 500);
        // The independent viewer may outlive the device dialog.
        return () => clearInterval(timer);
    }, [popup]);

    useEffect(() => {
        if (popup) return;
        let stopped = false;
        let currentUrl: string | null = null;
        let timer: ReturnType<typeof setTimeout> | undefined;

        let count = 0, measuredAt = performance.now();
        const fpsTimer = setInterval(() => {
            const now = performance.now();
            const value = Math.round(count * 1000 / (now - measuredAt));
            setFps(value); onFps?.(value); count = 0; measuredAt = now;
        }, 1000);
        const controller = new AbortController();
        async function refresh() {
            let delay = 1000;
            try {
                if (capture || viewDocument.visibilityState !== "hidden") {
                    const started = performance.now();
                    const preset = capture ? RECORDING_QUALITIES[capture.quality] : SCREEN_QUALITIES[screenQuality];
                    const blob = await getVeyonFrame(deviceId, controller.signal, preset?.width, preset?.quality);
                    if (stopped) return;
                    const next = URL.createObjectURL(blob);
                    const image = viewDocument.createElement("img");
                    image.src = next;
                    try { await image.decode(); }
                    catch (err) { URL.revokeObjectURL(next); throw err; }
                    if (stopped) { URL.revokeObjectURL(next); return; }
                    count++;
                    onRecordingFrame(image);
                    setSource(next); setError(null);
                    if (currentUrl) URL.revokeObjectURL(currentUrl);
                    currentUrl = next;
                    const elapsed = performance.now() - started;

                    // One request at a time; slow responses already provide backpressure.
                    const period = capture
                        ? 1000 / capture.fps
                        : 1000 / 30;
                    delay = Math.max(0, period - elapsed);
                }
            } catch (err) {
                if (!stopped) setError(extractErrorDetail(err));
                delay = 3000;
            }
            if (!stopped) timer = setTimeout(() => void refresh(), delay);
        }
        void refresh();
        return () => {
            stopped = true; controller.abort(); clearTimeout(timer); clearInterval(fpsTimer);
            if (currentUrl) URL.revokeObjectURL(currentUrl);
        };
    }, [deviceId, viewDocument, popup, capture, onRecordingFrame, onFps, screenQuality]);

    const [refreshing, setRefreshing] = useState(false);
    async function forceRefresh() {
        if (refreshing) return;
        setRefreshing(true);
        try { await refreshVeyonScreen(deviceId); setError(null); }
        catch (err) { setError(extractErrorDetail(err)); }
        finally {setRefreshing(false);}
    }

    async function toggleFullscreen() {
        try {
            if (viewDocument.fullscreenElement) await viewDocument.exitFullscreen();
            else if (imageRef.current?.requestFullscreen) await imageRef.current.requestFullscreen();
            else setError("Этот браузер не поддерживает полноэкранный режим. Откройте экран в отдельном окне.");
        } catch { setError("Не удалось открыть полноэкранный режим."); }
    }

    function openWindow() {
        const url = new URL(window.location.href);
        url.search = "";
        url.hash = "";
        url.searchParams.set("veyon_device", String(deviceId));
        if (deviceName) url.searchParams.set("veyon_device_name", deviceName);
        if (classroomName) url.searchParams.set("veyon_classroom_name", classroomName);
        if (control) url.searchParams.set("veyon_control", "1");
        const next = window.open(url.href, "_blank", "popup,width=1280,height=800");
        if (!next) { setError("Разрешите всплывающие окна для просмотра экрана в отдельном окне."); return; }
        next.opener = null;

        setPopup(next);
    }

    const recordingControls = !control && (recording.options ? <div className="device-recording-controls">
        <button type="button" className="secondary-button" aria-label="Отмена" title="Отменить запись" disabled={recording.busy} onClick={() => recording.finish(true)}><ScreenIcon name="cancel"/></button>
        <button type="button" className="secondary-button" aria-label={recording.paused ? "Продолжить" : "Пауза"} title={recording.paused ? "Продолжить запись" : "Приостановить запись"} disabled={recording.busy} onClick={recording.pause}><ScreenIcon name={recording.paused ? "play" : "pause"}/></button>
        <button type="button" className="success-button" aria-label={recording.busy ? "Сохранение…" : "Завершить"} title="Завершить и сохранить запись" disabled={recording.busy} onClick={() => recording.finish()}><ScreenIcon name="stop"/></button>
    </div> : <button type="button" className="danger-button" aria-label="Запись" title="Запись" disabled={recording.busy || !!popup || !source}
        onClick={() => setRecordingSettings(true)}><ScreenIcon name="record"/></button>);
    const screen = <div className="device-screen">
        {recording.options && <div className={`recording-timer${recording.paused ? " recording-paused" : ""}`} role="timer" aria-label="Длительность записи">
            {recording.paused ? "Пауза" : "●"} {recordingClock(recording.seconds)} / {recordingClock(RECORDING_MAX_SECONDS)}
        </div>}
        {recording.error && <div className="device-modal-error" role="alert">{recording.error}</div>}
        {recording.message && <p role="status">{recording.message}</p>}
        {error && <div className="device-modal-error" role="alert">{error}</div>}
        {!source && !error && <p role="status">Подключение к экрану...</p>}
        {source && (control ? <RemoteControlImage deviceId={deviceId} source={source} imageRef={imageRef} commandRef={commandRef} /> : <img ref={imageRef} src={source} alt="Экран устройства" />)}
        {error && source && <p className="muted">Показан последний полученный кадр.</p>}
    </div>;
    const snapshotButton = !control && <button type="button" className="success-button" aria-label={savingSnapshot ? "Сохранение…" : "Снимок"} title="Снимок" disabled={savingSnapshot}
        onClick={() => void saveSnapshot()}><ScreenIcon name="snapshot"/></button>;
    const refreshButton = <button type="button" className="secondary-button screen-quality-button"
        aria-label="Обновить экран" title="Обновить экран" disabled={refreshing}
        onMouseDown={event => event.preventDefault()} onClick={() => void forceRefresh()}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M20 7v5h-5M4 17v-5h5"/>
            <path d="M6.1 7a7 7 0 0 1 11.6-1L20 9M4 15l2.3 3A7 7 0 0 0 17.9 17"/>
        </svg>
    </button>;
    const qualityButton = <button type="button" className="secondary-button screen-quality-button" aria-label="Качество экрана" title="Качество экрана" onClick={() => setQualitySettings(true)}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="m9 3-.6 2.4-2 .9L4.2 6l-2 3.5 1.7 1.7v2l-1.7 1.7 2 3.5 2.2-.3 2 .9L9 21h4l.6-2.4 2-.9 2.2.3 2-3.5-1.7-1.7v-2l1.7-1.7-2-3.5-2.2.3-2-.9L13 3Z" />
            <circle cx="11" cy="12" r="3" />
        </svg>
    </button>;
    const toolbar = popup ? <div className="device-screen-toolbar" role="group" aria-label="Действия экрана">
        {snapshotButton}
            {recordingControls}
        <button type="button" className="secondary-button" aria-label="Показать окно" title="Показать окно" onClick={() => popup.focus()}><ScreenIcon name="window"/></button>
        <button type="button" className="secondary-button" aria-label="Вернуть в окно устройства" title="Вернуть в окно устройства" onClick={() => { popup.close(); setPopup(null); }}><ScreenIcon name="back"/></button>
        {refreshButton}
        {qualityButton}
    </div> : (
        <div className="device-screen-toolbar" role="group" aria-label="Действия экрана">
            {snapshotButton}
            {recordingControls}
            {control && <button type="button" className="secondary-button" aria-label="Esc" title="Отправить Esc" disabled={!source || shortcutBusy}
                onMouseDown={event => event.preventDefault()} onClick={() => void sendShortcut("escape")}>Esc</button>}
            {control && canSendAdminShortcut && <button type="button" className="danger-button" aria-label="Ctrl+Alt+Del" title="Отправить Ctrl+Alt+Del" disabled={!source || shortcutBusy}
                onMouseDown={event => event.preventDefault()} onClick={() => void sendShortcut("ctrl-alt-delete")}><ScreenIcon name="keyboard"/></button>}
            <button type="button" className="secondary-button" aria-label="На весь экран" title="На весь экран" disabled={!source} onClick={() => void toggleFullscreen()}><ScreenIcon name="fullscreen"/></button>
            {!standalone && <button type="button" className="secondary-button" aria-label="В отдельном окне" title="В отдельном окне" disabled={recording.busy || !!recording.options} onClick={openWindow}><ScreenIcon name="window"/></button>}
            {refreshButton}
        {qualityButton}
        </div>
    );
    return <>
        {standalone && <h3>{classroomName || "Аудитория"}: {deviceName || `PC-${deviceId}`} <span className="device-fps">({fps} FPS)</span></h3>}
        {qualitySettings && <ScreenQualitySettings value={screenQuality}
            onSave={quality => { saveScreenQuality(quality); setScreenQuality(quality); setQualitySettings(false); }}
            onClose={() => setQualitySettings(false)} />}
        {recordingSettings && <RecordingSettings busy={recording.busy}
            onStart={options => { void recording.start(options).then(() => setRecordingSettings(false)); }}
            onClose={() => setRecordingSettings(false)} />}
        <div className="device-screen-layout">
            {popup ? <p role="status">{control ? "Управление открыто в отдельном окне." : "Экран открыт в отдельном окне."}</p> : screen}
            {toolbar}
        </div>
    </>;
}
