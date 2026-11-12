import { useCallback, useEffect, useRef, useState } from "react";
import { extractErrorDetail, refreshVeyonScreen } from "../../api";

const configuredInterval = Number(import.meta.env.VITE_FULL_FRAME_REFRESH_INTERVAL_MS);
const interval = Number.isFinite(configuredInterval) && configuredInterval > 0 ? configuredInterval : 5000;

export function useFullFrameRefresh(deviceId: number, enabled: boolean, onError: (error: string | null) => void) {
    const request = useRef<AbortController | null>(null);
    const [refreshing, setRefreshing] = useState(false);
    const refresh = useCallback(async () => {
        if (request.current) return;
        const controller = new AbortController();
        request.current = controller;
        setRefreshing(true);
        try {
            await refreshVeyonScreen(deviceId, controller.signal);
            if (!controller.signal.aborted) onError(null);
        } catch (err) {
            if (!controller.signal.aborted) onError(extractErrorDetail(err));
        } finally {
            if (request.current === controller) {
                request.current = null;
                setRefreshing(false);
            }
        }
    }, [deviceId, onError]);
    useEffect(() => {
        if (!enabled) return;
        // Defer to the next task so StrictMode's setup/cleanup cannot send twice.
        const initial = window.setTimeout(() => void refresh(), 0);
        const timer = window.setInterval(() => void refresh(), interval);
        return () => {
            window.clearTimeout(initial);
            window.clearInterval(timer);
            request.current?.abort();
        };
    }, [enabled, refresh]);
    return {refreshing, refresh};
}
