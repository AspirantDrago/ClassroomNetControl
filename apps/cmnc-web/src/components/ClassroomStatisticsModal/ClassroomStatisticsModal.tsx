import { type MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    clearAccessToken,
    extractErrorDetail,
    getAccessToken,
} from "../../api";
import { REFRESH_INTERVALS } from "../../config/refreshIntervals";
import { formatUsername } from "../../utils/usernames";
import "./ClassroomStatisticsModal.css";


const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const TICK_COUNT = 7;


type StatisticsRangeMinutes = 10080 | 1440 | 240 | 40;


type StatisticsRangeOption = {
    value: StatisticsRangeMinutes;
    label: string;
    description: string;
};


const DEFAULT_STATISTICS_RANGE_MINUTES: StatisticsRangeMinutes = 1440;
const STATISTICS_RANGE_OPTIONS: StatisticsRangeOption[] = [
    {
        value: 10080,
        label: "Неделя",
        description: "последнюю неделю",
    },
    {
        value: 1440,
        label: "24 часа",
        description: "последние 24 часа",
    },
    {
        value: 240,
        label: "4 часа",
        description: "последние 4 часа",
    },
    {
        value: 40,
        label: "40 минут",
        description: "последние 40 минут",
    },
];


type StatisticsSegment = {
    start_at: string;
    end_at: string;
    state: string;
    username?: string | null;
};


type DeviceStatisticsItem = {
    device_id: number;
    is_non_pc?: boolean;
    name: string;
    ip_address: string | null;
    availability: StatisticsSegment[];
    wan: StatisticsSegment[];
    users?: StatisticsSegment[];
};


type ClassroomStatisticsResponse = {
    classroom_id: number;
    start_at: string;
    end_at: string;
    devices: DeviceStatisticsItem[];
};


type StatisticsLoadMode = "initial" | "interactive" | "background";


type ClassroomStatisticsButtonProps = {
    classroomId: number;
    classroomName: string;
};


export function ClassroomStatisticsButton(props: ClassroomStatisticsButtonProps) {
    const { classroomId, classroomName } = props;
    const [opened, setOpened] = useState(false);

    return (
        <>
            <button
                type="button"
                className="secondary-button classroom-statistics-button"
                onClick={() => setOpened(true)}
            >
                Статистика
            </button>

            {opened && (
                <ClassroomStatisticsModal
                    classroomId={classroomId}
                    classroomName={classroomName}
                    onClose={() => setOpened(false)}
                />
            )}
        </>
    );
}


type ClassroomStatisticsModalProps = ClassroomStatisticsButtonProps & {
    onClose: () => void;
};


