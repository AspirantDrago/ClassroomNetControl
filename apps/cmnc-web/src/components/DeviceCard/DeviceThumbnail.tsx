import { useEffect, useState, type RefObject } from "react";
import { REFRESH_INTERVALS } from "../../config/refreshIntervals";
import { requestThumbnail } from "./thumbnailQueue";

export function DeviceThumbnail({deviceId, title, cardRef}: {
    deviceId: number; title: string; cardRef: RefObject<HTMLDivElement | null>;
}) {
    const [source, setSource] = useState<string | null>(null);
    useEffect(() => {
        let disposed = false, inViewport = false, active = false, generation = 0;
        let currentUrl: string | null = null;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let controller: AbortController | null = null;
        function clearFrame() {
            if (currentUrl) URL.revokeObjectURL(currentUrl);
            currentUrl = null;
            if (!disposed) setSource(null);
        }
        async function refresh(version: number) {
            const started = performance.now();
            controller = new AbortController();
            try {
                const blob = await requestThumbnail(deviceId, controller.signal);
                if (disposed || !active || version !== generation) return;
                const next = URL.createObjectURL(blob);
                const image = new Image(); image.src = next;
                try { await image.decode(); }
                catch (error) { URL.revokeObjectURL(next); throw error; }
                if (disposed || !active || version !== generation) { URL.revokeObjectURL(next); return; }
                if (currentUrl) URL.revokeObjectURL(currentUrl);
                currentUrl = next; setSource(next);
            } catch {
                if (!disposed && active && version === generation) clearFrame();
            }
            if (!disposed && active && version === generation) {
                timer = setTimeout(() => void refresh(version), Math.max(0, REFRESH_INTERVALS.thumbnails - (performance.now() - started)));
            }
        }
        function update() {
            const enabled = inViewport && !document.hidden;
            if (active === enabled) return;
            active = enabled; generation++;
            clearTimeout(timer); controller?.abort();
            if (active) void refresh(generation); else clearFrame();
        }
        const observer = typeof IntersectionObserver !== "undefined" ? new IntersectionObserver(entries => {
            inViewport = entries.some(entry => entry.isIntersecting); update();
        }) : null;
        if (observer && cardRef.current) observer.observe(cardRef.current);
        else { inViewport = true; update(); }
        document.addEventListener("visibilitychange", update);
        return () => {
            disposed = true; active = false; generation++;
            clearTimeout(timer); controller?.abort(); observer?.disconnect();
            document.removeEventListener("visibilitychange", update);
            clearFrame();
        };
    }, [deviceId, cardRef]);
    return source ? <img className="device-thumbnail" src={source} alt={`Экран устройства ${title}`} draggable={false} onError={() => setSource(null)} /> : null;
}
