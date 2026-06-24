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

function getQualityLabel(quality: CameraQuality): string {
    if (quality === "main") {
        return "Основной поток";
    }

    return "Дополнительный поток";
}

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
    const [selectedQuality, setSelectedQuality] = useState<CameraQuality | null>(
        defaultQuality,
    );
    const [session, setSession] = useState<CameraSessionResponse | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        setSelectedQuality(defaultQuality);
    }, [defaultQuality]);

    useEffect(() => {
        let cancelled = false;
        let createdSessionId: string | null = null;

        async function openSession() {
            if (!isOpen || selectedQuality === null) {
                setSession(null);
                setBusy(false);
                return;
            }

            setBusy(true);
            setError(null);
            setSession(null);

            try {
                const createdSession = await createClassroomCameraSession(
                    classroomId,
                    selectedQuality,
                );

                createdSessionId = createdSession.session_id;

                if (cancelled) {
                    await deleteCameraSession(createdSession.session_id);
                    return;
                }

                setSession(createdSession);
            } catch (err) {
                if (!cancelled) {
                    setError(extractErrorDetail(err));
                }
            } finally {
                if (!cancelled) {
                    setBusy(false);
                }
            }
        }

        void openSession();

        return () => {
            cancelled = true;

            if (createdSessionId !== null) {
                void deleteCameraSession(createdSessionId);
            }
        };
    }, [classroomId, isOpen, selectedQuality]);

    if (!camera.enabled || selectedQuality === null) {
        return null;
    }

    const streamUrl = session ? getCameraStreamUrl(session.url) : null;
    const canSelectQuality = camera.qualities.length > 1 && !busy;

    function togglePanel() {
        setError(null);
        setIsOpen((value) => !value);
    }

    function handleQualityChange(value: string) {
        if (value !== "main" && value !== "sub") {
            return;
        }

        setError(null);
        setSelectedQuality(value);
    }

    return (
        <section className="classroom-camera-panel">
            <button
                type="button"
                className="classroom-camera-panel__summary"
                onClick={togglePanel}
            >
                <span>{isOpen ? "▼" : "▶"}</span>
                <span>Камера аудитории</span>
            </button>

            {isOpen && (
                <div className="classroom-camera-panel__body">
                    {camera.qualities.length > 1 && (
                        <label className="classroom-camera-panel__quality-select">
                            <span>Качество</span>
                            <select
                                value={selectedQuality}
                                disabled={!canSelectQuality}
                                onChange={(event) =>
                                    handleQualityChange(event.target.value)
                                }
                            >
                                {camera.qualities.includes("main") && (
                                    <option value="main">Основной поток</option>
                                )}

                                {camera.qualities.includes("sub") && (
                                    <option value="sub">Дополнительный поток</option>
                                )}
                            </select>
                        </label>
                    )}

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
                            {busy
                                ? `Подключение: ${getQualityLabel(selectedQuality)}...`
                                : "Видео недоступно."}
                        </div>
                    )}
                </div>
            )}
        </section>
    );
}
