import { createContext, useContext } from "react";
import type { VeyonBulkActionResult } from "../../api";

export type NotificationKind = "success" | "warning" | "error" | "neutral";
export type NotificationContent = string | {context: string; action: string; items: string[]};
export type Notify = (content: NotificationContent, kind?: NotificationKind) => void;
export const NotificationContext = createContext<Notify>(() => {});
export function useNotify() { return useContext(NotificationContext); }

export function bulkNotification(context: string, action: string, result: VeyonBulkActionResult) {
    const timeout = result.timeout_count ?? 0;
    const errors = Math.max(0, result.failed_count - timeout);
    const items = [
        result.accepted_count ? `Успешно: ${result.accepted_count}` : "",
        errors ? `С ошибкой: ${errors}` : "",
        timeout ? `Не выполнено: ${timeout}` : "",
        result.skipped_count ? `Пропущено: ${result.skipped_count}` : "",
    ].filter(Boolean);
    return {content: {context, action, items},
        kind: (errors ? result.accepted_count ? "warning" : "error" : result.accepted_count ? "success" : "neutral") as NotificationKind};
}
