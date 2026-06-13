import { useEffect, useMemo, useState } from "react";
import {
  allowDeviceWan,
  blockDeviceWan,
  type Classroom,
  type ClassroomDashboard,
  type DashboardDevice,
  getClassroomDashboard,
  getClassrooms,
} from "./api";

function formatDate(value: string | null): string {
  if (!value) {
    return "нет данных";
  }

  return new Date(value).toLocaleString();
}

function getDeviceTitle(device: DashboardDevice): string {
  return device.inventory_name || device.hostname || device.observed_hostname || device.mac_address;
}

function sortDevices(devices: DashboardDevice[]): DashboardDevice[] {
  return [...devices].sort((left, right) => {
    const leftRow = left.row_index ?? 9999;
    const rightRow = right.row_index ?? 9999;

    if (leftRow !== rightRow) {
      return leftRow - rightRow;
    }

    const leftColumn = left.column_index ?? 9999;
    const rightColumn = right.column_index ?? 9999;

    if (leftColumn !== rightColumn) {
      return leftColumn - rightColumn;
    }

    return left.id - right.id;
  });
}

function DeviceCard(props: {
  device: DashboardDevice;
  busyDeviceId: number | null;
  onBlock: (deviceId: number) => Promise<void>;
  onAllow: (deviceId: number) => Promise<void>;
}) {
  const { device, busyDeviceId, onBlock, onAllow } = props;
  const busy = busyDeviceId === device.id;

  return (
      <div className={`device-card ${device.online ? "device-online" : "device-offline"}`}>
        <div className="device-card-header">
          <div>
            <div className="device-title">{getDeviceTitle(device)}</div>
          </div>

          <div className={`status-pill ${device.online ? "status-online" : "status-offline"}`}>
            {device.online ? "online" : "offline"}
          </div>
          <div className={`status-pill 
          ${device.wan_allowed ? "status-online" : "status-offline"}
          ${device.sync_status == 'pending' ? 'status-pending' : ''}
          `}>
            {device.wan_allowed ? "Internet" : "no Internet"}
          </div>
        </div>

        <div className="device-info">
          <div className="device-subtitle">{device.mac_address}</div>
          <div className="device-subtitle">{device.static_ip ?? "-"}</div>
          <div className="device-subtitle">{device.observed_hostname ?? device.hostname ?? "-"}</div>
        </div>

        {device.sync_error && <div className="error-text">{device.sync_error}</div>}

        <div className="device-actions">
          {device.wan_allowed ? (
              <button
                  className="danger-button"
                  disabled={busy}
                  onClick={() => onBlock(device.id)}
              >
                Отключить интернет
              </button>
          ) : (
              <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() => onAllow(device.id)}
              >
                Включить интернет
              </button>
          )}
        </div>
      </div>
  );
}

export function App() {
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [selectedClassroomId, setSelectedClassroomId] = useState<number | null>(null);
  const [dashboard, setDashboard] = useState<ClassroomDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyDeviceId, setBusyDeviceId] = useState<number | null>(null);

  async function loadClassrooms() {
    const data = await getClassrooms();
    setClassrooms(data);

    if (selectedClassroomId === null && data.length > 0) {
      setSelectedClassroomId(data[0].id);
    }
  }

  async function loadDashboard(classroomId: number) {
    const data = await getClassroomDashboard(classroomId);
    setDashboard(data);
  }

  async function reload() {
    if (selectedClassroomId === null) {
      return;
    }

    setError(null);

    try {
      await loadDashboard(selectedClassroomId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);

    loadClassrooms()
        .catch((err) => {
          setError(err instanceof Error ? err.message : "Unknown error");
        })
        .finally(() => {
          setLoading(false);
        });
  }, []);

  useEffect(() => {
    if (selectedClassroomId === null) {
      return;
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);

    loadDashboard(selectedClassroomId)
        .catch((err) => {
          setError(err instanceof Error ? err.message : "Unknown error");
        })
        .finally(() => {
          setLoading(false);
        });

    const timerId = window.setInterval(() => {
      loadDashboard(selectedClassroomId).catch(() => {
        // Ошибку polling не показываем поверх экрана.
      });
    }, 5000);

    return () => window.clearInterval(timerId);
  }, [selectedClassroomId]);

  async function handleBlock(deviceId: number) {
    setBusyDeviceId(deviceId);
    setError(null);

    try {
      await blockDeviceWan(deviceId);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setBusyDeviceId(null);
    }
  }

  async function handleAllow(deviceId: number) {
    setBusyDeviceId(deviceId);
    setError(null);

    try {
      await allowDeviceWan(deviceId);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setBusyDeviceId(null);
    }
  }

  const sortedDevices = useMemo(() => {
    return sortDevices(dashboard?.devices ?? []);
  }, [dashboard]);

  return (
      <div className="page">
        <header className="topbar">
          <div>
            <h1>Classroom MikroTik Net Control</h1>
            <p>Управление доступом ученических ПК в WAN</p>
          </div>

          <button
              className="secondary-button"
              onClick={reload}
              disabled={selectedClassroomId === null}
          >
            Обновить
          </button>
        </header>

        <main className="content">
          <section className="classroom-tabs">
            {classrooms.map((classroom) => (
                <button
                    key={classroom.id}
                    className={classroom.id === selectedClassroomId ? "tab active-tab" : "tab"}
                    onClick={() => setSelectedClassroomId(classroom.id)}
                >
                  {classroom.name}
                </button>
            ))}
          </section>

          {error && <pre className="error-box">{error}</pre>}

          {loading && <div className="loading">Загрузка...</div>}

          {dashboard && (
              <>
                <section className="classroom-header">
                  <div>
                    <h2>{dashboard.classroom.name}</h2>
                    <div className="muted">
                      subnet: {dashboard.classroom.subnet_cidr}, VLAN:{" "}
                      {dashboard.classroom.vlan_id ?? "-"}
                    </div>
                  </div>
                </section>

                <section className="device-grid">
                  {sortedDevices.map((device) => (
                      <DeviceCard
                          key={device.id}
                          device={device}
                          busyDeviceId={busyDeviceId}
                          onBlock={handleBlock}
                          onAllow={handleAllow}
                      />
                  ))}
                </section>

                <section className="dynamic-section">
                  <h3>Незакреплённые устройства</h3>

                  {dashboard.dynamic_devices.length === 0 ? (
                      <div className="muted">Нет найденных незакреплённых устройств в подсети аудитории.</div>
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
                          </tr>
                          </thead>
                          <tbody>
                          {dashboard.dynamic_devices.map((device) => (
                              <tr key={device.mac_address}>
                                <td>{device.mac_address}</td>
                                <td>{device.active_ip ?? "-"}</td>
                                <td>{device.hostname ?? "-"}</td>
                                <td>
                                  {device.dynamic === false
                                      ? "static"
                                      : device.dynamic === true
                                          ? "dynamic"
                                          : "unknown"}
                                </td>
                                <td>{device.active ? "yes" : "no"}</td>
                                <td>{formatDate(device.last_seen_at)}</td>
                              </tr>
                          ))}
                          </tbody>
                        </table>
                      </div>
                  )}
                </section>
              </>
          )}
        </main>
      </div>
  );
}