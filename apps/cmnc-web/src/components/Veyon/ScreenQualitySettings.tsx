import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { SCREEN_QUALITIES, type ScreenQuality } from "./screenQuality";
export function ScreenQualitySettings({ value, onSave, onClose }: { value: ScreenQuality; onSave: (quality: ScreenQuality) => void; onClose: () => void }) {
    const [selected, setSelected] = useState(value);
    const ref = useRef<HTMLDialogElement>(null);
    useEffect(() => {
        const dialog = ref.current!;
        dialog.showModal();
        return () => dialog.close();
    }, []);
    return createPortal(<dialog ref={ref} className="modal-card recording-settings screen-quality-dialog"
        aria-labelledby="screen-quality-title" onCancel={event => { event.preventDefault(); onClose(); }}
        onKeyDown={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
        <div className="modal-header"><h3 id="screen-quality-title">Качество экрана</h3></div>
        <label>Качество<select autoFocus value={selected} onChange={event => setSelected(event.target.value as ScreenQuality)}>
            {Object.entries(SCREEN_QUALITIES).map(([key, preset]) => <option key={key} value={key}>{preset.label}</option>)}
        </select></label>
        <p className="muted">Выбор сохраняется в этом браузере для просмотра и перехвата экрана. Качество записи выбирается при её запуске.</p>
        <div className="recording-settings-actions">
            <button type="button" className="secondary-button" onClick={onClose}>Отмена</button>
            <button type="button" className="primary-button" onClick={() => onSave(selected)}>Сохранить</button>
        </div>
    </dialog>, document.body);
}
