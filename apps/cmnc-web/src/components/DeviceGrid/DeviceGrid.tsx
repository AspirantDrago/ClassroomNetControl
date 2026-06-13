import type { DashboardDevice } from "../../api";
import type { DeviceGridModel } from "../../utils/devices";
import { DeviceCard } from "../DeviceCard/DeviceCard";
import "./DeviceGrid.css";

type DeviceGridProps = {
    deviceGrid: DeviceGridModel;
    busyDeviceId: number | null;
    onBlock: (deviceId: number) => Promise<void>;
    onAllow: (deviceId: number) => Promise<void>;
    onEdit: (device: DashboardDevice) => void;
};

export function DeviceGrid(props: DeviceGridProps) {
    const { deviceGrid, busyDeviceId, onBlock, onAllow, onEdit } = props;

    return (
        <>
            {deviceGrid.rowCount > 0 && deviceGrid.columnCount > 0 ? (
                <section
                    className="device-grid"
                    style={{
                        gridTemplateColumns: `repeat(${deviceGrid.columnCount}, 128px)`,
                    }}
                >
                    {deviceGrid.rows.flatMap((row) =>
                        row.map((cell) => (
                            <div
                                key={`${cell.rowIndex}:${cell.columnIndex}`}
                                className="device-grid-cell"
                            >
                                {cell.device ? (
                                    <DeviceCard
                                        device={cell.device}
                                        busyDeviceId={busyDeviceId}
                                        onBlock={onBlock}
                                        onAllow={onAllow}
                                        onEdit={onEdit}
                                    />
                                ) : (
                                    <div className="empty-device-cell">
                                        <span>
                                            {cell.rowIndex}:{cell.columnIndex}
                                        </span>
                                    </div>
                                )}
                            </div>
                        )),
                    )}
                </section>
            ) : (
                <div className="muted">
                    В аудитории пока нет устройств с заданной позицией в сетке.
                </div>
            )}

            {deviceGrid.unpositionedDevices.length > 0 && (
                <UnpositionedDevices
                    devices={deviceGrid.unpositionedDevices}
                    busyDeviceId={busyDeviceId}
                    onBlock={onBlock}
                    onAllow={onAllow}
                    onEdit={onEdit}
                />
            )}
        </>
    );
}

function UnpositionedDevices(props: {
    devices: DashboardDevice[];
    busyDeviceId: number | null;
    onBlock: (deviceId: number) => Promise<void>;
    onAllow: (deviceId: number) => Promise<void>;
    onEdit: (device: DashboardDevice) => void;
}) {
    const { devices, busyDeviceId, onBlock, onAllow, onEdit } = props;

    return (
        <section className="unpositioned-section">
            <h3>Устройства без позиции</h3>

            <div className="unpositioned-grid">
                {devices.map((device) => (
                    <DeviceCard
                        key={device.id}
                        device={device}
                        busyDeviceId={busyDeviceId}
                        onBlock={onBlock}
                        onAllow={onAllow}
                        onEdit={onEdit}
                    />
                ))}
            </div>
        </section>
    );
}
