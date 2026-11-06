import { useEffect, useState, type FormEvent } from "react";
import { formatStateDuration, formatStateTime } from "../../utils/deviceTiming";
import type { DashboardDevice, DynamicDevice } from "../../api";
import "./DeviceFormModal.css";

export type DeviceFormState =
    | {
    mode: "pin-observed";
    device: DynamicDevice;
    inventoryName: string;
    rowIndex: string;
    columnIndex: string;
    wanProtected: boolean;
}
    | {
    mode: "edit-device";
    device: DashboardDevice;
    inventoryName: string;
    rowIndex: string;
    columnIndex: string;
    wanProtected: boolean;
};

type DeviceFormModalProps = {
    form: DeviceFormState;
    busy: boolean;
    canManage: boolean;
    canControlWan: boolean;
    wanBusy: boolean;
    onToggleWan: (device: DashboardDevice) => void;
    error: string | null;
    onChange: (form: DeviceFormState) => void;
    onClose: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
    onUnpin?: () => void;
};

export function DeviceFormModal(props: DeviceFormModalProps) {
    const { form, busy, canManage, canControlWan, wanBusy, onToggleWan, error,
        onChange, onClose, onSubmit, onUnpin } = props;
    const [selectedTab, setSelectedTab] = useState<"info" | "settings">(
        canManage ? "settings" : "info",
    );
    const tab = canManage ? selectedTab : "info";
    const [now, setNow] = useState(() => Date.now());

    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, []);

    return (
        <div className="modal-backdrop" onMouseDown={onClose}>
            <form
                className="modal-card"
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

                <div className="device-modal-tabs" role="tablist" aria-label="Устройство">
                    <button type="button" role="tab" id="device-info-tab"
                        aria-selected={tab === "info"} aria-controls="device-info-panel"
                        onClick={() => setSelectedTab("info")}>Инфо</button>
                    {canManage && <button type="button" role="tab" id="device-settings-tab"
                        aria-selected={tab === "settings"} aria-controls="device-settings-panel"
                        onClick={() => setSelectedTab("settings")}>Настройка</button>}
                </div>

                {error && <div className="device-modal-error" role="alert">{error}</div>}

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
                        />
                        <ReadonlyField
                            label={form.device.wan_allowed ? "Интернет доступен" : "Интернет отключён"}
                            value={formatStateDuration(form.device.wan_state_since, now)}
                        />
                    </>}
                    <ReadonlyField
                        label={form.device.online ? "Время запуска" : "Время выключения"}
                        value={formatStateTime(form.device.online_state_since)}
                    />
                    <ReadonlyField
                        label={form.device.online ? "Включен" : "Выключен"}
                        value={formatStateDuration(form.device.online_state_since, now)}
                    />
                </div>}
                {form.mode === "edit-device" && <div className="modal-actions">
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

function ReadonlyField(props: { label: string; value: string }) {
    const { label, value } = props;

    return (
        <div className="readonly-field">
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
