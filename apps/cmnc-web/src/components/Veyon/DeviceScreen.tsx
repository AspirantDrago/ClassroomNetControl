import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { extractErrorDetail, getVeyonFrame, getVeyonSnapshot } from "../../api";
import "./Veyon.css";
import { RecordingSettings } from "./RecordingSettings";
import { useScreenRecording } from "./useScreenRecording";
import { downloadMedia, mediaFilename, recordingClock, RECORDING_MAX_SECONDS, RECORDING_QUALITIES } from "./recording";
import { RemoteControlImage } from "./RemoteControlImage";

export function DeviceScreen({ deviceId, deviceName, classroomName, standalone = false, control = false, toolbarTarget, onFps }: { deviceId: number; deviceName?: string; classroomName?: string; standalone?: boolean; control?: boolean; toolbarTarget?: HTMLElement | null; onFps?: (fps: number) => void }) {
    const [source, setSource] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [popup, setPopup] = useState<Window | null>(null);
    const [fps, setFps] = useState(0);
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
        let averageDuration = 33;
        let count = 0, measuredAt = performance.now();
        const fpsTimer = setInterval(() => {
            const now = performance.now();
            const value = Math.round(count * 10000 / (now - measuredAt)) / 10;
            setFps(value); onFps?.(value); count = 0; measuredAt = now;
        }, 1000);
        const controller = new AbortController();
        async function refresh() {
            let delay = 1000;
            try {
                if (capture || viewDocument.visibilityState !== "hidden") {
                    const started = performance.now();
                    const preset = capture ? RECORDING_QUALITIES[capture.quality] : undefined;
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
                    averageDuration = averageDuration * 0.7 + elapsed * 0.3;
                    // Adapt to network, server and image decoding time. Never
                    // overlap requests; cap at 10 fps with some capacity to spare.
                    const period = capture
                        ? Math.max(1000 / capture.fps, averageDuration * 1.05)
                        : Math.max(1000 / 30, averageDuration * 1.05);
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
    }, [deviceId, viewDocument, popup, capture, onRecordingFrame, onFps]);

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
        <span className={`recording-timer${recording.paused ? " recording-paused" : ""}`} role="timer" aria-label="Длительность записи">
            {recording.paused ? "Пауза" : "●"} {recordingClock(recording.seconds)} / {recordingClock(RECORDING_MAX_SECONDS)}
        </span>
        <button type="button" className="secondary-button" disabled={recording.busy} onClick={() => recording.finish(true)}>Отмена</button>
        <button type="button" className="secondary-button" disabled={recording.busy} onClick={recording.pause}>{recording.paused ? "Продолжить" : "Пауза"}</button>
        <button type="button" className="success-button" disabled={recording.busy} onClick={() => recording.finish()}>{recording.busy ? "Сохранение…" : "Завершить"}</button>
    </div> : <button type="button" className="danger-button" disabled={recording.busy || !!popup || !source}
        onClick={() => setRecordingSettings(true)}>Запись</button>);
    const screen = <div className="device-screen">
        {recording.error && <div className="device-modal-error" role="alert">{recording.error}</div>}
        {recording.message && <p role="status">{recording.message}</p>}
        {error && <div className="device-modal-error" role="alert">{error}</div>}
        {!source && !error && <p role="status">Подключение к экрану...</p>}
        {source && (control ? <RemoteControlImage deviceId={deviceId} source={source} imageRef={imageRef} /> : <img ref={imageRef} src={source} alt="Экран устройства" />)}
        {error && source && <p className="muted">Показан последний полученный кадр.</p>}
    </div>;
    const snapshotButton = !control && <button type="button" className="success-button" disabled={savingSnapshot}
        onClick={() => void saveSnapshot()}>{savingSnapshot ? "Сохранение…" : "Снимок"}</button>;
    const toolbar = popup ? <div className="device-screen-toolbar">
        {snapshotButton}
            {recordingControls}
        <button type="button" className="secondary-button" onClick={() => popup.focus()}>Показать окно</button>
        <button type="button" className="secondary-button" onClick={() => { popup.close(); setPopup(null); }}>Вернуть в окно устройства</button>
    </div> : (
        <div className="device-screen-toolbar">
            {snapshotButton}
            {recordingControls}
            <button type="button" className="secondary-button" disabled={!source} onClick={() => void toggleFullscreen()}>На весь экран</button>
            {!standalone && <button type="button" className="secondary-button" disabled={recording.busy || !!recording.options} onClick={openWindow}>В отдельном окне</button>}
        </div>
    );
    return <>
        {standalone && <h3>{classroomName || "Аудитория"}: {deviceName || `PC-${deviceId}`} <span className="muted">({fps} FPS)</span></h3>}
        {toolbarTarget ? createPortal(toolbar, toolbarTarget) : toolbar}
        {recordingSettings && <RecordingSettings busy={recording.busy}
            onStart={options => { void recording.start(options).then(() => setRecordingSettings(false)); }}
            onClose={() => setRecordingSettings(false)} />}
        {popup ? <p role="status">{control ? "Управление открыто в отдельном окне." : "Экран открыт в отдельном окне."}</p> : screen}
    </>;
}
