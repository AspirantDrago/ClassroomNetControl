const MIN_REFRESH_INTERVAL_MS = 1_000;

function readRefreshInterval(rawValue: string | undefined, fallbackMs: number, minimumMs = MIN_REFRESH_INTERVAL_MS): number {
    if (rawValue === undefined || rawValue.trim() === "") {
        return fallbackMs;
    }

    const parsed = Number(rawValue);

    if (!Number.isSafeInteger(parsed) || parsed < minimumMs) {
        console.warn(
            `Некорректный интервал обновления "${rawValue}". Используется ${fallbackMs} мс.`,
        );
        return fallbackMs;
    }

    return parsed;
}

export const REFRESH_INTERVALS = Object.freeze({
    thumbnails: readRefreshInterval(import.meta.env.VITE_THUMBNAIL_REFRESH_INTERVAL_MS, 1000, 100),
    dashboard: readRefreshInterval(
        import.meta.env.VITE_DASHBOARD_REFRESH_INTERVAL_MS,
        5_000,
    ),
    adminPresence: readRefreshInterval(
        import.meta.env.VITE_ADMIN_PRESENCE_REFRESH_INTERVAL_MS,
        30_000,
    ),
    maintenance: readRefreshInterval(
        import.meta.env.VITE_MAINTENANCE_REFRESH_INTERVAL_MS,
        5_000,
    ),
    routers: readRefreshInterval(
        import.meta.env.VITE_ROUTERS_REFRESH_INTERVAL_MS,
        5_000,
    ),
    statistics: readRefreshInterval(
        import.meta.env.VITE_STATISTICS_REFRESH_INTERVAL_MS,
        30_000,
    ),
});
