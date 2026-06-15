import type { DynamicDevice } from "../../api";
import {
    canPinObservedDevice,
    getObservedDevicePinText,
} from "../../utils/devices";
import "./DynamicDevicesTable.css";

type DynamicDevicesTableProps = {
    devices: DynamicDevice[];
    busyPinMac: string | null;
    busyDeleteObservedDeviceId: number | null;
    busyCleanupStale: boolean;
    onOpenPinForm: (device: DynamicDevice) => void;
    onDeleteInactive: (device: DynamicDevice) => void;
    onCleanupStale: () => void;
    canManageWorkstations: boolean;
};

export function DynamicDevicesTable(props: DynamicDevicesTableProps) {
    const {
        devices,
        busyPinMac,
        busyDeleteObservedDeviceId,
        busyCleanupStale,
        onOpenPinForm,
        onDeleteInactive,
        onCleanupStale,
        canManageWorkstations,
    } = props;

    const sortedDevices = [...devices].sort((left, right) => {
        return compareIpAddresses(left.active_ip, right.active_ip);
    });

    return (
        <section className="dynamic-section">
            <div className="dynamic-section-header">
                <div>
                    <h3>Незакреплённые устройства</h3>
                    <div className="muted">
                        Неактивные устройства можно удалить из базы данных.
                    </div>
                </div>

                {canManageWorkstations && (
                    <button
                        className="secondary-button compact-button"
                        disabled={busyCleanupStale}
                        onClick={onCleanupStale}
                    >
                        {busyCleanupStale ? "Очистка..." : "Очистить старые"}
                    </button>
                )}
            </div>

            {devices.length === 0 ? (
                <div className="muted">
                    Нет найденных незакреплённых устройств в подсети аудитории.
                </div>
            ) : (
                <div className="dynamic-table-wrapper">
                    <table>
                        <thead>
                        <tr>
                            <th>MAC</th>
                            <th>IP</th>
                            <th>Hostname</th>
                            <th>Lease</th>
                            <th>Active</th>
                            <th>Last seen</th>
                            <th>Действие</th>
                        </tr>
                        </thead>
                        <tbody>
                        {sortedDevices.map((device) => (
                            <tr
                                key={device.id}
                                className={device.active ? undefined : "dynamic-row-inactive"}
                            >
                                <td>{device.mac_address}</td>
                                <td>{device.active_ip ?? "-"}</td>
                                <td>{device.hostname ?? "-"}</td>
                                <td>{getLeaseText(device)}</td>
                                <td>{device.active ? "yes" : "no"}</td>
                                <td>{formatDate(device.last_seen_at)}</td>
                                <td>
                                    {!canManageWorkstations ? (
                                        <span className="muted">Нет прав</span>
                                    ) : !device.active ? (
                                        <button
                                            className="icon-danger-button"
                                            title="Удалить неактивное устройство из базы данных"
                                            aria-label="Удалить неактивное устройство из базы данных"
                                            disabled={busyDeleteObservedDeviceId === device.id}
                                            onClick={() => onDeleteInactive(device)}
                                        >
                                            {busyDeleteObservedDeviceId === device.id ? "..." : "×"}
                                        </button>
                                    ) : canPinObservedDevice(device) ? (
                                        <button
                                            className="secondary-button compact-button"
                                            disabled={busyPinMac === device.mac_address}
                                            onClick={() => onOpenPinForm(device)}
                                        >
                                            {busyPinMac === device.mac_address ? "..." : "Закрепить"}
                                        </button>
                                    ) : (
                                        <span className="muted">
                                            {getObservedDevicePinText(device)}
                                        </span>
                                    )}
                                </td>
                            </tr>
                        ))}
                        </tbody>
                    </table>
                </div>
            )}
        </section>
    );
}

function formatDate(value: string | null): string {
    if (!value) {
        return "нет данных";
    }

    return new Date(value).toLocaleString().replace(',', '');
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

function compareIpAddresses(leftIp: string | null, rightIp: string | null): number {
    const leftParts = parseIpv4(leftIp);
    const rightParts = parseIpv4(rightIp);

    if (leftParts === null && rightParts === null) {
        return 0;
    }

    if (leftParts === null) {
        return 1;
    }

    if (rightParts === null) {
        return -1;
    }

    for (let index = 0; index < 4; index += 1) {
        const difference = leftParts[index] - rightParts[index];

        if (difference !== 0) {
            return difference;
        }
    }

    return 0;
}

function parseIpv4(value: string | null): [number, number, number, number] | null {
    if (!value) {
        return null;
    }

    const parts = value.split(".");

    if (parts.length !== 4) {
        return null;
    }

    const numbers = parts.map((part) => Number(part));

    if (
        numbers.some(
            (part) => !Number.isInteger(part) || part < 0 || part > 255,
        )
    ) {
        return null;
    }

    return numbers as [number, number, number, number];
}
