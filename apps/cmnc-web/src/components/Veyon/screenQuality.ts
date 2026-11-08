export const SCREEN_QUALITIES = {
    veryLow: { label: "Низкое — до 600 px", width: 600, quality: 45 },
    low: { label: "Экономное — до 854 px", width: 854, quality: 60 },
    medium: { label: "Среднее — до 1280 px", width: 1280, quality: 75 },
    high: { label: "Высокое — до 1920 px", width: 1920, quality: 95 },
    maximum: { label: "Максимальное — до 1920 px", width: 1920, quality: 100 },
};
export type ScreenQuality = keyof typeof SCREEN_QUALITIES;
const COOKIE = "cmnc_screen_quality";
export function readScreenQuality(): ScreenQuality {
    const value = document.cookie.split(";").map(part => part.trim()).find(part => part.startsWith(`${COOKIE}=`))?.slice(COOKIE.length + 1);
    return value && Object.hasOwn(SCREEN_QUALITIES, value) ? value as ScreenQuality : "low";
}
export function saveScreenQuality(value: ScreenQuality) {
    document.cookie = `${COOKIE}=${value}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
}

