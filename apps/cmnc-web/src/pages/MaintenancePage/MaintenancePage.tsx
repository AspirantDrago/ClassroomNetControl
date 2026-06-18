import { useEffect, useMemo, useState } from "react";
import {
    extractErrorDetail,
    getMaintenanceContainers,
    type MaintenanceContainerStatus,
} from "../../api";
import "./MaintenancePage.css";

export function MaintenancePage() {
    const [containers, setContainers] = useState<MaintenanceContainerStatus[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function loadContainers() {
        setLoading(true);
        setError(null);

        try {
            const data = await getMaintenanceContainers();
            setContainers(data.containers);
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        let cancelled = false;

        async function loadInitial() {
            setLoading(true);
            setError(null);

            try {
                const data = await getMaintenanceContainers();

                if (!cancelled) {
                    setContainers(data.containers);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(extractErrorDetail(err));
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        void loadInitial();

        const timerId = window.setInterval(() => {
            getMaintenanceContainers()
                .then((data) => {
                    if (!cancelled) {
                        setContainers(data.containers);
                    }
                })
                .catch(() => {
                    // Ошибку фонового обновления не показываем поверх текущего состояния.
                });
        }, 5000);

        return () => {
            cancelled = true;
            window.clearInterval(timerId);
        };
    }, []);

    const totals = useMemo(() => {
        const runningCount = containers.filter((container) => container.state === "running").length;
        const stoppedCount = containers.filter((container) =>
            ["exited", "dead", "removing"].includes(container.state),
        ).length;
        const startingCount = containers.filter((container) =>
            ["created", "restarting"].includes(container.state) || container.health === "starting",
        ).length;

        return { runningCount, stoppedCount, startingCount };
    }, [containers]);

    return (
        <section className="maintenance-page">
            <div className="maintenance-page__header">
                <div>
                    <h2>Обслуживание</h2>
                    <p>Состояние контейнеров CMNC, потребление CPU и памяти.</p>
                </div>

                <button
                    className="secondary-button"
                    type="button"
                    onClick={() => void loadContainers()}
                    disabled={loading}
                >
                    {loading ? "Обновление..." : "Обновить"}
                </button>
            </div>

            <div className="maintenance-summary">
                <div className="maintenance-summary__item">
                    <span>Запущено</span>
                    <strong>{totals.runningCount}</strong>
                </div>
                <div className="maintenance-summary__item">
                    <span>Запускается</span>
                    <strong>{totals.startingCount}</strong>
                </div>
                <div className="maintenance-summary__item">
                    <span>Остановлено</span>
                    <strong>{totals.stoppedCount}</strong>
                </div>
            </div>

            {error && <pre className="error-box">{error}</pre>}

            <div className="maintenance-table-wrap">
                <table className="maintenance-table">
                    <thead>
                        <tr>
                            <th>Контейнер</th>
                            <th>Состояние</th>
                            <th>Health</th>
                            <th>CPU</th>
                            <th>Память</th>
                            <th>Docker status</th>
                            <th>Образ</th>
                        </tr>
                    </thead>
                    <tbody>
                        {containers.map((container) => (
                            <tr key={container.id}>
                                <td>
                                    <div className="maintenance-container-name">
                                        {container.name}
                                    </div>
                                </td>
                                <td>
                                    <span className={getStateBadgeClassName(container)}>
                                        {container.state_label}
                                    </span>
                                </td>
                                <td>{formatHealth(container.health)}</td>
                                <td>{formatPercent(container.cpu_percent)}</td>
                                <td>{formatMemory(container)}</td>
                                <td className="maintenance-muted">{container.docker_status || "-"}</td>
                                <td className="maintenance-image" title={container.image}>
                                    {container.image || "-"}
                                </td>
                            </tr>
                        ))}

                        {containers.length === 0 && !loading && (
                            <tr>
                                <td colSpan={7} className="maintenance-empty">
                                    Контейнеры не найдены.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </section>
    );
}

function getStateBadgeClassName(container: MaintenanceContainerStatus): string {
    if (container.state === "running" && container.health !== "starting") {
        return "maintenance-status maintenance-status--running";
    }

    if (["created", "restarting"].includes(container.state) || container.health === "starting") {
        return "maintenance-status maintenance-status--starting";
    }

    if (["exited", "dead", "removing"].includes(container.state)) {
        return "maintenance-status maintenance-status--stopped";
    }

    return "maintenance-status";
}

function formatHealth(health: string | null): string {
    if (health === null) {
        return "-";
    }

    if (health === "healthy") {
        return "здоров";
    }

    if (health === "unhealthy") {
        return "ошибка";
    }

    if (health === "starting") {
        return "запускается";
    }

    return health;
}

function formatPercent(value: number | null): string {
    if (value === null) {
        return "-";
    }

    return `${value.toFixed(2)} %`;
}

function formatMemory(container: MaintenanceContainerStatus): string {
    if (container.memory_usage_bytes === null) {
        return "-";
    }

    const usage = formatBytes(container.memory_usage_bytes);

    if (container.memory_limit_bytes === null || container.memory_percent === null) {
        return usage;
    }

    return `${usage} / ${formatBytes(container.memory_limit_bytes)} (${container.memory_percent.toFixed(2)} %)`;
}

function formatBytes(bytes: number): string {
    const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
    let value = bytes;
    let unitIndex = 0;

    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }

    if (unitIndex === 0) {
        return `${value} ${units[unitIndex]}`;
    }

    return `${value.toFixed(1)} ${units[unitIndex]}`;
}
