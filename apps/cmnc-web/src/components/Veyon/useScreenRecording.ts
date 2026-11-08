import { useCallback, useEffect, useRef, useState } from "react";
import { extractErrorDetail, getVeyonFrame } from "../../api";
import { mediaFilename, RECORDING_MAX_SECONDS, RECORDING_QUALITIES, recordingFormat, recordingSink, ScreenRecording, type RecordingOptions } from "./recording";

export function useScreenRecording(deviceId: number, deviceName?: string, classroomName?: string) {
    const session = useRef<ScreenRecording | null>(null);
    const starting = useRef<AbortController | null>(null);
    const mounted = useRef(false);
    const [options, setOptions] = useState<RecordingOptions | null>(null);
    const [busy, setBusy] = useState(false);
    const [seconds, setSeconds] = useState(0);
    const [paused, setPaused] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);

    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
            starting.current?.abort();
            // Leaving this tab/dialog finishes and saves, rather than discarding.
            void session.current?.stop();
        };
    }, []);

    useEffect(() => {
        if (!options) return;
        const timer = setInterval(() => {
            const current = session.current;
            if (!current) return;
            setSeconds(current.seconds);
            if (current.finalizing) setBusy(true);
            if (current.seconds >= RECORDING_MAX_SECONDS && !current.finalizing) void current.stop();
        }, 250);
        const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); };
        window.addEventListener("beforeunload", beforeUnload);
        return () => { clearInterval(timer); window.removeEventListener("beforeunload", beforeUnload); };
    }, [options]);

    async function start(selected: RecordingOptions) {
        if (session.current || starting.current) return;
        const controller = new AbortController();
        starting.current = controller;
        setBusy(true); setError(null); setMessage(null);
        let sink: Awaited<ReturnType<typeof recordingSink>> | undefined;
        let imageUrl: string | undefined;
        try {
            const format = recordingFormat();
            // The picker must run directly from the user's click, before fetching.
            sink = await recordingSink(mediaFilename(classroomName, deviceName, deviceId, format.extension), format.mimeType);
            const preset = RECORDING_QUALITIES[selected.quality];
            const blob = await getVeyonFrame(deviceId, controller.signal, preset.width, preset.quality);
            if (controller.signal.aborted) { await sink.abort(); return; }
            imageUrl = URL.createObjectURL(blob);
            const image = new Image(); image.src = imageUrl;
            await image.decode();
            if (controller.signal.aborted) { await sink.abort(); return; }
            const current = new ScreenRecording(image, selected, format, sink);
            session.current = current;
            setOptions(selected); setSeconds(0); setPaused(false);
            void current.done.then(() => {
                if (mounted.current) setMessage(current.discarded ? "Запись отменена." : "Запись завершена.");
            }).catch(err => {
                if (mounted.current) setError(extractErrorDetail(err));
            }).finally(() => {
                if (session.current === current) session.current = null;
                if (mounted.current) { setOptions(null); setBusy(false); setPaused(false); }
            });
        } catch (err) {
            await sink?.abort().catch(() => {});
            if (mounted.current && !controller.signal.aborted && !(err instanceof DOMException && err.name === "AbortError")) setError(extractErrorDetail(err));
        } finally {
            if (imageUrl) URL.revokeObjectURL(imageUrl);
            if (starting.current === controller) starting.current = null;
            if (mounted.current) setBusy(false);
        }
    }

    function pause() {
        const current = session.current;
        if (!current || current.finalizing) return;
        current.pause(); setPaused(current.paused); setSeconds(current.seconds);
    }

    function finish(cancel = false) {
        const current = session.current;
        if (!current) return;
        setBusy(true);
        void current.stop(cancel);
    }

    const onFrame = useCallback((image: HTMLImageElement) => session.current?.draw(image), []);
    return { options, busy, seconds, paused, error, message, start, pause, finish, onFrame };
}
