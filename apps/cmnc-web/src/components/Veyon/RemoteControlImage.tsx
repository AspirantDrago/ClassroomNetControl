import { useEffect, useState, type RefObject } from "react";
import { extractErrorDetail, veyonControl, type VeyonInputEvent } from "../../api";

const special: Record<string, number> = {
    Backspace: 0xff08, Tab: 0xff09, Enter: 0xff0d, Delete: 0xffff, Insert: 0xff63,
    Home: 0xff50, End: 0xff57, PageUp: 0xff55, PageDown: 0xff56,
    ArrowLeft: 0xff51, ArrowUp: 0xff52, ArrowRight: 0xff53, ArrowDown: 0xff54,
    Shift: 0xffe1, Control: 0xffe3, Alt: 0xffe9, Meta: 0xffeb,
    CapsLock: 0xffe5, NumLock: 0xff7f, ScrollLock: 0xff14, PrintScreen: 0xff61,
    Pause: 0xff13, ContextMenu: 0xff67, AltGraph: 0xfe03,
};
function remoteKey(key: string, location = 0): number | null {
    if (special[key]) return special[key] + (location === 2 && ["Shift", "Control", "Alt", "Meta"].includes(key) ? 1 : 0);
    if (/^F([1-9]|1\d|2[0-4])$/.test(key)) return 0xffbd + Number(key.slice(1));
    if ([...key].length !== 1) return null;
    const point = key.codePointAt(0)!;
    return point <= 255 ? point : 0x01000000 + point;
}

