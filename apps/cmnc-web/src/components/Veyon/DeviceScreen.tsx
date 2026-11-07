import { useEffect, useState } from "react";
import { extractErrorDetail, getVeyonFrame } from "../../api";
import "./Veyon.css";

export function DeviceScreen({ deviceId }: { deviceId: number }) {
    const [source, setSource] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        let stopped = false;
        let currentUrl: string | null = null;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const controller = new AbortController();
        async function refresh() {
            let delay = 700;
            try {
                if (document.visibilityState !== "hidden") {
                    const blob = await getVeyonFrame(deviceId, controller.signal);
                    if (stopped) return;
                    const next = URL.createObjectURL(blob);
                    setSource(next); setError(null);
                    if (currentUrl) URL.revokeObjectURL(currentUrl);
                    currentUrl = next;
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
    }, [deviceId]);
    return <div className="device-screen">
        {error && <div className="device-modal-error" role="alert">{error}</div>}
        {!source && !error && <p role="status">Подключение к экрану...</p>}
        {source && <img src={source} alt="Экран устройства" />}
        <p className="muted">Просмотр экрана через Veyon. {error && source ? "Показан последний полученный кадр." : ""}</p>
    </div>;
}
