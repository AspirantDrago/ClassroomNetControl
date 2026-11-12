import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { NotificationContext, type NotificationContent, type NotificationKind } from "./notificationContext";
import "./Notifications.css";

const configuredDuration = Number(import.meta.env.VITE_NOTIFICATION_DURATION_MS);
const duration = Number.isFinite(configuredDuration) && configuredDuration > 0 ? configuredDuration : 5000;
const configuredAnimationDuration = Number(import.meta.env.VITE_NOTIFICATION_ANIMATION_DURATION_MS);
const animationDuration = Number.isFinite(configuredAnimationDuration) && configuredAnimationDuration >= 0 ? configuredAnimationDuration : 300;
type Item = {id: number; content: NotificationContent; kind: NotificationKind};
let nextId = 0;

function Toast({item, dismiss}: {item: Item; dismiss: (id: number) => void}) {
    const [leaving, setLeaving] = useState(false);
    useEffect(() => {
        const timer = window.setTimeout(() => setLeaving(true), duration);
        return () => window.clearTimeout(timer);
    }, []);
    useEffect(() => {
        if (!leaving) return;
        const timer = window.setTimeout(() => dismiss(item.id), animationDuration);
        return () => window.clearTimeout(timer);
    }, [leaving, item.id, dismiss]);
    return <div className={`site-notification site-notification-${item.kind}${leaving ? " site-notification-leaving" : ""}`}
        style={{"--notification-animation-duration": `${animationDuration}ms`} as CSSProperties}
        role={item.kind === "error" ? "alert" : "status"}>
        <div className="site-notification-content">
            {typeof item.content === "string" ? item.content : <>
                <div>{item.content.context}: <strong>{item.content.action}</strong>.</div>
                {item.content.items.length > 0 && <ul>{item.content.items.map(text => <li key={text}>{text}</li>)}</ul>}
            </>}
        </div>
        <button type="button" aria-label="Закрыть уведомление" disabled={leaving} onClick={() => setLeaving(true)}>×</button>
    </div>;
}

export function Notifications({children}: {children: ReactNode}) {
    const [items, setItems] = useState<Item[]>([]);
    const notify = useCallback((content: NotificationContent, kind: NotificationKind = "success") => {
        setItems(previous => [...previous, {id: ++nextId, content, kind}]);
    }, []);
    const dismiss = useCallback((id: number) => setItems(previous => previous.filter(item => item.id !== id)), []);
    return <NotificationContext.Provider value={notify}>
        {children}
        <div className="site-notifications" aria-label="Уведомления">
            {items.map(item => <Toast key={item.id} item={item} dismiss={dismiss}/>)}
        </div>
    </NotificationContext.Provider>;
}
