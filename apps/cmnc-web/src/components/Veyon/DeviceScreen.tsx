import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { extractErrorDetail, getVeyonFrame, getVeyonSnapshot } from "../../api";
import "./Veyon.css";
import { RemoteControlImage } from "./RemoteControlImage";

export function DeviceScreen({ deviceId, deviceName, standalone = false, control = false, toolbarTarget }: { deviceId: number; deviceName?: string; standalone?: boolean; control?: boolean; toolbarTarget?: HTMLElement | null }) {
    const [source, setSource] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [popup, setPopup] = useState<Window | null>(null);
    const imageRef = useRef<HTMLImageElement>(null);
    const snapshotRequest = useRef<AbortController | null>(null);
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
            const now = new Date();
            const pad = (value: number) => String(value).padStart(2, "0");
            const timestamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;
            const name = (deviceName?.trim() || `PC-${deviceId}`).replace(/[<>:"/\\|?*]/g, "_").replace(/\p{Cc}/gu, "_").replace(/[. ]+$/g, "").slice(0, 100) || `PC-${deviceId}`;
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `${name}_${timestamp}.png`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            // Let the browser finish handing the file to its download manager.
            window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
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
        let averageDuration = 80;
        const controller = new AbortController();
        async function refresh() {
            let delay = 1000;
            try {
                if (viewDocument.visibilityState !== "hidden") {
                    const started = performance.now();
                    const blob = await getVeyonFrame(deviceId, controller.signal);
                    if (stopped) return;
                    const next = URL.createObjectURL(blob);
                    const image = viewDocument.createElement("img");
                    image.src = next;
                    try { await image.decode(); }
                    catch (err) { URL.revokeObjectURL(next); throw err; }
                    if (stopped) { URL.revokeObjectURL(next); return; }
                    setSource(next); setError(null);
                    if (currentUrl) URL.revokeObjectURL(currentUrl);
                    currentUrl = next;
                    const elapsed = performance.now() - started;
                    averageDuration = averageDuration * 0.7 + elapsed * 0.3;
                    // Adapt to network, server and image decoding time. Never
                    // overlap requests; cap at 10 fps with some capacity to spare.
                    const period = Math.min(1000, Math.max(100, averageDuration * 1.25));
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
            stopped = true; controller.abort(); clearTimeout(timer);
            if (currentUrl) URL.revokeObjectURL(currentUrl);
        };
    }, [deviceId, viewDocument, popup]);

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
        if (control) url.searchParams.set("veyon_control", "1");
        const next = window.open(url.href, "_blank", "popup,width=1280,height=800");
        if (!next) { setError("Разрешите всплывающие окна для просмотра экрана в отдельном окне."); return; }
        next.opener = null;

        setPopup(next);
    }

    const screen = <div className="device-screen">
        {error && <div className="device-modal-error" role="alert">{error}</div>}
        {!source && !error && <p role="status">Подключение к экрану...</p>}
        {source && (control ? <RemoteControlImage deviceId={deviceId} source={source} imageRef={imageRef} /> : <img ref={imageRef} src={source} alt="Экран устройства" />)}
        {error && source && <p className="muted">Показан последний полученный кадр.</p>}
    </div>;
    const snapshotButton = !control && <button type="button" className="secondary-button" disabled={savingSnapshot}
        onClick={() => void saveSnapshot()}>{savingSnapshot ? "Сохранение…" : "Снимок"}</button>;
    const toolbar = popup ? <div className="device-screen-toolbar">
        {snapshotButton}
        <button type="button" className="secondary-button" onClick={() => popup.focus()}>Показать окно</button>
        <button type="button" className="secondary-button" onClick={() => { popup.close(); setPopup(null); }}>Вернуть в окно устройства</button>
    </div> : (
        <div className="device-screen-toolbar">
            {snapshotButton}
            <button type="button" className="secondary-button" disabled={!source} onClick={() => void toggleFullscreen()}>На весь экран</button>
            {!standalone && <button type="button" className="secondary-button" onClick={openWindow}>В отдельном окне</button>}
        </div>
    );
    return <>
        {toolbarTarget ? createPortal(toolbar, toolbarTarget) : toolbar}
        {popup ? <p role="status">{control ? "Управление открыто в отдельном окне." : "Экран открыт в отдельном окне."}</p> : screen}
    </>;
}