function ClassroomStatisticsModal(props: ClassroomStatisticsModalProps) {
    const { classroomId, classroomName, onClose } = props;
    const [rangeMinutes, setRangeMinutes] = useState<StatisticsRangeMinutes>(
        DEFAULT_STATISTICS_RANGE_MINUTES,
    );
    const [statistics, setStatistics] = useState<ClassroomStatisticsResponse | null>(null);
    const [displayedRangeMinutes, setDisplayedRangeMinutes] =
        useState<StatisticsRangeMinutes>(DEFAULT_STATISTICS_RANGE_MINUTES);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const requestAbortControllerRef = useRef<AbortController | null>(null);
    const hasLoadedStatisticsRef = useRef(false);

    const selectedRange = useMemo(() => {
        return STATISTICS_RANGE_OPTIONS.find((option) => option.value === rangeMinutes)
            ?? STATISTICS_RANGE_OPTIONS[1];
    }, [rangeMinutes]);

    const loadStatistics = useCallback(async (mode: StatisticsLoadMode) => {
        if (mode === "background" && requestAbortControllerRef.current !== null) {
            return;
        }

        requestAbortControllerRef.current?.abort();

        const abortController = new AbortController();
        requestAbortControllerRef.current = abortController;

        if (mode === "initial") {
            setLoading(true);
            setError(null);
        } else if (mode === "interactive") {
            setRefreshing(true);
            setError(null);
        }

        try {
            const data = await requestStatistics(
                classroomId,
                rangeMinutes,
                abortController.signal,
            );

            if (!abortController.signal.aborted) {
                setStatistics((current) => mergeStatisticsGraphs(current, data));
                setDisplayedRangeMinutes(rangeMinutes);
                hasLoadedStatisticsRef.current = true;
                setError(null);
            }
        } catch (err) {
            if (abortController.signal.aborted) {
                return;
            }

            if (mode !== "background") {
                setError(extractErrorDetail(err));
            }
        } finally {
            if (requestAbortControllerRef.current === abortController) {
                requestAbortControllerRef.current = null;

                if (mode === "initial") {
                    setLoading(false);
                } else if (mode === "interactive") {
                    setRefreshing(false);
                }
            }
        }
    }, [classroomId, rangeMinutes]);

    useEffect(() => {
        const mode: StatisticsLoadMode = hasLoadedStatisticsRef.current
            ? "interactive"
            : "initial";
        void loadStatistics(mode);

        const timerId = window.setInterval(() => {
            if (document.visibilityState === "visible") {
                void loadStatistics("background");
            }
        }, REFRESH_INTERVALS.statistics);

        return () => {
            window.clearInterval(timerId);
            requestAbortControllerRef.current?.abort();
        };
    }, [loadStatistics]);

    useEffect(() => {
        function handleKeyDown(event: KeyboardEvent) {
            if (event.key === "Escape") {
                onClose();
            }
        }

        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [onClose]);

    const ticks = useMemo(() => {
        if (!statistics) {
            return [];
        }

        const start = Date.parse(statistics.start_at);
        const end = Date.parse(statistics.end_at);
        const duration = end - start;

        return Array.from({ length: TICK_COUNT }, (_, index) => {
            const timestamp = start + duration * (index / (TICK_COUNT - 1));
            return {
                position: index / (TICK_COUNT - 1) * 100,
                label: formatTick(timestamp, displayedRangeMinutes),
            };
        });
    }, [displayedRangeMinutes, statistics]);

    return (
        <div className="statistics-backdrop" onMouseDown={onClose}>
            <div
                className="statistics-modal"
                role="dialog"
                aria-modal="true"
                aria-label={`Статистика аудитории ${classroomName}`}
                onMouseDown={(event: MouseEvent<HTMLDivElement>) => event.stopPropagation()}
            >
                <div className="statistics-header">
                    <div>
                        <h3>Статистика — {classroomName}</h3>
                        <div className="muted">
                            Доступность устройств, состояние WAN и пользователи за {selectedRange.description}
                        </div>
                    </div>

                    <div className="statistics-header-actions">
                        <label className="statistics-range-control">
                            <span>Период</span>
                            <select
                                value={rangeMinutes}
                                onChange={(event) =>
                                    setRangeMinutes(
                                        Number(event.target.value) as StatisticsRangeMinutes,
                                    )
                                }
                            >
                                {STATISTICS_RANGE_OPTIONS.map((option) => (
                                    <option key={option.value} value={option.value}>
                                        {option.label}
                                    </option>
                                ))}
                            </select>
                        </label>

                        <button
                            type="button"
                            className="secondary-button statistics-refresh-button"
                            aria-label="Обновить"
                            title="Обновить"
                            aria-busy={refreshing}
                            disabled={loading || refreshing}
                            onClick={() => void loadStatistics("interactive")}
                        >
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                <path d="M20 7v5h-5M4 17v-5h5" />
                                <path d="M6 7a7 7 0 0 1 12-2l2 2M4 17l2 2a7 7 0 0 0 12-2" />
                            </svg>
                        </button>
                        <button
                            className="statistics-close-button"
                            type="button"
                            onClick={onClose}
                            aria-label="Закрыть"
                        >
                            ×
                        </button>
                    </div>
                </div>

                <StatisticsLegend />

                {error && <pre className="error-box">{error}</pre>}
                {loading && statistics === null && (
                    <div className="loading">Загрузка статистики...</div>
                )}

                {statistics && statistics.devices.length === 0 && (
                    <div className="muted statistics-empty">В аудитории нет закреплённых устройств.</div>
                )}

                {statistics && statistics.devices.length > 0 && (
                    <div className="statistics-scroll">
                        <div className="statistics-chart">
                            <div className="statistics-time-row">
                                <div className="statistics-device-heading">Устройство</div>
                                <div className="statistics-time-axis">
                                    {ticks.map((tick) => (
                                        <div
                                            key={`${tick.position}-${tick.label}`}
                                            className="statistics-tick"
                                            style={{ left: `${tick.position}%` }}
                                        >
                                            <span>{tick.label}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {statistics.devices.map((device) => (
                                <StatisticsDeviceRow
                                    key={device.device_id}
                                    device={device}
                                    startAt={statistics.start_at}
                                    endAt={statistics.end_at}
                                />
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}


function mergeStatisticsGraphs(
    current: ClassroomStatisticsResponse | null,
    next: ClassroomStatisticsResponse,
): ClassroomStatisticsResponse {
    if (current === null || current.classroom_id !== next.classroom_id) {
        return next;
    }

    const nextDevicesById = new Map(
        next.devices.map((device) => [device.device_id, device]),
    );

    return {
        classroom_id: next.classroom_id,
        start_at: next.start_at,
        end_at: next.end_at,
        devices: current.devices.map((device) => {
            const nextDevice = nextDevicesById.get(device.device_id);

            return {
                ...device,
                availability: nextDevice?.availability ?? [],
                wan: nextDevice?.wan ?? [],
                users: nextDevice?.users ?? [],
                is_non_pc: nextDevice?.is_non_pc ?? device.is_non_pc,
            };
        }),
    };
}


function StatisticsLegend() {
    return (
        <div className="statistics-legend">
            <LegendItem className="statistics-legend-online" label="В сети" />
            <LegendItem className="statistics-legend-wan-blocked" label="WAN отключён" />
            <LegendItem className="statistics-legend-wan-allowed" label="WAN разрешён" />
            <LegendItem className="statistics-legend-wan-protected" label="WAN защищён администратором" />
            <LegendItem className="statistics-legend-user-absent" label="Нет пользователя" />
            <LegendItem className="statistics-legend-user-present" label="Пользователь авторизован" />
            <LegendItem className="statistics-legend-user-unknown" label="Пропуск в истории пользователей — нет данных" />
        </div>
    );
}


function LegendItem(props: { className: string; label: string }) {
    return (
        <div className="statistics-legend-item">
            <span className={props.className} />
            {props.label}
        </div>
    );
}


function StatisticsDeviceRow(props: {
    device: DeviceStatisticsItem;
    startAt: string;
    endAt: string;
}) {
    const { device, startAt, endAt } = props;

    return (
        <div className="statistics-device-row">
            <div className="statistics-device-info">
                <strong>{device.name}</strong>
                <span>{device.ip_address ?? "IP не задан"}</span>
            </div>

            <div className="statistics-lanes">
                {!device.is_non_pc && <StatisticsLane className="statistics-user-lane" segments={device.users ?? []}
                    startAt={startAt} endAt={endAt} />}
                <StatisticsLane
                    className="statistics-availability-lane"
                    segments={device.availability.filter((segment) => segment.state === "online")}
                    startAt={startAt}
                    endAt={endAt}
                />
                <StatisticsLane
                    className="statistics-wan-lane"
                    segments={device.wan}
                    startAt={startAt}
                    endAt={endAt}
                />
            </div>
        </div>
    );
}


function StatisticsLane(props: {
    className: string;
    segments: StatisticsSegment[];
    startAt: string;
    endAt: string;
}) {
    const { className, segments, startAt, endAt } = props;

    return (
        <div className={`statistics-lane ${className}`}>
            {segments.map((segment, index) => {
                const position = getSegmentPosition(segment, startAt, endAt);

                if (position.width <= 0) {
                    return null;
                }

                return (
                    <div
                        key={`${segment.start_at}-${segment.end_at}-${segment.state}-${index}`}
                        className={`statistics-segment statistics-segment-${segment.state}`}
                        style={{
                            left: `${position.left}%`,
                            width: `${position.width}%`,
                        }}
                        title={formatSegmentTitle(segment)}
                    />
                );
            })}
        </div>
    );
}


function getSegmentPosition(
    segment: StatisticsSegment,
    startAt: string,
    endAt: string,
): { left: number; width: number } {
    const rangeStart = Date.parse(startAt);
    const rangeEnd = Date.parse(endAt);
    const duration = Math.max(rangeEnd - rangeStart, 1);
    const segmentStart = Math.min(Math.max(Date.parse(segment.start_at), rangeStart), rangeEnd);
    const segmentEnd = Math.min(Math.max(Date.parse(segment.end_at), rangeStart), rangeEnd);

    return {
        left: (segmentStart - rangeStart) / duration * 100,
        width: Math.max(segmentEnd - segmentStart, 0) / duration * 100,
    };
}


function formatSegmentTitle(segment: StatisticsSegment): string {
    const user = segment.state === "user_present" && segment.username ? ` (${formatUsername(segment.username)})` : "";
    return `${formatState(segment.state)}${user}: ${formatDateTime(segment.start_at)} — ${formatDateTime(segment.end_at)}`;
}


function formatState(state: string): string {
    const labels: Record<string, string> = {
        user_absent: "Нет пользователя",
        user_present: "Пользователь авторизован",
        online: "В сети",
        offline: "Не в сети",
        allowed: "WAN разрешён",
        blocked: "WAN отключён",
        protected: "WAN защищён администратором",
    };

    return labels[state] ?? state;
}


function formatTick(timestamp: number, rangeMinutes: StatisticsRangeMinutes): string {
    if (rangeMinutes <= 240) {
        return new Date(timestamp).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    return new Date(timestamp).toLocaleString([], {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}


function formatDateTime(value: string): string {
    return new Date(value).toLocaleString().replace(",", "");
}


async function requestStatistics(
    classroomId: number,
    rangeMinutes: StatisticsRangeMinutes,
    signal: AbortSignal,
): Promise<ClassroomStatisticsResponse> {
    const token = getAccessToken();
    const searchParams = new URLSearchParams({
        range_minutes: rangeMinutes.toString(),
    });
    const response = await fetch(
        `${API_BASE_URL}/api/classrooms/${classroomId}/statistics?${searchParams.toString()}`,
        {
            signal,
            headers: {
                "Content-Type": "application/json",
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
        },
    );

    if (response.status === 401) {
        clearAccessToken();
    }

    if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `HTTP ${response.status}`);
    }

    return await response.json() as ClassroomStatisticsResponse;
}
