import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import {
    downloadMaintenanceDatabaseBackup,
    extractErrorDetail,
    getMaintenanceContainerLogs,
    getMaintenanceContainers,
    uploadMaintenanceDatabaseBackup,
    type MaintenanceContainerStatus,
} from "../../api";
import "./MaintenancePage.css";

type LogsTail = 100 | 1000 | 10000;

type LogsDialogState = {
    container: MaintenanceContainerStatus;
    tail: LogsTail;
    logs: string;
    loading: boolean;
    error: string | null;
};

export function MaintenancePage() {
    const [containers, setContainers] = useState<MaintenanceContainerStatus[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [logsDialog, setLogsDialog] = useState<LogsDialogState | null>(null);
    const [backupFile, setBackupFile] = useState<File | null>(null);
    const [backupLoading, setBackupLoading] = useState(false);
    const [backupMessage, setBackupMessage] = useState<string | null>(null);
    const [backupError, setBackupError] = useState<string | null>(null);
    const logsContentRef = useRef<HTMLPreElement | null>(null);
    const backupInputRef = useRef<HTMLInputElement | null>(null);

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

    async function openLogs(container: MaintenanceContainerStatus, tail: LogsTail = 100) {
        setLogsDialog({
            container,
            tail,
            logs: "",
            loading: true,
            error: null,
        });

        try {
            const data = await getMaintenanceContainerLogs(container.id, tail);

            setLogsDialog((current) => {
                if (current?.container.id !== container.id) {
                    return current;
                }

                return {
                    ...current,
                    tail,
                    logs: data.logs,
                    loading: false,
                    error: null,
                };
            });
        } catch (err) {
            setLogsDialog((current) => {
                if (current?.container.id !== container.id) {
                    return current;
                }

                return {
                    ...current,
                    tail,
                    loading: false,
                    error: extractErrorDetail(err),
                };
            });
        }
    }

    function closeLogs() {
        setLogsDialog(null);
    }

    function handleLogsTailChange(tail: LogsTail) {
        if (!logsDialog) {
            return;
        }

        void openLogs(logsDialog.container, tail);
    }

    function handleBackupFileChange(event: ChangeEvent<HTMLInputElement>) {
        const file = event.target.files?.[0] ?? null;
        setBackupFile(file);
        setBackupMessage(null);
        setBackupError(null);
    }

    async function handleDownloadBackup() {
        setBackupLoading(true);
        setBackupMessage(null);
        setBackupError(null);

        try {
            const data = await downloadMaintenanceDatabaseBackup();
            const filename = data.filename ?? buildFallbackBackupFilename();
            const url = window.URL.createObjectURL(data.blob);
            const link = document.createElement("a");

            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);

            setBackupMessage(`Резервная копия сохранена: ${filename}`);
        } catch (err) {
            setBackupError(extractErrorDetail(err));
        } finally {
            setBackupLoading(false);
        }
    }

    async function handleUploadBackup() {
        if (!backupFile) {
            return;
        }

        const confirmed = window.confirm(
            "Загрузить резервную копию? Текущие данные баз PostgreSQL будут заменены данными из выбранного архива.",
        );

        if (!confirmed) {
            return;
        }

        setBackupLoading(true);
        setBackupMessage(null);
        setBackupError(null);

        try {
            const data = await uploadMaintenanceDatabaseBackup(backupFile);
            const databasesText = data.databases.length > 0
                ? ` Базы: ${data.databases.join(", ")}.`
                : "";

            setBackupMessage(
                `Резервная копия загружена: ${data.filename} (${formatBytes(data.size_bytes)}).${databasesText}`,
            );
            setBackupFile(null);

            if (backupInputRef.current) {
                backupInputRef.current.value = "";
            }
        } catch (err) {
            setBackupError(extractErrorDetail(err));
        } finally {
            setBackupLoading(false);
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

    useEffect(() => {
        if (!logsDialog) {
            return;
        }

        function handleKeyDown(event: KeyboardEvent) {
            if (event.key === "Escape") {
                closeLogs();
            }
        }

        window.addEventListener("keydown", handleKeyDown);

        return () => {
            window.removeEventListener("keydown", handleKeyDown);
        };
    }, [logsDialog !== null]);

    useEffect(() => {
        if (!logsDialog || !logsContentRef.current) {
            return;
        }

        requestAnimationFrame(() => {
            if (!logsContentRef.current) {
                return;
            }

            logsContentRef.current.scrollTop = logsContentRef.current.scrollHeight;
        });
    }, [
        logsDialog?.container.id,
        logsDialog?.tail,
        logsDialog?.logs,
        logsDialog?.loading,
    ]);

    const totals = useMemo(() => {
        const runningCount = containers.filter((container) => container.state === "running").length;
        const stoppedCount = containers.filter((container) =>
            ["exited", "dead", "removing"].includes(container.state),
        ).length;
        const startingCount = containers.filter((container) =>
            ["created", "restarting"].includes(container.state) || container.health === "starting",
        ).length;

        const totalCpuPercent = containers.reduce((sum, container) => {
            return sum + (container.cpu_percent ?? 0);
        }, 0);

        const totalMemoryUsageBytes = containers.reduce((sum, container) => {
            return sum + (container.memory_usage_bytes ?? 0);
        }, 0);

        const memoryLimitBytes =
            containers.find((container) => container.memory_limit_bytes != null)?.memory_limit_bytes ?? 0;

        const totalMemoryPercent = (memoryLimitBytes != 0) ?
            (100 * totalMemoryUsageBytes / memoryLimitBytes) : 0;

        return {
            runningCount,
            stoppedCount,
            startingCount,
            totalCpuPercent,
            totalMemoryUsageBytes,
            totalMemoryPercent,
            memoryLimitBytes,
        };
    }, [containers]);

    return (
        <section className="maintenance-page">
            <div className="maintenance-page__header">
                <div>
                    <h2>Обслуживание</h2>
                    <p>Резервное сохранение и восстановление, состояние контейнеров CMNC, потребление CPU и памяти</p>
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

            <div className="maintenance-backup-panel">
                <div className="maintenance-backup-panel__info">
                    <h3>Резервные копии</h3>
                    <p>Сохранение и загрузка архива с резервными копиями баз PostgreSQL.</p>
                </div>

                <div className="maintenance-backup-panel__actions">
                    <label className="secondary-button maintenance-file-button">
                        Выбрать файл
                        <input
                            ref={backupInputRef}
                            type="file"
                            accept=".tar,application/x-tar,application/octet-stream"
                            onChange={handleBackupFileChange}
                            disabled={backupLoading}
                        />
                    </label>

                    <span className="maintenance-backup-panel__filename">
                        {backupFile ? backupFile.name : "Файл не выбран"}
                    </span>

                    <button
                        className="secondary-button"
                        type="button"
                        onClick={() => void handleUploadBackup()}
                        disabled={!backupFile || backupLoading}
                    >
                        {backupLoading ? "Загрузка..." : "Загрузить резервную копию"}
                    </button>
                </div>

                <div className="maintenance-backup-panel__actions">
                    <button
                        className="primary-button"
                        type="button"
                        onClick={() => void handleDownloadBackup()}
                        disabled={backupLoading}
                    >
                        {backupLoading ? "Выполнение..." : "Сохранить резервную копию"}
                    </button>
                </div>

                {backupMessage && <div className="maintenance-backup-panel__message">{backupMessage}</div>}
                {backupError && <pre className="error-box">{backupError}</pre>}
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
                <div className="maintenance-summary__item">
                    <span>Потребление CPU</span>
                    <strong>{formatPercent(totals.totalCpuPercent)}</strong>
                </div>
                <div className="maintenance-summary__item">
                    <span>Потребление памяти</span>
                    <strong>{formatBytes(totals.totalMemoryUsageBytes)}</strong>
                    <strong>({formatPercent(totals.totalMemoryPercent)})</strong>
                </div>
                <div className="maintenance-summary__item">
                    <span>Всего памяти</span>
                    <strong>{formatBytes(totals.memoryLimitBytes)}</strong>
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
                                    <div className="maintenance-container-cell">
                                        <button
                                            className="maintenance-logs-button"
                                            type="button"
                                            title="Показать логи"
                                            aria-label={`Показать логи ${container.name}`}
                                            onClick={() => void openLogs(container)}
                                        >
                                            ▼
                                        </button>
                                        <div className="maintenance-container-name">
                                            {container.name}
                                        </div>
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

            {logsDialog && (
                <div className="maintenance-logs-backdrop" onClick={closeLogs}>
                    <div
                        className="maintenance-logs-dialog"
                        role="dialog"
                        aria-modal="true"
                        aria-label={`Логи контейнера ${logsDialog.container.name}`}
                        onClick={(event) => event.stopPropagation()}
                    >
                        <div className="maintenance-logs-dialog__header">
                            <div>
                                <h3>Логи контейнера</h3>
                                <p>{logsDialog.container.name}</p>
                            </div>
                            <button
                                className="maintenance-logs-dialog__close"
                                type="button"
                                onClick={closeLogs}
                                aria-label="Закрыть"
                            >
                                ×
                            </button>
                        </div>

                        <div className="maintenance-logs-dialog__toolbar">
                            <label>
                                Последние строки
                                <select
                                    value={logsDialog.tail}
                                    onChange={(event) => handleLogsTailChange(Number(event.target.value) as LogsTail)}
                                    disabled={logsDialog.loading}
                                >
                                    <option value={100}>100</option>
                                    <option value={1000}>1000</option>
                                    <option value={10000}>10000</option>
                                </select>
                            </label>

                            <button
                                className="secondary-button"
                                type="button"
                                onClick={() => void openLogs(logsDialog.container, logsDialog.tail)}
                                disabled={logsDialog.loading}
                            >
                                {logsDialog.loading ? "Загрузка..." : "Обновить логи"}
                            </button>
                        </div>

                        {logsDialog.error && <pre className="error-box">{logsDialog.error}</pre>}

                        <pre
                            ref={logsContentRef}
                            className="maintenance-logs-content"
                        >
                            {logsDialog.loading && !logsDialog.logs
                                ? "Загрузка логов..."
                                : logsDialog.logs || "Логи пустые."}
                        </pre>
                    </div>
                </div>
            )}
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


function buildFallbackBackupFilename(): string {
    const now = new Date();
    const pad = (value: number) => value.toString().padStart(2, "0");

    return [
        "cmnc_databases_",
        now.getFullYear(),
        "-",
        pad(now.getMonth() + 1),
        "-",
        pad(now.getDate()),
        "_",
        pad(now.getHours()),
        "-",
        pad(now.getMinutes()),
        "-",
        pad(now.getSeconds()),
        ".tar",
    ].join("");
}
