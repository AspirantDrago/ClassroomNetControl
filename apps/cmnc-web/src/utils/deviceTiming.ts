const pluralRules = new Intl.PluralRules("ru");

function formatUnit(value: number, one: string, few: string, many: string): string {
    const form = pluralRules.select(value);
    return `${value} ${form === "one" ? one : form === "few" ? few : many}`;
}

export function formatStateDuration(since: string | null | undefined, now: number): string {
    if (!since) return "Нет данных";
    const timestamp = Date.parse(since);
    if (!Number.isFinite(timestamp)) return "Нет данных";

    const totalMinutes = Math.max(0, Math.floor((now - timestamp) / 60_000));
    const days = Math.floor(totalMinutes / 1440);
    const hours = Math.floor((totalMinutes % 1440) / 60);
    const minutes = totalMinutes % 60;
    const parts: string[] = [];
    if (days) parts.push(formatUnit(days, "день", "дня", "дней"));
    if (hours) parts.push(formatUnit(hours, "час", "часа", "часов"));
    if (minutes) parts.push(formatUnit(minutes, "минута", "минуты", "минут"));
    return parts.join(" ") || "Меньше минуты";
}

export function formatStateTime(since: string | null | undefined): string {
    if (!since) return "Нет данных";
    const date = new Date(since);
    if (!Number.isFinite(date.getTime())) return "Нет данных";
    return date.toLocaleString("ru-RU");
}
