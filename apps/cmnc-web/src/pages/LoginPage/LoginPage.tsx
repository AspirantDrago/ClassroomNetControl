import { type FormEvent, useState } from "react";
import "./LoginPage.css";

type LoginPageProps = {
    busy: boolean;
    error: string | null;
    onLogin: (username: string, password: string) => Promise<void>;
};

export function LoginPage({ busy, error, onLogin }: LoginPageProps) {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        await onLogin(username, password);
        setPassword("");
    }

    return (
        <div className="page auth-page">
            <form className="login-card" onSubmit={handleSubmit}>
                <div>
                    <h1>Classroom MikroTik Net Control</h1>
                    <p className="muted">Войдите, чтобы управлять аудиториями.</p>
                </div>

                {error && <pre className="error-box">{error}</pre>}

                <label>
                    Логин
                    <input
                        autoComplete="username"
                        value={username}
                        onChange={(event) => setUsername(event.target.value)}
                    />
                </label>

                <label>
                    Пароль
                    <input
                        autoComplete="current-password"
                        type="password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                    />
                </label>

                <button
                    className="primary-button"
                    type="submit"
                    disabled={busy || username.trim() === ""}
                >
                    {busy ? "Вход..." : "Войти"}
                </button>
            </form>
        </div>
    );
}
