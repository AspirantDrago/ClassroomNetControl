import { useEffect, useState, type FormEvent } from "react";
import { formatStateDuration, formatStateTime } from "../../utils/deviceTiming";
import type { DashboardDevice, DynamicDevice } from "../../api";
import { getDeviceTitle } from "../../utils/devices";
import { DeviceScreen } from "../Veyon/DeviceScreen";
import "./DeviceFormModal.css";

export type DeviceFormState =
    | {
    mode: "pin-observed";
    device: DynamicDevice;
    inventoryName: string;
    rowIndex: string;
    columnIndex: string;
    wanProtected: boolean;
    veyonBulkProtected: boolean;
    wolProtected: boolean;
}
    | {
    mode: "edit-device";
    device: DashboardDevice;
    inventoryName: string;
    rowIndex: string;
    columnIndex: string;
    wanProtected: boolean;
    veyonBulkProtected: boolean;
    wolProtected: boolean;
};

type DeviceFormModalProps = {
    classroomName?: string;
    form: DeviceFormState;
    busy: boolean;
    canManage: boolean;
    canControlWan: boolean;
    wanBusy: boolean;
    wakeBusy: boolean;
    powerBusy: boolean;
    onPower: (device: DashboardDevice, action: "power-down" | "reboot") => void;
    onWake: (device: DashboardDevice) => void;
    wakeMessage: string | null;
    onToggleWan: (device: DashboardDevice) => void;
    error: string | null;
    onChange: (form: DeviceFormState) => void;
    onClose: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
    onUnpin?: () => void;
};

