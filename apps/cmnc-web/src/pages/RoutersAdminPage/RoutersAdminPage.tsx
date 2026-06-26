import { type ChangeEvent, type FormEvent, useEffect, useMemo, useState } from "react";
import {
    createAdminRouter,
    extractErrorDetail,
    getAdminRoutersStatus,
    pollAdminRouterNow,
    type AdminRouter,
    type AdminRouterCreateRequest,
    type AdminRouterPollNowResponse,
    type AdminRouterServiceStatus,
    type AdminRouterStatusItem,
    type AdminRouterTestConnectionResponse,
    type AdminRouterUpdateRequest,
    testAdminRouterConnection,
    updateAdminRouter,
} from "../../api";
import "./RoutersAdminPage.css";

type RouterFormState = {
    mode: "create" | "edit";
    router: AdminRouter | null;
    name: string;
    apiHost: string;
    apiPort: string;
    apiUseSsl: boolean;
    apiUsername: string;
    apiPassword: string;
    isEnabled: boolean;
    pollEnabled: boolean;
    syncEnabled: boolean;
    pollIntervalSeconds: string;
};

type RouterTestResultState = {
    routerName: string;
    result: AdminRouterTestConnectionResponse;
};

type RouterPollNowResultState = {
    routerName: string;
    result: AdminRouterPollNowResponse;
};

const EMPTY_FORM: RouterFormState = {
    mode: "create",
    router: null,
    name: "",
    apiHost: "",
    apiPort: "80",
    apiUseSsl: false,
    apiUsername: "cmnc_service",
    apiPassword: "",
    isEnabled: true,
    pollEnabled: true,
    syncEnabled: true,
    pollIntervalSeconds: "10",
};

