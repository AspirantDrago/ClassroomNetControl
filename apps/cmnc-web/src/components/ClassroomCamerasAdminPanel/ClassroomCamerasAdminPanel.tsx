import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
    type AdminClassroomCamera,
    type AdminClassroomCameraCreateRequest,
    type CameraQuality,
    createAdminClassroomCamera,
    deleteAdminClassroomCamera,
    extractErrorDetail,
    getAdminClassroomCameras,
    updateAdminClassroomCamera,
} from "../../api";
import "./ClassroomCamerasAdminPanel.css";

type ClassroomCamerasAdminPanelProps = {
    classroomId: number;
    onChanged: () => void | Promise<void>;
};

type CameraFormState = {
    mode: "create" | "edit";
    camera: AdminClassroomCamera | null;
    name: string;
    sortOrder: string;
    isEnabled: boolean;
    rtspMainStream: string;
    rtspSubStream: string;
    defaultQuality: CameraQuality;
};

function emptyStringToNull(value: string): string | null {
    const normalized = value.trim();
    return normalized === "" ? null : normalized;
}

function parseSortOrder(value: string): number {
    const normalized = value.trim();

    if (normalized === "") {
        return 0;
    }

    const parsed = Number(normalized);

    if (!Number.isInteger(parsed) || parsed < 0) {
        throw new Error("Порядок должен быть целым числом от 0.");
    }

    return parsed;
}

function getQualityLabel(quality: CameraQuality): string {
    return quality === "main" ? "Высокое" : "Низкое";
}

function buildPayload(form: CameraFormState): AdminClassroomCameraCreateRequest {
    const name = form.name.trim();

    if (name === "") {
        throw new Error("Название камеры обязательно.");
    }

    const rtspMainStream = emptyStringToNull(form.rtspMainStream);
    const rtspSubStream = emptyStringToNull(form.rtspSubStream);

    if (form.isEnabled && rtspMainStream === null && rtspSubStream === null) {
        throw new Error("Для включённой камеры нужно указать хотя бы один RTSP-поток.");
    }

    return {
        name,
        sort_order: parseSortOrder(form.sortOrder),
        is_enabled: form.isEnabled,
        rtsp_main_stream: rtspMainStream,
        rtsp_sub_stream: rtspSubStream,
        default_quality: form.defaultQuality,
    };
}

function getStreamSummary(camera: AdminClassroomCamera): string {
    const streams: string[] = [];

    if (camera.rtsp_main_stream) {
        streams.push("main");
    }

    if (camera.rtsp_sub_stream) {
        streams.push("sub");
    }

    return streams.length > 0 ? streams.join(" + ") : "нет";
}

function getNextSortOrder(cameras: AdminClassroomCamera[]): string {
    if (cameras.length === 0) {
        return "0";
    }

    return String(Math.max(...cameras.map((camera) => camera.sort_order)) + 10);
}

