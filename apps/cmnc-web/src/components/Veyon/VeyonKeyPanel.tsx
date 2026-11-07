import { useEffect, useState, type FormEvent } from "react";
import { deleteVeyonKey, extractErrorDetail, getVeyonKey, saveVeyonKey } from "../../api";
import "./Veyon.css";

export function VeyonKeyPanel({ scope, scopeId }: { scope: "router" | "classroom"; scopeId: number }) {
    const [name, setName] = useState("CMNC");
    const [pem, setPem] = useState("");
    const [configured, setConfigured] = useState(false);
    const [override, setOverride] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        getVeyonKey(scope, scopeId).then((result) => {
            if (!cancelled) {
                setConfigured(result.configured);
                setName(result.key_name);
                setOverride(result.router_override ?? false);
            }
        }).catch((err) => { if (!cancelled) setError(extractErrorDetail(err)); });
        return () => { cancelled = true; };
    }, [scope, scopeId]);

    async function save(event: FormEvent) {
        event.preventDefault();
        setBusy(true); setError(null); setMessage(null);
        try {
            await saveVeyonKey(scope, scopeId, name, pem);
            setPem(""); setConfigured(true); setMessage("Ключ Veyon сохранён.");
        } catch (err) { setError(extractErrorDetail(err)); }
        finally { setBusy(false); }
    }

    async function remove() {
        if (!window.confirm("Удалить сохранённый ключ Veyon?")) return;
        setBusy(true); setError(null); setMessage(null);
        try {
            await deleteVeyonKey(scope, scopeId);
            setConfigured(false); setPem(""); setMessage("Ключ Veyon удалён.");
        } catch (err) { setError(extractErrorDetail(err)); }
        finally { setBusy(false); }
    }

    return <section className="veyon-key-panel">
        <h4>Veyon — ключ аутентификации</h4>
        <p className="muted">{scope === "router"
            ? "Ключ MikroTik применяется ко всем его аудиториям и имеет приоритет над их ключами."
            : override ? "Для MikroTik уже задан ключ — он имеет приоритет над ключом аудитории."
                : "Ключ аудитории используется, если для MikroTik ключ не задан."}</p>
        <p>{configured ? "Приватный ключ сохранён на сервере." : "Собственный ключ не задан."}</p>
        {error && <p className="device-modal-error" role="alert">{error}</p>}
        {message && <p role="status">{message}</p>}
        <form onSubmit={(event) => void save(event)} className="veyon-key-form">
            <label>Имя ключа Veyon
                <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={128} />
            </label>
            <label>Файл приватного ключа (.pem)
                <input type="file" accept=".pem,.key,text/plain" onChange={async (event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    if (file.size > 65536) { setError("Файл ключа больше 64 КБ."); return; }
                    try { setPem(await file.text()); setError(null); }
                    catch { setError("Не удалось прочитать файл ключа."); }
                }} />
            </label>
            <label>Приватный ключ PEM {configured ? "(новый, для замены)" : ""}
                <textarea value={pem} onChange={(event) => setPem(event.target.value)} rows={5}
                    autoComplete="off" spellCheck={false} maxLength={65536} placeholder="-----BEGIN ... PRIVATE KEY-----" />
            </label>
            <div className="veyon-key-actions">
                {configured && <button type="button" className="danger-button" disabled={busy} onClick={() => void remove()}>Удалить ключ Veyon</button>}
                <button type="submit" className="primary-button" disabled={busy || !pem.trim() || !name.trim()}>
                    {busy ? "Сохранение..." : "Сохранить ключ Veyon"}
                </button>
            </div>
        </form>
    </section>;
}
