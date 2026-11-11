import { createContext, useContext } from "react";
import type { VeyonBulkActionResult } from "../../api";

export type NotificationKind = "success" | "warning" | "error";
export type Notify = (text: string, kind?: NotificationKind) => void;
export const NotificationContext = createContext<Notify>(() => {});
export function useNotify() { return useContext(NotificationContext); }

export function bulkNotification(title: string, result: VeyonBulkActionResult) {
    const timeout = result.timeout_count ?? 0;
    const errors = Math.max(0, result.failed_count - timeout);
    const counts = [
        result.accepted_count ? `Успешно: ${result.accepted_count}` : "",
        errors ? `С ошибкой: ${errors}` : "",
        timeout ? `Не выполнено (тайм-аут): ${timeout}` : "",
        result.skipped_count ? `Пропущено защищённых: ${result.skipped_count}` : "",
    ].filter(Boolean);
    return {text: `${title}. ${counts.join(". ") || "Нет устройств для выполнения"}.`,
        kind: (result.failed_count ? result.accepted_count ? "warning" : "error" : "success") as NotificationKind};
}