export function DeviceFormModal(props: DeviceFormModalProps) {
    const { form, busy, canManage, canControlWan, wanBusy, onToggleWan, error,
        onChange, onClose, onSubmit, onUnpin, wakeBusy, onWake, wakeMessage, powerBusy, onPower } = props;
    const [selectedTab, setSelectedTab] = useState<"info" | "settings" | "screen" | "control">(
        canManage ? "settings" : "info",
    );
    const tab = !canManage && selectedTab === "settings" ? "info" : selectedTab;
    const [screenToolbar, setScreenToolbar] = useState<HTMLDivElement | null>(null);
    const [now, setNow] = useState(() => Date.now());

    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, []);

    return (
        <div className="modal-backdrop" onMouseDown={onClose}>
            <form
                className={`modal-card${(tab === "screen" || tab === "control") ? " device-modal-screen" : ""}`}
                role="dialog"
                aria-modal="true"
                aria-labelledby="device-dialog-title"
                onSubmit={(event) => {
                    if (tab === "settings" && canManage) onSubmit(event);
                    else event.preventDefault();
                }}
                onKeyDown={(event) => { if (event.key === "Escape") onClose(); }}
                onMouseDown={(event) => event.stopPropagation()}
            >
                <div className="modal-header">
                    <div>
                        <h3 id="device-dialog-title">
                            {form.mode === "pin-observed"
                                ? "Закрепить устройство"
                                : "Устройство"}
                        </h3>
                        {tab === "settings" && <div className="muted">
                            {form.mode === "pin-observed"
                                ? "Устройство будет добавлено в сетку аудитории."
                                : "Можно изменить позицию в сетке или очистить Row/Column."}
                        </div>}
                    </div>

                    <button
                        type="button"
                        className="modal-close-button"
                        aria-label="Закрыть"
                        autoFocus
                        onClick={onClose}
                    >
                        ×
                    </button>
                </div>

                <div className="device-modal-navigation">
                <div className="device-modal-tabs" role="tablist" aria-label="Устройство">
                    <button type="button" role="tab" id="device-info-tab"
                        aria-selected={tab === "info"} aria-controls="device-info-panel"
                        onClick={() => setSelectedTab("info")}>Инфо</button>
                    {form.mode === "edit-device" && <button type="button" role="tab" id="device-screen-tab"
                        aria-selected={tab === "screen"} aria-controls="device-screen-panel"
                        onClick={() => setSelectedTab("screen")}>Экран</button>}
                    {form.mode === "edit-device" && <button type="button" role="tab" id="device-control-tab"
                        aria-selected={tab === "control"} aria-controls="device-control-panel"
                        onClick={() => setSelectedTab("control")}>Перехват экрана</button>}
                    {canManage && <button type="button" role="tab" id="device-settings-tab"
                        aria-selected={tab === "settings"} aria-controls="device-settings-panel"
                        onClick={() => setSelectedTab("settings")}>Настройка</button>}
                </div>

                <div className="device-modal-screen-actions" ref={setScreenToolbar} />
                </div>

                {error && <div className="device-modal-error" role="alert">{error}</div>}

                {tab === "screen" && form.mode === "edit-device" && <div role="tabpanel" id="device-screen-panel" aria-labelledby="device-screen-tab">
                    <DeviceScreen key={form.device.id} deviceId={form.device.id} deviceName={getDeviceTitle(form.device)} classroomName={props.classroomName} toolbarTarget={screenToolbar} />
                </div>}

                {tab === "control" && form.mode === "edit-device" && <div role="tabpanel" id="device-control-panel" aria-labelledby="device-control-tab">
                    <DeviceScreen key={form.device.id} deviceId={form.device.id} control toolbarTarget={screenToolbar} />
                </div>}

                {tab === "info" && <div role="tabpanel" id="device-info-panel" aria-labelledby="device-info-tab">
                <div className="readonly-grid">
                    <ReadonlyField label="MAC" value={getMacAddress(form)} />
                    <ReadonlyField label="IP" value={getIpAddress(form)} />
                    <ReadonlyField label="Hostname из MikroTik" value={getHostname(form)} />
                    <ReadonlyField label="Lease" value={getLeaseText(form)} />
                    <ReadonlyField label="Название в аудитории" value={form.mode === "edit-device" ? form.device.inventory_name || "-" : "-"} />
                    {form.mode === "edit-device" && form.device.wan_protected && (
                        <ReadonlyField label="Защищено от отключения WAN" value="Да" />
                    )}
                </div>
                {form.mode === "edit-device" && <div className="device-state-grid">
                    {!form.device.wan_protected && <>
                        <ReadonlyField
                            label={form.device.wan_allowed ? "Время включения Интернета" : "Время отключения Интернета"}
                            value={formatStateTime(form.device.wan_state_since)}
                            positive={form.device.wan_allowed}
                        />
                        <ReadonlyField
                            label={form.device.wan_allowed ? "Интернет доступен" : "Интернет отключён"}
                            value={formatStateDuration(form.device.wan_state_since, now)}
                            positive={form.device.wan_allowed}
                        />
                    </>}
                    <ReadonlyField
                        label={form.device.online ? "Время запуска устройства" : "Время выключения устройства"}
                        value={formatStateTime(form.device.online_state_since)}
                            positive={form.device.online}
                    />
                    <ReadonlyField
                        label={form.device.online ? "Устройство включено" : "Устройство выключено"}
                        value={formatStateDuration(form.device.online_state_since, now)}
                            positive={form.device.online}
                    />
                </div>}
                {wakeMessage && <div className="device-wake-message muted" role="status">{wakeMessage}</div>}
                {form.mode === "edit-device" && <div className="modal-actions device-power-actions">
                    <button type="button" className="danger-button" disabled={powerBusy}
                        onClick={() => onPower(form.device, "power-down")}>Выключить</button>
                    <button type="button" className="secondary-button" disabled={powerBusy}
                        onClick={() => onPower(form.device, "reboot")}>Перезагрузить</button>
                    <button type="button" className="success-button"
                        disabled={wakeBusy} onClick={() => onWake(form.device)}>
                        {wakeBusy ? "Отправка WoL..." : "Разбудить"}
                    </button>
                    <button type="button"
                        className={form.device.wan_allowed ? "danger-button" : "primary-button"}
                        disabled={!canControlWan || wanBusy || (form.device.wan_protected && form.device.wan_allowed)}
                        onClick={() => onToggleWan(form.device)}>
                        {form.device.wan_allowed ? "Выключить Интернет" : "Включить Интернет"}
                    </button>
                </div>}
                </div>}

                {tab === "settings" && canManage && <div role="tabpanel" id="device-settings-panel" aria-labelledby="device-settings-tab">
                <div className="pin-form-grid">
                    <label>
                        Название в аудитории
                        <input
                            value={form.inventoryName}
                            onChange={(event) =>
                                onChange({
                                    ...form,
                                    inventoryName: event.target.value,
                                })
                            }
                            placeholder="PC-01"
                        />
                    </label>

                    <label>
                        Row
                        <input
                            type="number"
                            min="1"
                            value={form.rowIndex}
                            onChange={(event) =>
                                onChange({
                                    ...form,
                                    rowIndex: event.target.value,
                                })
                            }
                            placeholder="1"
                        />
                    </label>

                    <label>
                        Column
                        <input
                            type="number"
                            min="1"
                            value={form.columnIndex}
                            onChange={(event) =>
                                onChange({
                                    ...form,
                                    columnIndex: event.target.value,
                                })
                            }
                            placeholder="1"
                        />
                    </label>
                </div>

                <label className="checkbox-field">
                    <input
                        type="checkbox"
                        checked={form.wanProtected}
                        onChange={(event) =>
                            onChange({
                                ...form,
                                wanProtected: event.target.checked,
                            })
                        }
                    />
                    <span>Защитить от отключения WAN</span>
                </label>

                <label className="checkbox-field">
                    <input type="checkbox" checked={form.veyonBulkProtected}
                        onChange={(event) => onChange({ ...form, veyonBulkProtected: event.target.checked })} />
                    <span>Защита от массового управления через Veyon</span>
                </label>
                <label className="checkbox-field">
                    <input type="checkbox" checked={form.wolProtected}
                        onChange={(event) => onChange({ ...form, wolProtected: event.target.checked })} />
                    <span>Защита от пробуждения WoL</span>
                </label>

                <div className="modal-actions">
                    {form.mode === "edit-device" && onUnpin && (
                        <button
                            type="button"
                            className="danger-button"
                            disabled={busy}
                            onClick={onUnpin}
                        >
                            Открепить
                        </button>
                    )}

                    <button
                        type="button"
                        className="secondary-button"
                        disabled={busy}
                        onClick={onClose}
                    >
                        Отмена
                    </button>

                    <button
                        type="submit"
                        className="primary-button"
                        disabled={busy}
                    >
                        {form.mode === "pin-observed" ? "Закрепить" : "Сохранить"}
                    </button>
                </div>
                </div>}
            </form>
        </div>
    );
}

function ReadonlyField(props: { label: string; value: string; positive?: boolean }) {
    const { label, value, positive } = props;

    return (
        <div className={`readonly-field${positive === undefined ? "" : positive ? " readonly-field-positive" : " readonly-field-negative"}`}>
            <span>{label}</span>
            <strong>{value}</strong>
        </div>
    );
}

function getMacAddress(form: DeviceFormState): string {
    return form.device.mac_address;
}

function getIpAddress(form: DeviceFormState): string {
    if (form.mode === "pin-observed") {
        return form.device.active_ip ?? "-";
    }

    return form.device.static_ip ?? form.device.active_ip ?? "-";
}

function getHostname(form: DeviceFormState): string {
    if (form.mode === "pin-observed") {
        return form.device.hostname ?? "-";
    }

    return form.device.observed_hostname ?? form.device.hostname ?? "-";
}

function getLeaseText(form: DeviceFormState): string {
    if (form.mode === "edit-device") {
        return form.device.static_ip ? "static" : "unknown";
    }

    if (form.device.dynamic === false) {
        return "static";
    }

    if (form.device.dynamic === true) {
        return "dynamic";
    }

    return "unknown";
}