export function RemoteControlImage({deviceId, source, imageRef}: {
    deviceId: number; source: string; imageRef: RefObject<HTMLImageElement | null>;
}) {
    const [status, setStatus] = useState("Нажмите на изображение для управления. Esc — отпустить мышь и клавиатуру.");
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        const image = imageRef.current!;
        let token: string | null = null;
        let active = false, disposed = false, epoch = 0, pointerButtons = 0;
        let starting: Promise<string | null> | null = null;
        let pumping: Promise<void> | null = null;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let queue: VeyonInputEvent[] = [];
        const pressed = new Map<string, number>();
        function stop() {
            active = false; pointerButtons = 0; epoch++; queue = []; pressed.clear(); clearTimeout(timer); timer = undefined;
            const current = token; token = null;
            // A stop is ordered after the in-flight input batch, including clicks.
            if (current) void (pumping ?? Promise.resolve()).finally(() => veyonControl(deviceId, "stop", {token: current})).catch(() => {});
            if (!disposed) setStatus("Нажмите на изображение для управления. Esc — отпустить мышь и клавиатуру.");
        }
        function start() {
            if (active) return;
            active = true; const version = ++epoch;
            setError(null); setStatus("Подключение управления...");
            starting = veyonControl(deviceId, "start", {}).then(async result => {
                if (!result.token) throw new Error("Сервер не вернул сеанс управления");
                if (disposed || !active || epoch !== version) {
                    await veyonControl(deviceId, "stop", {token: result.token}); return null;
                }
                token = result.token; setStatus("Управление активно. Esc — отпустить мышь и клавиатуру.");
                return token;
            }).catch(err => { if (!disposed && epoch === version) { stop(); setError(extractErrorDetail(err)); } return null; });
        }
        function pump() {
            if (pumping || !active) return;
            const version = epoch;
            pumping = (async () => {
                const current = token ?? await starting;
                if (!current || !active || version !== epoch) return;
                while (queue.length && active && version === epoch) {
                    const events = queue.splice(0, 64);
                    await veyonControl(deviceId, "input", {token: current, events});
                }
            })().catch(err => { if (!disposed) { stop(); setError(extractErrorDetail(err)); } }).finally(() => {
                pumping = null;
                if (active && queue.length) timer = setTimeout(() => { timer = undefined; pump(); }, 20);
            });
        }
        function enqueue(event: VeyonInputEvent, move = false) {
            if (!active) return;
            const last = queue.at(-1);
            if (move && last?.type === "pointer" && last.buttons === (event as {buttons: number}).buttons) queue[queue.length-1] = event;
            else queue.push(event);
            if (queue.length > 256) { stop(); setError("Соединение не успевает передавать ввод. Подключитесь снова."); return; }
            if (!timer) timer = setTimeout(() => { timer = undefined; pump(); }, move ? 20 : 0);
        }
        function position(event: MouseEvent | PointerEvent | WheelEvent, clamp = false) {
            const rect = image.getBoundingClientRect();
            const scale = Math.min(rect.width / image.naturalWidth, rect.height / image.naturalHeight);
            const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
            const x = (event.clientX - rect.left - (rect.width-width)/2) / width;
            const y = (event.clientY - rect.top - (rect.height-height)/2) / height;
            if (!Number.isFinite(x) || !Number.isFinite(y) || (!clamp && (x<0 || x>1 || y<0 || y>1))) return null;
            return {x: Math.max(0, Math.min(1,x)), y: Math.max(0, Math.min(1,y))};
        }
        function pointer(event: PointerEvent) {
            if (!event.isPrimary) return;
            const down = event.type === "pointerdown";
            const point = position(event, !down);
            if (!point || (!active && !down)) return;
            event.preventDefault(); event.stopPropagation();
            if (down) { image.focus({preventScroll: true}); start(); image.setPointerCapture(event.pointerId); }
            const buttons = (event.buttons&1) | ((event.buttons&4)>>1) | ((event.buttons&2)<<1);
            pointerButtons = buttons;
            enqueue({type:"pointer", ...point, buttons}, event.type === "pointermove");
        }
        function key(event: KeyboardEvent) {
            if (!active) return;
            event.preventDefault(); event.stopPropagation();
            if (event.key === "Escape") {
                stop(); if (document.fullscreenElement) void document.exitFullscreen(); return;
            }
            const down = event.type === "keydown";
            const code = down ? remoteKey(event.key, event.location) : pressed.get(event.code);
            if (!code) return;
            if (down) pressed.set(event.code, code); else pressed.delete(event.code);
            enqueue({type:"key", key:code, pressed:down});
        }
        function wheel(event: WheelEvent) {
            const point = position(event);
            if (!active || !point) return;
            event.preventDefault(); event.stopPropagation();
            const buttons = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? (event.deltaY<0 ? 8 : 16) : (event.deltaX<0 ? 32 : 64);
            enqueue({type:"pointer", ...point, buttons: buttons | pointerButtons}); enqueue({type:"pointer", ...point, buttons:pointerButtons});
        }
        const context = (event: Event) => event.preventDefault();
        const visibility = () => { if (document.hidden) stop(); };
        const fullscreen = () => { if (!document.fullscreenElement) stop(); };
        for (const type of ["pointerdown", "pointermove", "pointerup"] as const) image.addEventListener(type, pointer);
        image.addEventListener("pointercancel", stop);
        image.addEventListener("keydown", key); image.addEventListener("keyup", key);
        image.addEventListener("wheel", wheel, {passive:false}); image.addEventListener("contextmenu", context);
        image.addEventListener("blur", stop); window.addEventListener("blur", stop);
        document.addEventListener("visibilitychange", visibility);
        document.addEventListener("fullscreenchange", fullscreen);
        const heartbeat = setInterval(() => {
            if (token && active && !pumping) {
                pumping = veyonControl(deviceId, "input", {token, events:[]}).then(() => {}).catch(err => { stop(); if (!disposed) setError(extractErrorDetail(err)); }).finally(() => { pumping = null; if (queue.length) pump(); });
            }
        }, 2000);
        return () => {
            disposed = true; stop(); clearInterval(heartbeat);
            for (const type of ["pointerdown", "pointermove", "pointerup"] as const) image.removeEventListener(type, pointer);
            image.removeEventListener("pointercancel", stop);
            image.removeEventListener("keydown", key); image.removeEventListener("keyup", key);
            image.removeEventListener("wheel", wheel); image.removeEventListener("contextmenu", context);
            image.removeEventListener("blur", stop); window.removeEventListener("blur", stop);
            document.removeEventListener("visibilitychange", visibility);
            document.removeEventListener("fullscreenchange", fullscreen);
        };
    }, [deviceId, imageRef]);
    return <>
        {error && <div className="device-modal-error" role="alert">{error}</div>}
        <img ref={imageRef} src={source} alt="Управление устройством" tabIndex={0} draggable={false} className="device-control-image" />
        <p className="muted" role="status">{status}</p>
    </>;
}
