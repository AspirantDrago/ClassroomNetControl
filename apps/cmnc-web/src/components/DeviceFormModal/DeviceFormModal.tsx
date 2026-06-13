import type { FormEvent } from "react";
import type { DashboardDevice, DynamicDevice } from "../../api";
import "./DeviceFormModal.css";

export type DeviceFormState =
    | {
    mode: "pin-observed";
    device: DynamicDevice;
    inventoryName: string;
    rowIndex: string;
    columnIndex: string;
}
    | {
    mode: "edit-device";
    device: DashboardDevice;
    inventoryName: string;
    rowIndex: string;
    columnIndex: string;
};

type DeviceFormModalProps = {
    form: DeviceFormState;
    busy: boolean;
    onChange: (form: DeviceFormState) => void;
    onClose: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
    onUnpin?: () => void;
};

export function DeviceFormModal(props: DeviceFormModalProps) {
    const { form, busy, onChange, onClose, onSubmit, onUnpin } = props;

    return (
        <div className="modal-backdrop" onMouseDown={onClose}>
            <form
                className="modal-card"
                onSubmit={onSubmit}
                onMouseDown={(event) => event.stopPropagation()}
            >
                <div className="modal-header">
                    <div>
                        <h3>
                            {form.mode === "pin-observed"
                                ? "Закрепить устройство"
                                : "Редактировать устройство"}
                        </h3>
                        <div className="muted">
                            {form.mode === "pin-observed"
                                ? "Устройство будет добавлено в сетку аудитории."
                                : "Можно изменить позицию в сетке или очистить Row/Column."}
                        </div>
                    </div>

                    <button
                        type="button"
                        className="modal-close-button"
                        onClick={onClose}
                    >
                        ×
                    </button>
                </div>

                <div className="readonly-grid">
                    <ReadonlyField label="MAC" value={getMacAddress(form)} />
                    <ReadonlyField label="IP" value={getIpAddress(form)} />
                    <ReadonlyField label="Hostname из MikroTik" value={getHostname(form)} />
                    <ReadonlyField label="Lease" value={getLeaseText(form)} />
                </div>

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