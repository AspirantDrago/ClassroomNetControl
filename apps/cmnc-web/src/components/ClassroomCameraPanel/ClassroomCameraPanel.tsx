import { useEffect, useMemo, useState } from "react";

import {
    type CameraQuality,
    type CameraSessionResponse,
    type ClassroomCamera,
    createClassroomCameraSession,
    deleteCameraSession,
    extractErrorDetail,
    getCameraStreamUrl,
} from "../../api";
import "./ClassroomCameraPanel.css";

type ClassroomCameraPanelProps = {
    classroomId: number;
    camera: ClassroomCamera;
};

export function ClassroomCameraPanel({
    classroomId,
    camera,
}: ClassroomCameraPanelProps) {
    const defaultQuality = useMemo<CameraQuality | null>(() => {
        if (camera.qualities.includes("sub")) {
            return "sub";
        }

        if (camera.qualities.includes("main")) {
            return "main";
        }

        return null;
    }, [camera.qualities]);

    const [isOpen, setIsOpen] = useState(false);
    const [selectedQuality, setSelectedQuality] = useState<CameraQuality | null>(defaultQuality);
    const [session, setSession] = useState<CameraSessionResponse | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        setSelectedQuality(defaultQuality);
    }, [defaultQuality]);

    useEffect(() => {
        return () => {
            if (session !== null) {
                void deleteCameraSession(session.session_id);
            }
        };
    }, [session]);

    if (!camera.enabled || selectedQuality === null) {
        return null;
    }

    const streamUrl = session ? getCameraStreamUrl(session.url) : null;
    const canSelectQuality = camera.qualities.length > 1 && session === null && !busy;

    async function stopCurrentSession() {
        if (session === null) {
            return;
        }

        const sessionId = session.session_id;
        setSession(null);

        try {
            await deleteCameraSession(sessionId);
        } catch {
            // Сессию могли уже закрыть по TTL или из-за перезапуска сервиса.
        }
    }

    async function togglePanel() {
        setError(null);

        if (isOpen) {
            setIsOpen(false);
            await stopCurrentSession();
            return;
        }

        setIsOpen(true);
    }

    async function startStream() {
        if (selectedQuality === null) {
            return;
        }

        setBusy(true);
        setError(null);

        try {
            const createdSession = await createClassroomCameraSession(
                classroomId,
                selectedQuality,
            );
            setSession(createdSession);
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusy(false);
        }
    }

    async function stopStream() {
        setBusy(true);
        setError(null);

        try {
            await stopCurrentSession();
        } finally {
            setBusy(false);
        }
    }

    async function selectQuality(quality: CameraQuality) {
        if (quality === selectedQuality) {
            return;
        }

        setError(null);
        await stopCurrentSession();
        setSelectedQuality(quality);
    }

    return (
        <section className="classroom-camera-panel">
            <button
                type="button"
                className="classroom-camera-panel__summary"
                onClick={() => void togglePanel()}
            >
                <span>{isOpen ? "▼" : "▶"}</span>
                <span>Камера аудитории</span>
            </button>

            {isOpen && (
                <div className="classroom-camera-panel__body">
                    {camera.qualities.length > 1 && (
                        <div className="classroom-camera-panel__qualities">
                            {camera.qualities.includes("main") && (
                                <button
                                    type="button"
                                    className={
                                        selectedQuality === "main"
                                            ? "secondary-button classroom-camera-panel__quality classroom-camera-panel__quality--active"
                                            : "secondary-button classroom-camera-panel__quality"
                                    }
                                    disabled={!canSelectQuality}
                                    onClick={() => void selectQuality("main")}
                                >
                                    Основной поток
                                </button>
                            )}

                            {camera.qualities.includes("sub") && (
                                <button
                                    type="button"
                                    className={
                                        selectedQuality === "sub"
                                            ? "secondary-button classroom-camera-panel__quality classroom-camera-panel__quality--active"
                                            : "secondary-button classroom-camera-panel__quality"
                                    }
                                    disabled={!canSelectQuality}
                                    onClick={() => void selectQuality("sub")}
                                >
                                    Дополнительный поток
                                </button>
                            )}
                        </div>
                    )}

                    <div className="classroom-camera-panel__controls">
                        {session === null ? (
                            <button
                                type="button"
                                className="secondary-button"
                                disabled={busy}
                                onClick={() => void startStream()}
                            >
                                {busy ? "Открытие камеры..." : "Открыть камеру"}
                            </button>
                        ) : (
                            <button
                                type="button"
                                className="secondary-button"
                                disabled={busy}
                                onClick={() => void stopStream()}
                            >
                                {busy ? "Закрытие камеры..." : "Закрыть камеру"}
                            </button>
                        )}

                        <span className="classroom-camera-panel__hint">
                            Видео запускается только после открытия камеры.
                        </span>
                    </div>

                    {error && <pre className="classroom-camera-panel__error">{error}</pre>}

                    {streamUrl ? (
                        <video
                            className="classroom-camera-panel__video"
                            src={streamUrl}
                            controls
                            autoPlay
                            muted
                            playsInline
                        />
                    ) : (
                        <div className="classroom-camera-panel__placeholder">
                            Выберите качество и нажмите “Открыть камеру”. RTSP-ссылка остаётся на backend.
                        </div>
                    )}
                </div>
            )}
        </section>
    );
}