export function RoutersAdminPage() {
    const [items, setItems] = useState<AdminRouterStatusItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [form, setForm] = useState<RouterFormState | null>(null);
    const [testingRouterId, setTestingRouterId] = useState<number | null>(null);
    const [testResult, setTestResult] = useState<RouterTestResultState | null>(null);
    const [pollingRouterId, setPollingRouterId] = useState<number | null>(null);
    const [pollNowResult, setPollNowResult] = useState<RouterPollNowResultState | null>(null);

    async function loadStatuses(showLoader = false) {
        if (showLoader) {
            setLoading(true);
        }

        setError(null);

        try {
            const data = await getAdminRoutersStatus();
            setItems(data);
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            if (showLoader) {
                setLoading(false);
            }
        }
    }

    useEffect(() => {
        let cancelled = false;

        async function loadInitial() {
            setLoading(true);
            setError(null);

            try {
                const data = await getAdminRoutersStatus();

                if (!cancelled) {
                    setItems(data);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(extractErrorDetail(err));
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        void loadInitial();

        const timerId = window.setInterval(() => {
            getAdminRoutersStatus()
                .then((data) => {
                    if (!cancelled) {
                        setItems(data);
                    }
                })
                .catch(() => {
                    // Фоновое обновление не должно перекрывать экран ошибкой.
                });
        }, 5000);

        return () => {
            cancelled = true;
            window.clearInterval(timerId);
        };
    }, []);

    const sortedItems = useMemo(() => {
        return [...items].sort((left, right) => left.router.id - right.router.id);
    }, [items]);

    function openCreateForm() {
        setError(null);
        setForm({ ...EMPTY_FORM });
    }

    function openEditForm(router: AdminRouter) {
        setError(null);
        setForm({
            mode: "edit",
            router,
            name: router.name,
            apiHost: router.api_host,
            apiPort: router.api_port.toString(),
            apiUseSsl: router.api_use_ssl,
            apiUsername: router.api_username,
            apiPassword: "",
            isEnabled: router.is_enabled,
            pollEnabled: router.poll_enabled,
            syncEnabled: router.sync_enabled,
            pollIntervalSeconds: router.poll_interval_seconds.toString(),
        });
    }

    function closeForm() {
        setForm(null);
    }

    function updateFormString(field: "name" | "apiHost" | "apiPort" | "apiUsername" | "apiPassword" | "pollIntervalSeconds", value: string) {
        setForm((current) => (current === null ? current : { ...current, [field]: value }));
    }

    function updateFormBoolean(field: "apiUseSsl" | "isEnabled" | "pollEnabled" | "syncEnabled", value: boolean) {
        setForm((current) => (current === null ? current : { ...current, [field]: value }));
    }

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (form === null) {
            return;
        }

        setSaving(true);
        setError(null);

        try {
            const name = parseRequiredText(form.name, "Название");
            const apiHost = parseRequiredText(form.apiHost, "Host");
            const apiPort = parseInteger(form.apiPort, "Порт", 1, 65535);
            const apiUsername = parseRequiredText(form.apiUsername, "Логин");
            const pollIntervalSeconds = parseInteger(
                form.pollIntervalSeconds,
                "Интервал опроса",
                1,
                3600,
            );

            if (form.mode === "create") {
                const apiPassword = parseRequiredText(form.apiPassword, "Пароль");
                const payload: AdminRouterCreateRequest = {
                    name,
                    api_host: apiHost,
                    api_port: apiPort,
                    api_use_ssl: form.apiUseSsl,
                    api_username: apiUsername,
                    api_password: apiPassword,
                    is_enabled: form.isEnabled,
                    poll_enabled: form.pollEnabled,
                    sync_enabled: form.syncEnabled,
                    poll_interval_seconds: pollIntervalSeconds,
                };

                await createAdminRouter(payload);
                setForm(null);
                await loadStatuses(false);
                return;
            }

            if (form.router === null) {
                throw new Error("MikroTik не выбран");
            }

            const payload: AdminRouterUpdateRequest = {
                name,
                api_host: apiHost,
                api_port: apiPort,
                api_use_ssl: form.apiUseSsl,
                api_username: apiUsername,
                is_enabled: form.isEnabled,
                poll_enabled: form.pollEnabled,
                sync_enabled: form.syncEnabled,
                poll_interval_seconds: pollIntervalSeconds,
            };

            const password = form.apiPassword.trim();
            if (password !== "") {
                payload.api_password = password;
            }

            await updateAdminRouter(form.router.id, payload);
            setForm(null);
            await loadStatuses(false);
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setSaving(false);
        }
    }

    async function toggleRouter(router: AdminRouter, field: "is_enabled" | "poll_enabled" | "sync_enabled") {
        setError(null);

        try {
            await updateAdminRouter(router.id, {
                [field]: !router[field],
            });
            await loadStatuses(false);
        } catch (err) {
            setError(extractErrorDetail(err));
        }
    }

    async function handleTestConnection(router: AdminRouter) {
        setTestingRouterId(router.id);
        setTestResult(null);
        setError(null);

        try {
            const result = await testAdminRouterConnection(router.id);
            setTestResult({
                routerName: router.name,
                result,
            });
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setTestingRouterId(null);
        }
    }

    async function handlePollNow(router: AdminRouter) {
        setPollingRouterId(router.id);
        setPollNowResult(null);
        setError(null);

        try {
            const result = await pollAdminRouterNow(router.id);
            setPollNowResult({
                routerName: router.name,
                result,
            });
            await loadStatuses(false);
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setPollingRouterId(null);
        }
    }

    return (
        <section className="routers-page">
            <div className="routers-page__header">
                <div>
                    <h2>MikroTik</h2>
                    <p>Настройка маршрутизаторов и состояние worker-ов poller/sync.</p>
                </div>

                <div className="routers-page__actions">
                    <button className="secondary-button" type="button" onClick={() => void loadStatuses(true)}>
                        Обновить
                    </button>
                    <button className="primary-button" type="button" onClick={openCreateForm}>
                        Добавить MikroTik
                    </button>
                </div>
            </div>

            {error && <pre className="error-box">{error}</pre>}
            {testResult && <RouterTestResultCard state={testResult} onClose={() => setTestResult(null)} />}
            {pollNowResult && <RouterPollNowResultCard state={pollNowResult} onClose={() => setPollNowResult(null)} />}
            {loading && <div className="loading">Загрузка...</div>}

            <div className="routers-table-wrapper">
                <table className="routers-table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Название</th>
                            <th>REST API</th>
                            <th>Включён</th>
                            <th>Poller</th>
                            <th>Sync</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sortedItems.map((item) => (
                            <RouterRow
                                key={item.router.id}
                                item={item}
                                onEdit={openEditForm}
                                onToggle={toggleRouter}
                                onTest={handleTestConnection}
                                testing={testingRouterId === item.router.id}
                                onPollNow={handlePollNow}
                                polling={pollingRouterId === item.router.id}
                            />
                        ))}

                        {sortedItems.length === 0 && !loading && (
                            <tr>
                                <td colSpan={7} className="routers-table__empty">
                                    MikroTik ещё не добавлены.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            {form && (
                <div className="routers-modal-backdrop" onMouseDown={closeForm}>
                    <div className="routers-modal" onMouseDown={(event) => event.stopPropagation()}>
                        <form onSubmit={(event) => void handleSubmit(event)}>
                            <div className="routers-modal__header">
                                <h3>{form.mode === "create" ? "Добавить MikroTik" : "Редактировать MikroTik"}</h3>
                                <button type="button" className="icon-button" onClick={closeForm}>
                                    x
                                </button>
                            </div>

                            <div className="routers-form-grid">
                                <label>
                                    <span>Название</span>
                                    <input
                                        value={form.name}
                                        onChange={(event) => updateFormString("name", event.target.value)}
                                        autoFocus
                                    />
                                </label>

                                <label>
                                    <span>Host</span>
                                    <input
                                        value={form.apiHost}
                                        onChange={(event) => updateFormString("apiHost", event.target.value)}
                                        placeholder="192.168.0.1"
                                    />
                                </label>

                                <label>
                                    <span>Порт REST</span>
                                    <input
                                        value={form.apiPort}
                                        onChange={(event) => updateFormString("apiPort", event.target.value)}
                                        inputMode="numeric"
                                    />
                                </label>

                                <label>
                                    <span>Логин</span>
                                    <input
                                        value={form.apiUsername}
                                        onChange={(event) => updateFormString("apiUsername", event.target.value)}
                                    />
                                </label>

                                <label>
                                    <span>{form.mode === "create" ? "Пароль" : "Новый пароль"}</span>
                                    <input
                                        value={form.apiPassword}
                                        onChange={(event) => updateFormString("apiPassword", event.target.value)}
                                        type="password"
                                        placeholder={form.mode === "edit" ? "Оставить пустым, чтобы не менять" : ""}
                                    />
                                </label>

                                <label>
                                    <span>Интервал опроса, сек.</span>
                                    <input
                                        value={form.pollIntervalSeconds}
                                        onChange={(event) => updateFormString("pollIntervalSeconds", event.target.value)}
                                        inputMode="numeric"
                                    />
                                </label>
                            </div>

                            <div className="routers-checkboxes">
                                <BooleanCheckbox
                                    label="HTTPS"
                                    checked={form.apiUseSsl}
                                    onChange={(value) => updateFormBoolean("apiUseSsl", value)}
                                />
                                <BooleanCheckbox
                                    label="MikroTik включён"
                                    checked={form.isEnabled}
                                    onChange={(value) => updateFormBoolean("isEnabled", value)}
                                />
                                <BooleanCheckbox
                                    label="Poller включён"
                                    checked={form.pollEnabled}
                                    onChange={(value) => updateFormBoolean("pollEnabled", value)}
                                />
                                <BooleanCheckbox
                                    label="Sync включён"
                                    checked={form.syncEnabled}
                                    onChange={(value) => updateFormBoolean("syncEnabled", value)}
                                />
                            </div>

                            <div className="routers-modal__footer">
                                <button type="button" className="secondary-button" onClick={closeForm} disabled={saving}>
                                    Отмена
                                </button>
                                <button type="submit" className="primary-button" disabled={saving}>
                                    {saving ? "Сохранение..." : "Сохранить"}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </section>
    );
}

type RouterRowProps = {
    item: AdminRouterStatusItem;
    onEdit: (router: AdminRouter) => void;
    onToggle: (router: AdminRouter, field: "is_enabled" | "poll_enabled" | "sync_enabled") => Promise<void>;
    onTest: (router: AdminRouter) => Promise<void>;
    testing: boolean;
    onPollNow: (router: AdminRouter) => Promise<void>;
    polling: boolean;
};

function RouterRow({ item, onEdit, onToggle, onTest, testing, onPollNow, polling }: RouterRowProps) {
    const router = item.router;
    const poller = findService(item.services, "mikrotik_poller");
    const sync = findService(item.services, "policy_sync");

    return (
        <tr>
            <td>{router.id}</td>
            <td>
                <div className="routers-table__name">{router.name}</div>
                <div className="routers-table__muted">user: {router.api_username}</div>
            </td>
            <td>
                <div>{router.api_use_ssl ? "https" : "http"}://{router.api_host}:{router.api_port}/rest</div>
                <div className="routers-table__muted">poll: {router.poll_interval_seconds} сек.</div>
            </td>
            <td>
                <ToggleButton
                    active={router.is_enabled}
                    labelOn="Включён"
                    labelOff="Отключён"
                    onClick={() => void onToggle(router, "is_enabled")}
                />
            </td>
            <td>
                <ServiceStatusBlock
                    title="Poller"
                    enabled={router.poll_enabled}
                    status={poller}
                    onToggle={() => void onToggle(router, "poll_enabled")}
                />
            </td>
            <td>
                <ServiceStatusBlock
                    title="Sync"
                    enabled={router.sync_enabled}
                    status={sync}
                    onToggle={() => void onToggle(router, "sync_enabled")}
                />
            </td>
            <td>
                <div className="routers-table__actions">
                    <button className="secondary-button" type="button" onClick={() => onEdit(router)}>
                        Редактировать
                    </button>
                    <button
                        className="secondary-button"
                        type="button"
                        disabled={testing}
                        onClick={() => void onTest(router)}
                    >
                        {testing ? "Проверка..." : "Проверить"}
                    </button>
                    <button
                        className="secondary-button"
                        type="button"
                        disabled={polling}
                        onClick={() => void onPollNow(router)}
                    >
                        {polling ? "Опрос..." : "Опросить"}
                    </button>
                </div>
            </td>
        </tr>
    );
}


type RouterTestResultCardProps = {
    state: RouterTestResultState;
    onClose: () => void;
};

function RouterTestResultCard({ state, onClose }: RouterTestResultCardProps) {
    const result = state.result;
    const identityName = getStringField(result.identity, "name");
    const boardName = getStringField(result.resource, "board-name");
    const version = getStringField(result.resource, "version");

    return (
        <div className={result.ok ? "router-test-result router-test-result--ok" : "router-test-result router-test-result--error"}>
            <div className="router-test-result__header">
                <div>
                    <strong>
                        {result.ok ? "Подключение успешно" : "Подключение не прошло"}
                    </strong>
                    <div className="router-test-result__muted">
                        {state.routerName} - {result.checked_url}
                    </div>
                </div>
                <button type="button" className="mini-button" onClick={onClose}>
                    Закрыть
                </button>
            </div>

            {result.ok ? (
                <div className="router-test-result__details">
                    <span>HTTP: {result.status_code ?? "-"}</span>
                    <span>identity: {identityName ?? "-"}</span>
                    <span>board: {boardName ?? "-"}</span>
                    <span>version: {version ?? "-"}</span>
                </div>
            ) : (
                <>
                    <div className="router-test-result__error-text">
                        {result.error ?? "Unknown connection error"}
                    </div>
                    {result.status_code !== null && (
                        <div className="router-test-result__muted">HTTP: {result.status_code}</div>
                    )}
                    {result.redirect_location && (
                        <div className="router-test-result__muted">redirect: {result.redirect_location}</div>
                    )}
                    {result.response_preview && (
                        <pre className="router-test-result__preview">{result.response_preview}</pre>
                    )}
                </>
            )}
        </div>
    );
}


type RouterPollNowResultCardProps = {
    state: RouterPollNowResultState;
    onClose: () => void;
};

function RouterPollNowResultCard({ state, onClose }: RouterPollNowResultCardProps) {
    const result = state.result;

    return (
        <div className={result.ok ? "router-test-result router-test-result--ok" : "router-test-result router-test-result--error"}>
            <div className="router-test-result__header">
                <div>
                    <strong>
                        {result.ok ? "Опрос выполнен" : "Опрос не выполнен"}
                    </strong>
                    <div className="router-test-result__muted">
                        {state.routerName} - router #{result.router_id}
                    </div>
                </div>
                <button type="button" className="mini-button" onClick={onClose}>
                    Закрыть
                </button>
            </div>

            {result.ok ? (
                <div className="router-test-result__details">
                    <span>leases: {result.leases_count ?? "-"}</span>
                    <span>snapshot: {result.snapshot_published === false ? "нет" : "да"}</span>
                    <span>duration: {result.duration_ms ?? "-"} ms</span>
                </div>
            ) : (
                <div className="router-test-result__error-text">
                    {result.error ?? "Unknown poll error"}
                </div>
            )}
        </div>
    );
}

type ServiceStatusBlockProps = {
    title: string;
    enabled: boolean;
    status: AdminRouterServiceStatus | null;
    onToggle: () => void;
};

function ServiceStatusBlock({ title, enabled, status, onToggle }: ServiceStatusBlockProps) {
    return (
        <div className="service-status-block">
            <div className="service-status-block__top">
                <span className={`router-status-pill router-status-pill--${status?.status ?? "unknown"}`}>
                    {status?.status ?? "unknown"}
                </span>
                <button type="button" className="mini-button" onClick={onToggle}>
                    {enabled ? "Выключить" : "Включить"}
                </button>
            </div>
            <div className="routers-table__muted">{title}</div>
            <div className="routers-table__muted">heartbeat: {formatDateTime(status?.heartbeat_at)}</div>
            <div className="routers-table__muted">success: {formatDateTime(status?.last_success_at)}</div>
            {status?.consecutive_failures ? (
                <div className="routers-table__warning">ошибок подряд: {status.consecutive_failures}</div>
            ) : null}
            {status?.last_error ? <div className="routers-table__error">{status.last_error}</div> : null}
        </div>
    );
}

type ToggleButtonProps = {
    active: boolean;
    labelOn: string;
    labelOff: string;
    onClick: () => void;
};

function ToggleButton({ active, labelOn, labelOff, onClick }: ToggleButtonProps) {
    return (
        <button
            type="button"
            className={active ? "toggle-button toggle-button--active" : "toggle-button"}
            onClick={onClick}
        >
            {active ? labelOn : labelOff}
        </button>
    );
}

type BooleanCheckboxProps = {
    label: string;
    checked: boolean;
    onChange: (checked: boolean) => void;
};

function BooleanCheckbox({ label, checked, onChange }: BooleanCheckboxProps) {
    function handleChange(event: ChangeEvent<HTMLInputElement>) {
        onChange(event.target.checked);
    }

    return (
        <label className="routers-checkbox">
            <input type="checkbox" checked={checked} onChange={handleChange} />
            <span>{label}</span>
        </label>
    );
}

function findService(
    services: AdminRouterServiceStatus[],
    serviceName: string,
): AdminRouterServiceStatus | null {
    return services.find((service) => service.service_name === serviceName) ?? null;
}

function parseRequiredText(value: string, fieldName: string): string {
    const text = value.trim();

    if (text === "") {
        throw new Error(`${fieldName}: обязательное поле`);
    }

    return text;
}

function parseInteger(value: string, fieldName: string, min: number, max: number): number {
    const text = value.trim();
    const parsed = Number.parseInt(text, 10);

    if (!Number.isInteger(parsed) || parsed.toString() !== text) {
        throw new Error(`${fieldName}: нужно целое число`);
    }

    if (parsed < min || parsed > max) {
        throw new Error(`${fieldName}: допустимый диапазон ${min}-${max}`);
    }

    return parsed;
}

function formatDateTime(value: string | null | undefined): string {
    if (!value) {
        return "-";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return date.toLocaleString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    });
}

function getStringField(value: Record<string, unknown> | null, fieldName: string): string | null {
    const fieldValue = value?.[fieldName];
    return typeof fieldValue === "string" && fieldValue.trim() !== "" ? fieldValue : null;
}
