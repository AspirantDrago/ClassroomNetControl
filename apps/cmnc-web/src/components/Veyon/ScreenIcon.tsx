type IconName = "snapshot" | "record" | "pause" | "play" | "stop" | "cancel" | "fullscreen" | "window" | "back" | "keyboard";
export function ScreenIcon({name}: {name: IconName}) {
    const shapes = {
        snapshot: <><path d="M4 6h4l2-3h4l2 3h4v14H4Z"/><circle cx="12" cy="13" r="4"/></>,
        record: <circle cx="12" cy="12" r="7" fill="currentColor" stroke="none"/>,
        pause: <><path d="M8 5v14M16 5v14" strokeWidth="4"/></>,
        play: <path d="m8 4 12 8-12 8Z"/>,
        stop: <rect x="5" y="5" width="14" height="14" rx="1"/>,
        cancel: <path d="m6 6 12 12M18 6 6 18"/>,
        fullscreen: <path d="M9 3H3v6M15 3h6v6M3 15v6h6M21 15v6h-6"/>,
        window: <><path d="M14 3h7v7M21 3l-9 9"/><path d="M10 5H3v16h16v-7"/></>,
        back: <><path d="M10 5H3v16h16v-7M21 3l-9 9M12 5v7h7"/></>,
        keyboard: <><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 9h1m3 0h1m3 0h1m3 0h1M6 12h1m3 0h1m3 0h1m3 0h1M7 16h10"/></>,
    };
    return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{shapes[name]}</svg>;
}