export function ClassroomCamerasAdminPanel({
    classroomId,
    onChanged,
}: ClassroomCamerasAdminPanelProps) {
    const [cameras, setCameras] = useState<AdminClassroomCamera[]>([]);
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [form, setForm] = useState<CameraFormState | null>(null);

    const sortedCameras = useMemo(() => {
        return [...cameras].sort((left, right) => {
            if (left.sort_order !== right.sort_order) {
                return left.sort_order - right.sort_order;
            }

            return left.id - right.id;
        });
    }, [cameras]);

    useEffect(() => {
        let cancelled = false;

        async function loadCameras(): Promise<void> {
            setLoading(true);
            setError(null);

            try {
                const data = await getAdminClassroomCameras(classroomId);

                if (!cancelled) {
                    setCameras(data);
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

        setForm(null);
        void loadCameras();

        return () => {
            cancelled = true;
        };
    }, [classroomId]);

    async function reloadAfterChange(): Promise<void> {
        const data = await getAdminClassroomCameras(classroomId);
        setCameras(data);
        await onChanged();
    }

    function openCreateForm() {
        setError(null);
        setForm({
            mode: "create",
            camera: null,
            name: "",
            sortOrder: getNextSortOrder(cameras),
            isEnabled: true,
            rtspMainStream: "",
            rtspSubStream: "",
            defaultQuality: "sub",
        });
    }

    function openEditForm(camera: AdminClassroomCamera) {
        setError(null);
        setForm({
            mode: "edit",
            camera,
            name: camera.name,
            sortOrder: String(camera.sort_order),
            isEnabled: camera.is_enabled,
            rtspMainStream: camera.rtsp_main_stream ?? "",
            rtspSubStream: camera.rtsp_sub_stream ?? "",
            defaultQuality: camera.default_quality,
        });
    }

    function closeForm() {
        if (!busy) {
            setForm(null);
        }
    }

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (form === null) {
            return;
        }

        setBusy(true);
        setError(null);

        try {
            const payload = buildPayload(form);

            if (form.mode === "create") {
                await createAdminClassroomCamera(classroomId, payload);
            } else if (form.camera !== null) {
                await updateAdminClassroomCamera(classroomId, form.camera.id, payload);
            }

            setForm(null);
            await reloadAfterChange();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusy(false);
        }
    }

    async function handleDelete(camera: AdminClassroomCamera) {
        const confirmed = window.confirm(`Удалить камеру "${camera.name}"?`);

        if (!confirmed) {
            return;
        }

        setBusy(true);
        setError(null);

        try {
            await deleteAdminClassroomCamera(classroomId, camera.id);

            if (form?.camera?.id === camera.id) {
                setForm(null);
            }

            await reloadAfterChange();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusy(false);
        }
    }

    return (
        <section className="classroom-cameras-admin-panel">
            <div className="classroom-cameras-admin-panel__header">
                <div>
                    <h3>Камеры</h3>
                    <div className="muted">Управление RTSP-потоками этой аудитории.</div>
                </div>

                <button
                    type="button"
                    className="secondary-button"
                    disabled={busy}
                    onClick={openCreateForm}
                >
                    Добавить камеру
                </button>
            </div>

            {error && <pre className="classroom-cameras-admin-panel__error">{error}</pre>}

            {loading ? (
                <div className="classroom-cameras-admin-panel__empty">Загрузка камер...</div>
            ) : sortedCameras.length === 0 ? (
                <div className="classroom-cameras-admin-panel__empty">
                    Для этой аудитории камеры не настроены.
                </div>
            ) : (
                <div className="classroom-cameras-admin-panel__table-wrap">
                    <table className="classroom-cameras-admin-panel__table">
                        <thead>
                            <tr>
                                <th>Название</th>
                                <th>Порядок</th>
                                <th>Статус</th>
                                <th>Потоки</th>
                                <th>По умолчанию</th>
                                <th />
                            </tr>
                        </thead>
                        <tbody>
                            {sortedCameras.map((camera) => (
                                <tr key={camera.id}>
                                    <td>{camera.name}</td>
                                    <td>{camera.sort_order}</td>
                                    <td>{camera.is_enabled ? "Включена" : "Выключена"}</td>
                                    <td>{getStreamSummary(camera)}</td>
                                    <td>{getQualityLabel(camera.default_quality)}</td>
                                    <td>
                                        <div className="classroom-cameras-admin-panel__row-actions">
                                            <button
                                                type="button"
                                                className="secondary-button"
                                                disabled={busy}
                                                onClick={() => openEditForm(camera)}
                                            >
                                                Изменить
                                            </button>
                                            <button
                                                type="button"
                                                className="danger-button"
                                                disabled={busy}
                                                onClick={() => void handleDelete(camera)}
                                            >
                                                Удалить
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {form && (
                <form
                    className="classroom-camera-form"
                    onSubmit={handleSubmit}
                >
                    <div className="classroom-camera-form__header">
                        <h4>
                            {form.mode === "create"
                                ? "Новая камера"
                                : "Редактировать камеру"}
                        </h4>
                        <div className="muted">RTSP-ссылки видны только администраторам.</div>
                    </div>

                    <div className="classroom-camera-form-grid">
                        <label>
                            Название
                            <input
                                value={form.name}
                                onChange={(event) =>
                                    setForm({
                                        ...form,
                                        name: event.target.value,
                                    })
                                }
                                placeholder="Камера у доски"
                            />
                        </label>

                        <label>
                            Порядок
                            <input
                                type="number"
                                min="0"
                                value={form.sortOrder}
                                onChange={(event) =>
                                    setForm({
                                        ...form,
                                        sortOrder: event.target.value,
                                    })
                                }
                                placeholder="10"
                            />
                        </label>

                        <label>
                            Качество по умолчанию
                            <select
                                value={form.defaultQuality}
                                onChange={(event) =>
                                    setForm({
                                        ...form,
                                        defaultQuality: event.target.value as CameraQuality,
                                    })
                                }
                            >
                                <option value="sub">Низкое</option>
                                <option value="main">Высокое</option>
                            </select>
                        </label>
                    </div>

                    <div className="classroom-camera-rtsp-grid">
                        <label>
                            RTSP основной поток
                            <input
                                value={form.rtspMainStream}
                                onChange={(event) =>
                                    setForm({
                                        ...form,
                                        rtspMainStream: event.target.value,
                                    })
                                }
                                placeholder="rtsp://user:password@camera/stream1"
                            />
                        </label>

                        <label>
                            RTSP дополнительный поток
                            <input
                                value={form.rtspSubStream}
                                onChange={(event) =>
                                    setForm({
                                        ...form,
                                        rtspSubStream: event.target.value,
                                    })
                                }
                                placeholder="rtsp://user:password@camera/stream2"
                            />
                        </label>
                    </div>

                    <label className="classroom-camera-enabled-checkbox">
                        <input
                            type="checkbox"
                            checked={form.isEnabled}
                            onChange={(event) =>
                                setForm({
                                    ...form,
                                    isEnabled: event.target.checked,
                                })
                            }
                        />
                        <span>Камера включена</span>
                    </label>

                    <div className="modal-actions classroom-camera-form-actions">
                        <button
                            type="button"
                            className="secondary-button"
                            disabled={busy}
                            onClick={closeForm}
                        >
                            Отмена
                        </button>

                        <button type="submit" className="primary-button" disabled={busy}>
                            {form.mode === "create" ? "Создать" : "Сохранить"}
                        </button>
                    </div>
                </form>
            )}
        </section>
    );
}
