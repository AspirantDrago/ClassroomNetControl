import type { DashboardDevice } from "../../api";
import { getDeviceTitle } from "../../utils/devices";
import "./DeviceCard.css";

type DeviceCardProps = {
    device: DashboardDevice;
    busyDeviceId: number | null;
    onBlock: (deviceId: number) => Promise<void>;
    onAllow: (deviceId: number) => Promise<void>;
    onEdit: (device: DashboardDevice) => void;
    canControlWan: boolean;
    canManageWorkstations: boolean;
};

export function DeviceCard(props: DeviceCardProps) {
    const {
        device,
        busyDeviceId,
        onBlock,
        onAllow,
        onEdit,
        canControlWan,
        canManageWorkstations,
    } = props;
    const busy = busyDeviceId === device.id;

    return (
        <div
            className={`device-card ${device.online ? "device-online" : "device-offline"}`}
            onDoubleClick={() => {
                if (canManageWorkstations) {
                    onEdit(device);
                }
            }}
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
                    canControlWan ? (
                        <button
                            disabled={busy}
                            onClick={(event) => {
                                event.stopPropagation();
                                void onBlock(device.id);
                            }}
                        >
                            <InternetStatusPill device={device} />
                        </button>
                    ) : (
                        <InternetStatusPill device={device} />
                    )
                ) : canControlWan ? (
                    <button
                        disabled={busy}
                        onClick={(event) => {
                            event.stopPropagation();
                            void onAllow(device.id);
                        }}
                    >
                        <NoInternetStatusPill device={device} />
                    </button>
                ) : (
                    <NoInternetStatusPill device={device} />
                )}
            </div>
        </div>
    );
}

function InternetStatusPill(props: { device: DashboardDevice }) {
    const { device } = props;

    return (
        <span
            className={`status-pill status-online ${
                device.sync_status === "pending" ? "status-pending" : ""
            }`}
        >
            Internet
        </span>
    );
}

function NoInternetStatusPill(props: { device: DashboardDevice }) {
    const { device } = props;

    return (
        <span
            className={`status-pill status-offline ${
                device.sync_status === "pending" ? "status-pending" : ""
            }`}
        >
            no Internet
        </span>
    );
}
