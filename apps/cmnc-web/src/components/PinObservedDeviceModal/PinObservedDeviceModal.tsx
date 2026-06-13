import type { FormEvent } from "react";
import type { DynamicDevice } from "../../api";
import "./PinObservedDeviceModal.css";

export type PinObservedFormState = {
    device: DynamicDevice;
    inventoryName: string;
    rowIndex: string;
    columnIndex: string;
};

type PinObservedDeviceModalProps = {
    form: PinObservedFormState;
    busyPinMac: string | null;
    onChange: (form: PinObservedFormState) => void;
    onClose: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function PinObservedDeviceModal(props: PinObservedDeviceModalProps) {
    const { form, busyPinMac, onChange, onClose, onSubmit } = props;

    return (
        <div className="modal-backdrop" onMouseDown={onClose}>
            <form
                className="modal-card"
                onSubmit={onSubmit}
                onMouseDown={(event) => event.stopPropagation()}
            >
                <div className="modal-header">
                    <div>
                        <h3>Закрепить устройство</h3>
                        <div className="muted">
                            Устройство будет добавлено в сетку аудитории.
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
                    <ReadonlyField label="MAC" value={form.device.mac_address} />
                    <ReadonlyField label="IP" value={form.device.active_ip ?? "-"} />
                    <ReadonlyField label="Hostname из MikroTik" value={form.device.hostname ?? "-"} />
                    <ReadonlyField label="Lease" value={getLeaseText(form.device)} />
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
                    <button
                        type="button"
                        className="secondary-button"
                        onClick={onClose}
                    >
                        Отмена
                    </button>

                    <button
                        type="submit"
                        className="primary-button"
                        disabled={busyPinMac === form.device.mac_address}
                    >
                        Закрепить
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

function getLeaseText(device: DynamicDevice): string {
    if (device.dynamic === false) {
        return "static";
    }

    if (device.dynamic === true) {
        return "dynamic";
    }

    return "unknown";
}
