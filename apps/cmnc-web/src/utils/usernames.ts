/** Remove Windows domain notation for display only; never modify stored logins. */
export function formatUsername(value: string | null | undefined): string {
    const login = (value ?? "").split("\\").at(-1) ?? "";
    const separator = login.indexOf("@");
    return separator > 0 ? login.slice(0, separator) : login;
}
