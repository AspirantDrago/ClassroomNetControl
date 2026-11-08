import { finalizeWebm } from "./webm";

export const RECORDING_QUALITIES = {
    high: { label: "Высокое — до 1920 px", width: 1920, quality: 95, bitrate: 6_000_000 },
    medium: { label: "Среднее — до 1280 px", width: 1280, quality: 85, bitrate: 3_000_000 },
    low: { label: "Экономное — до 854 px", width: 854, quality: 70, bitrate: 1_200_000 },
};
export type RecordingQuality = keyof typeof RECORDING_QUALITIES;
export type RecordingOptions = { quality: RecordingQuality; fps: number };

const configuredLimit = Number(import.meta.env.VITE_RECORDING_MAX_DURATION_SECONDS);
export const RECORDING_MAX_SECONDS = Number.isSafeInteger(configuredLimit) && configuredLimit > 0 ? configuredLimit : 5400;

export function recordingClock(seconds: number): string {
    const value = Math.max(0, Math.floor(seconds));
    return [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60].map(part => String(part).padStart(2, "0")).join(":");
}

export function mediaFilename(classroom: string | undefined, device: string | undefined, deviceId: number, extension: string, date = new Date()): string {
    const name = `${classroom?.trim() || "Аудитория"}_${device?.trim() || `PC-${deviceId}`}`.replace(/[<>:"/\\|?*]/g, "_").replace(/\p{Cc}/gu, "_").replace(/[. ]+$/g, "").slice(0, 180);
    const pad = (value: number) => String(value).padStart(2, "0");
    return `${name}_${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}_${pad(date.getHours())}-${pad(date.getMinutes())}-${pad(date.getSeconds())}.${extension}`;
}

export function downloadMedia(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = filename;
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function recordingFormat(): { mimeType: string; extension: string; label: string } {
    if (typeof MediaRecorder === "undefined" || !HTMLCanvasElement.prototype.captureStream) throw new Error("Этот браузер не поддерживает запись экрана.");
    const formats = [
        { mimeType: "video/webm;codecs=vp9", extension: "webm", label: "WebM / VP9" },
        { mimeType: "video/mp4;codecs=avc1.42E01E", extension: "mp4", label: "MP4 / H.264" },
        { mimeType: "video/mp4", extension: "mp4", label: "MP4" },
        { mimeType: "video/webm;codecs=vp8", extension: "webm", label: "WebM / VP8" },
    ];
    const format = formats.find(value => MediaRecorder.isTypeSupported(value.mimeType));
    if (!format) throw new Error("Браузер не поддерживает совместимый формат записи.");
    return format;
}

interface RecordingSink {
    write(blob: Blob): Promise<void>;
    finish(seconds: number): Promise<void>;
    abort(): Promise<void>;
}
type WritableRecording = { write(blob: Blob): Promise<void>; close(): Promise<void>; abort(): Promise<void> };
type SavePicker = (options: { suggestedName: string; types: { description: string; accept: Record<string, string[]> }[] }) => Promise<{ createWritable(): Promise<WritableRecording>; getFile(): Promise<File> }>;

function transactionDone(transaction: IDBTransaction): Promise<void> {
    return new Promise((resolve, reject) => {
        transaction.oncomplete = () => resolve();
        transaction.onerror = transaction.onabort = () => reject(transaction.error ?? new Error("Не удалось сохранить фрагмент записи"));
    });
}

// Persist chunks as they arrive; a 90 minute recording must not live in a JS array.
// Chromium can write directly to a chosen file. Other browsers use disk-backed IDB.
export async function recordingSink(filename: string, mimeType: string): Promise<RecordingSink> {
    const picker = (window as Window & { showSaveFilePicker?: SavePicker }).showSaveFilePicker;
    if (picker) {
        const handle = await picker.call(window, { suggestedName: filename, types: [{ description: "Запись экрана", accept: { [mimeType.split(";")[0]]: [filename.endsWith(".mp4") ? ".mp4" : ".webm"] } }] });
        const writer = await handle.createWritable();
        return { write: blob => writer.write(blob), finish: async seconds => {
            await writer.close();
            if (mimeType.startsWith("video/webm")) {
                const fixed = await finalizeWebm(await handle.getFile(), seconds);
                const output = await handle.createWritable();
                try { await output.write(fixed); await output.close(); }
                catch (error) { await output.abort(); throw error; }
            }
        }, abort: () => writer.abort() };
    }
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open("cmnc-screen-recordings", 1);
        request.onupgradeneeded = () => request.result.createObjectStore("chunks");
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
    const id = crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
    const range = IDBKeyRange.bound([id, 0], [id, Number.MAX_SAFE_INTEGER]);
    let sequence = 0;
    async function clear() {
        const transaction = database.transaction("chunks", "readwrite");
        transaction.objectStore("chunks").delete(range);
        await transactionDone(transaction);
        database.close();
    }
    return {
        async write(blob) {
            const transaction = database.transaction("chunks", "readwrite");
            transaction.objectStore("chunks").put(blob, [id, sequence++]);
            await transactionDone(transaction);
        },
        async finish(seconds) {
            try {
                const transaction = database.transaction("chunks", "readonly");
                const request = transaction.objectStore("chunks").getAll(range);
                const parts = await new Promise<Blob[]>((resolve, reject) => {
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                });
                if (parts.length) {
                    const original = new Blob(parts, { type: mimeType });
                    downloadMedia(mimeType.startsWith("video/webm") ? await finalizeWebm(original, seconds) : original, filename);
                }
            } finally { await clear(); }
        },
        abort: clear,
    };
}

export class ScreenRecording {
    readonly canvas = document.createElement("canvas");
    readonly recorder: MediaRecorder;
    readonly done: Promise<void>;
    readonly options: RecordingOptions;
    private sink: RecordingSink;
    private stream: MediaStream;
    private queue = Promise.resolve();
    private bytesPending = 0;
    private writeError: unknown;
    private cancelled = false;
    private stopping = false;
    private elapsed = 0;
    private resumedAt = performance.now();
    private limitTimer?: ReturnType<typeof setTimeout>;

    constructor(image: HTMLImageElement, options: RecordingOptions, format: ReturnType<typeof recordingFormat>, sink: RecordingSink) {
        this.options = options;
        this.sink = sink;
        const preset = RECORDING_QUALITIES[options.quality];
        const scale = Math.min(1, preset.width / image.naturalWidth);
        // Even dimensions are required by common video encoders; never upscale.
        this.canvas.width = Math.max(2, Math.floor(image.naturalWidth * scale / 2) * 2);
        this.canvas.height = Math.max(2, Math.floor(image.naturalHeight * scale / 2) * 2);
        this.draw(image);
        this.stream = this.canvas.captureStream(options.fps);
        try {
            this.recorder = new MediaRecorder(this.stream, { mimeType: format.mimeType, videoBitsPerSecond: preset.bitrate });
        } catch (error) { this.stream.getTracks().forEach(track => track.stop()); throw error; }
        this.recorder.ondataavailable = event => {
            if (!event.data.size || this.cancelled || this.writeError) return;
            this.bytesPending += event.data.size;
            this.queue = this.queue.then(async () => {
                if (!this.cancelled && !this.writeError) await this.sink.write(event.data);
            }).catch(error => { this.writeError = error; void this.stop(); }).finally(() => { this.bytesPending -= event.data.size; });
            if (this.bytesPending > 64 * 1024 * 1024) {
                this.writeError = new Error("Носитель не успевает сохранять запись. Сохранена доступная часть.");
                void this.stop();
            }
        };
        this.done = new Promise<void>((resolve, reject) => {
            this.recorder.onerror = () => { this.writeError = new Error("Браузер прервал кодирование. Сохранена доступная часть записи."); void this.stop(); };
            this.recorder.onstop = () => {
                clearTimeout(this.limitTimer);
                this.stream.getTracks().forEach(track => track.stop());
                void this.queue.then(async () => {
                    if (this.cancelled) await this.sink.abort();
                    else await this.sink.finish(this.seconds);
                    if (this.writeError) throw this.writeError;
                }).then(resolve, reject);
            };
        });
        // Attach a handler immediately, even when callers are still starting up.
        void this.done.catch(() => {});
        try { this.recorder.start(1000); }
        catch (error) { this.stream.getTracks().forEach(track => track.stop()); throw error; }
        this.scheduleLimit();
    }

    get paused() { return this.recorder.state === "paused"; }
    get discarded() { return this.cancelled; }
    get seconds() { return Math.min(RECORDING_MAX_SECONDS, (this.elapsed + (this.paused || this.stopping ? 0 : performance.now() - this.resumedAt)) / 1000); }
    get finalizing() { return this.stopping; }

    draw(image: HTMLImageElement) {
        if (this.recorder && (this.paused || this.stopping)) return;
        const context = this.canvas.getContext("2d", { alpha: false });
        if (!context) throw new Error("Браузер не поддерживает запись изображения");
        context.fillStyle = "#000"; context.fillRect(0, 0, this.canvas.width, this.canvas.height);
        const scale = Math.min(this.canvas.width / image.naturalWidth, this.canvas.height / image.naturalHeight);
        const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
        context.drawImage(image, (this.canvas.width - width) / 2, (this.canvas.height - height) / 2, width, height);
    }

    private scheduleLimit() {
        clearTimeout(this.limitTimer);
        this.limitTimer = setTimeout(() => void this.stop(), Math.min(2_147_483_647, Math.max(0, (RECORDING_MAX_SECONDS - this.seconds) * 1000)));
    }

    pause() {
        if (this.stopping) return;
        if (this.paused) {
            this.resumedAt = performance.now(); this.recorder.resume(); this.scheduleLimit();
        } else {
            this.elapsed += performance.now() - this.resumedAt;
            this.recorder.pause(); clearTimeout(this.limitTimer);
        }
    }

    stop(cancel = false): Promise<void> {
        if (this.stopping) return this.done;
        if (!this.paused) this.elapsed += performance.now() - this.resumedAt;
        this.stopping = true; this.cancelled = cancel;
        clearTimeout(this.limitTimer);
        if (this.recorder.state !== "inactive") this.recorder.stop();
        return this.done;
    }
}
