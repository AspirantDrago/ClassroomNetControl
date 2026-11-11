import { useCallback, useEffect, useState, type ReactNode } from "react";
import { NotificationContext, type NotificationKind } from "./notificationContext";
import "./Notifications.css";

const configuredDuration = Number(import.meta.env.VITE_NOTIFICATION_DURATION_MS);
const duration = Number.isFinite(configuredDuration) && configuredDuration > 0 ? configuredDuration : 5000;
type Item = {id: number; text: string; kind: NotificationKind};
let nextId = 0;

function Toast({item, dismiss}: {item: Item; dismiss: (id: number) => void}) {
    useEffect(() => {
        const timer = window.setTimeout(() => dismiss(item.id), duration);
        return () => window.clearTimeout(timer);
    }, [item.id, dismiss]);
    return <div className={`site-notification site-notification-${item.kind}`} role={item.kind === "error" ? "alert" : "status"}>
        <span>{item.text}</span>
        <button type="button" aria-label="Закрыть уведомление" onClick={() => dismiss(item.id)}>×</button>
    </div>;
}

export function Notifications({children}: {children: ReactNode}) {
    const [items, setItems] = useState<Item[]>([]);
    const notify = useCallback((text: string, kind: NotificationKind = "success") => {
        setItems(previous => [...previous, {id: ++nextId, text, kind}]);
    }, []);
    const dismiss = useCallback((id: number) => setItems(previous => previous.filter(item => item.id !== id)), []);
    return <NotificationContext.Provider value={notify}>
        {children}
        <div className="site-notifications" aria-label="Уведомления">
            {items.map(item => <Toast key={item.id} item={item} dismiss={dismiss}/>)}
        </div>
    </NotificationContext.Provider>;
}
