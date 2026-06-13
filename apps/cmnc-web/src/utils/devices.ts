import type { DashboardDevice, DynamicDevice } from "../api";

export type DeviceGridCell = {
    rowIndex: number;
    columnIndex: number;
    device: DashboardDevice | null;
};

export type DeviceGridModel = {
    rows: DeviceGridCell[][];
    rowCount: number;
    columnCount: number;
    unpositionedDevices: DashboardDevice[];
};

export function getDeviceTitle(device: DashboardDevice): string {
    return (
        device.inventory_name ||
        device.hostname ||
        device.observed_hostname ||
        device.mac_address
    );
}

function hasGridPosition(device: DashboardDevice): device is DashboardDevice & {
    row_index: number;
    column_index: number;
} {
    return (
        device.row_index !== null &&
        device.column_index !== null &&
        device.row_index > 0 &&
        device.column_index > 0
    );
}

export function buildDeviceGrid(devices: DashboardDevice[]): DeviceGridModel {
    const positionedDevices = devices.filter(hasGridPosition);
    const unpositionedDevices = devices.filter((device) => !hasGridPosition(device));

    const rowCount = positionedDevices.reduce(
        (maxRow, device) => Math.max(maxRow, device.row_index),
        0,
    );

    const columnCount = positionedDevices.reduce(
        (maxColumn, device) => Math.max(maxColumn, device.column_index),
        0,
    );

    const devicesByPosition = new Map<string, DashboardDevice>();

    for (const device of positionedDevices) {
        devicesByPosition.set(`${device.row_index}:${device.column_index}`, device);
    }

    const rows: DeviceGridCell[][] = [];

    for (let rowIndex = 1; rowIndex <= rowCount; rowIndex += 1) {
        const row: DeviceGridCell[] = [];

        for (let columnIndex = 1; columnIndex <= columnCount; columnIndex += 1) {
            row.push({
                rowIndex,
                columnIndex,
                device: devicesByPosition.get(`${rowIndex}:${columnIndex}`) ?? null,
            });
        }

        rows.push(row);
    }

    return {
        rows,
        rowCount,
        columnCount,
        unpositionedDevices,
    };
}

export function canPinObservedDevice(device: DynamicDevice): boolean {
    return device.dynamic === false && Boolean(device.active_ip);
}

export function getObservedDevicePinText(device: DynamicDevice): string {
    if (canPinObservedDevice(device)) {
        return "Закрепить";
    }

    if (device.dynamic !== false) {
        return "Нужен static lease";
    }

    if (!device.active_ip) {
        return "Нет IP";
    }

    return "Недоступно";
}

export function parseOptionalPositiveInteger(
    value: string,
    fieldName: string,
): number | null {
    const trimmed = value.trim();

    if (!trimmed) {
        return null;
    }

    const parsed = Number(trimmed);

    if (!Number.isInteger(parsed) || parsed <= 0) {
        throw new Error(`${fieldName} должен быть положительным целым числом`);
    }

    return parsed;
}

export function emptyStringToNull(value: string): string | null {
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
}
