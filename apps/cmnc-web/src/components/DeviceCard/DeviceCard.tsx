import type { DashboardDevice } from "../../api";
import { getDeviceTitle } from "../../utils/devices";
import "./DeviceCard.css";

type DeviceCardProps = {
    device: DashboardDevice;
    busyDeviceId: number | null;
    onBlock: (deviceId: number) => Promise<void>;
    onAllow: (deviceId: number) => Promise<void>;
    onEdit: (device: DashboardDevice) => void;
};

export function DeviceCard(props: DeviceCardProps) {
    const { device, busyDeviceId, onBlock, onAllow, onEdit } = props;
    const busy = busyDeviceId === device.id;

    return (
        <div className={`device-card ${device.online ? "device-online" : "device-offline"}`}
             onDoubleClick={() => onEdit(device)}
        >
            <div className="device-card-header">
                <div className="device-title">{getDeviceTitle(device)}</div>
            </div>

            <div className="device-info">
                <div className="device-subtitle">{device.mac_address}</div>
                <div className="device-subtitle">{device.static_ip ?? "-"}</div>
                <div className="device-subtitle">
                    {device.observed_hostname ?? device.hostname ?? "-"}
                </div>
            </div>

            {device.sync_error && <div className="error-text">{device.sync_error}</div>}

            <div className="device-actions">
                {device.wan_protected ? (
                    <span className="status-pill status-protected">Protected WAN</span>
                ) : device.wan_allowed ? (
                    <button
                        disabled={busy}
                        onClick={(event) => {
                            event.stopPropagation();
                            void onBlock(device.id);
                        }}
                    >
                        <span
                            className={`status-pill status-online ${
                                device.sync_status === "pending" ? "status-pending" : ""
                            }`}
                        >
                            Internet
                        </span>
                    </button>
                ) : (
                    <button
                        disabled={busy}
                        onClick={(event) => {
                            event.stopPropagation();
                            void onAllow(device.id);
                        }}
                    >
                        <span
                            className={`status-pill status-offline ${
                                device.sync_status === "pending" ? "status-pending" : ""
                            }`}
                        >
                            no Internet
                        </span>
                    </button>
                )}
            </div>
        </div>
    );
}
