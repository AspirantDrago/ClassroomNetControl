import { type FormEvent, useEffect, useState } from "react";
import {
    extractErrorDetail,
    type CurrentPrincipal,
    updateCurrentAccount,
} from "../../api";
import "./AccountPage.css";

type AccountPageProps = {
    principal: CurrentPrincipal;
    onPrincipalChanged: (principal: CurrentPrincipal) => void;
};

export function AccountPage({ principal, onPrincipalChanged }: AccountPageProps) {
    const [displayName, setDisplayName] = useState(principal.display_name ?? "");
    const [password, setPassword] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [saved, setSaved] = useState(false);

    useEffect(() => {
        setDisplayName(principal.display_name ?? "");
        setPassword("");
        setError(null);
        setSaved(false);
    }, [principal.id, principal.display_name]);

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        const nextDisplayName = displayName.trim();
        const nextPassword = password.trim();

        if (!nextDisplayName) {
            setError("Заполните отображаемое имя.");
            setSaved(false);
            return;
        }

        setBusy(true);
        setError(null);
        setSaved(false);

        try {
            const updatedPrincipal = await updateCurrentAccount({
                display_name: nextDisplayName,
                ...(nextPassword ? { password: nextPassword } : {}),
            });

            onPrincipalChanged(updatedPrincipal);
            setPassword("");
            setSaved(true);
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusy(false);
        }
    }

    return (
        <section className="account-page">
            <div className="account-card">
                <div className="account-card__header">
                    <h2>Учётная запись</h2>
                    <p className="muted">
                        Здесь можно изменить только отображаемое имя и пароль.
                    </p>
                </div>

                {error && <pre className="error-box">{error}</pre>}
                {saved && <div className="account-success">Изменения сохранены.</div>}

                <form className="account-form" onSubmit={handleSubmit}>
                    <label>
                        Отображаемое имя
                        <input
                            autoComplete="name"
                            value={displayName}
                            onChange={(event) => {
                                setDisplayName(event.target.value);
                                setSaved(false);
                            }}
                        />
                    </label>

                    <label>
                        Новый пароль
                        <input
                            autoComplete="new-password"
                            type="password"
                            value={password}
                            placeholder="Оставьте пустым, чтобы не менять"
                            onChange={(event) => {
                                setPassword(event.target.value);
                                setSaved(false);
                            }}
                        />
                    </label>

                    <div className="account-form__actions">
                        <button
                            className="primary-button"
                            disabled={busy || displayName.trim() === ""}
                            type="submit"
                        >
                            {busy ? "Сохранение..." : "Сохранить"}
                        </button>
                    </div>
                </form>
            </div>
        </section>
    );
}
