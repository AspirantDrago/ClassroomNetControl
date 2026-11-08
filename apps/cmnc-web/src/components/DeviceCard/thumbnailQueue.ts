import { THUMBNAIL_CONCURRENCY } from "../../config/refreshIntervals";
import { getVeyonFrame } from "../../api";

type Job = { signal: AbortSignal; start: () => void; cancel: () => void };
let active = 0;
const waiting: Job[] = [];
function pump() {
    while (active < THUMBNAIL_CONCURRENCY && waiting.length) {
        const job = waiting.shift()!;
        if (job.signal.aborted) job.cancel();
        else job.start();
    }
}

// Keep overview previews from occupying all Veyon connections at once.
export function requestThumbnail(deviceId: number, signal: AbortSignal): Promise<Blob> {
    return new Promise((resolve, reject) => {
        const abort = () => {
            const index = waiting.indexOf(job);
            if (index >= 0) waiting.splice(index, 1);
            reject(new DOMException("Aborted", "AbortError"));
        };
        const job: Job = {
            signal,
            cancel: abort,
            start: () => {
                signal.removeEventListener("abort", abort);
                active++;
                void getVeyonFrame(deviceId, signal, 320).then(resolve, reject).finally(() => { active--; pump(); });
            },
        };
        if (signal.aborted) { abort(); return; }
        signal.addEventListener("abort", abort, {once: true});
        waiting.push(job); pump();
    });
}
