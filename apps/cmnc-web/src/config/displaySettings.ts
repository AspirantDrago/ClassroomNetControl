import { useMemo, useState } from "react";
import type { CurrentPrincipal } from "../api";

export type DisplaySettings = {
    showInactiveClassrooms: boolean;
    showInactiveUsers: boolean;
    showInactiveWorkstations: boolean;
};
const defaults: DisplaySettings = {showInactiveClassrooms: false, showInactiveUsers: false, showInactiveWorkstations: false};
export function useDisplaySettings(principal: CurrentPrincipal | null): [DisplaySettings, (settings: DisplaySettings) => void] {
    const key = `cmnc-display-settings:${principal?.principal_type ?? "user"}:${principal?.user_id ?? principal?.id ?? principal?.username ?? "anonymous"}`;
    const [changes, setChanges] = useState<Record<string, DisplaySettings>>({});
    const settings = useMemo(() => {
        if (changes[key]) return changes[key];
        try {
            const value = JSON.parse(localStorage.getItem(key) ?? "null");
            return {showInactiveClassrooms: value?.showInactiveClassrooms === true,
                showInactiveUsers: value?.showInactiveUsers === true,
                showInactiveWorkstations: value?.showInactiveWorkstations === true};
        } catch { return defaults; }
    }, [key, changes]);
    return [settings, next => {
        try {localStorage.setItem(key, JSON.stringify(next));} catch { /* Keep preferences for this session if storage is unavailable. */ }
        setChanges(previous => ({...previous, [key]: next}));
    }];
}
