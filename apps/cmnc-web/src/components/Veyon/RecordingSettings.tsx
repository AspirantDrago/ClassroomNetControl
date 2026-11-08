import { useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { recordingClock, recordingFormat, RECORDING_MAX_SECONDS, RECORDING_QUALITIES, type RecordingOptions, type RecordingQuality } from "./recording";

export function RecordingSettings({ busy, onStart, onClose }: { busy: boolean; onStart: (options: RecordingOptions) => void; onClose: () => void }) {
    const [quality, setQuality] = useState<RecordingQuality>("high");
    const [fps, setFps] = useState(10);
    const dialog = useRef<HTMLDivElement>(null);
    let format: string;
    let unsupported = false;
    try { format = recordingFormat().label; }
    catch { format = "Этот браузер не поддерживает запись экрана."; unsupported = true; }

    function keyDown(event: KeyboardEvent) {
        event.stopPropagation();
        if (event.key === "Escape" && !busy) onClose();
        if (event.key !== "Tab") return;
        const nodes = dialog.current?.querySelectorAll<HTMLElement>("button:not(:disabled), select:not(:disabled)");
        if (!nodes?.length) return;
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }

    return createPortal(<div className="modal-backdrop recording-settings-backdrop" onMouseDown={event => { event.stopPropagation(); if (event.target === event.currentTarget && !busy) onClose(); }} onClick={event => event.stopPropagation()}>
        <div ref={dialog} className="modal-card recording-settings" role="dialog" aria-modal="true" aria-labelledby="recording-settings-title" onKeyDown={keyDown}>
            <div className="modal-header"><h3 id="recording-settings-title">Запись экрана</h3></div>
            <label>Качество<select autoFocus value={quality} disabled={busy} onChange={event => setQuality(event.target.value as RecordingQuality)}>
                {Object.entries(RECORDING_QUALITIES).map(([value, preset]) => <option key={value} value={value}>{preset.label}</option>)}
            </select></label>
            <label>Частота кадров<select value={fps} disabled={busy} onChange={event => setFps(Number(event.target.value))}>
                {[1, 5, 10, 15, 25, 30].map(value => <option key={value} value={value}>{value} FPS</option>)}
            </select></label>
            <p className="muted">{format}. Без звука. Максимум {recordingClock(RECORDING_MAX_SECONDS)}.</p>
            <p className="muted">Частота обновления изображения зависит от устройства и сети. При закрытии вкладки «Экран» запись завершится и сохранится.</p>
            <div className="recording-settings-actions">
                <button type="button" className="secondary-button" disabled={busy} onClick={onClose}>Отмена</button>
                <button type="button" className="danger-button" disabled={busy || unsupported} onClick={() => onStart({ quality, fps })}>{busy ? "Подготовка…" : "Начать запись"}</button>
            </div>
        </div>
    </div>, document.body);
}
