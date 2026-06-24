import Hls from "hls.js";
import { useEffect, useMemo, useRef, useState } from "react";

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

const ACCESS_TOKEN_STORAGE_KEY = "cmnc_access_token";

function getQualityLabel(quality: CameraQuality): string {
    if (quality === "main") {
        return "Основной поток";
    }

    return "Дополнительный поток";
}

function isCameraQuality(value: string): value is CameraQuality {
    return value === "main" || value === "sub";
}

function getVideoErrorMessage(video: HTMLVideoElement): string {
    const mediaError = video.error;

    if (mediaError === null) {
        return "Ошибка воспроизведения видео.";
    }

    if (mediaError.code === MediaError.MEDIA_ERR_ABORTED) {
        return "Воспроизведение видео было прервано.";
    }

    if (mediaError.code === MediaError.MEDIA_ERR_NETWORK) {
        return "Сетевая ошибка при загрузке видео.";
    }

    if (mediaError.code === MediaError.MEDIA_ERR_DECODE) {
        return "Браузер не смог декодировать видеопоток. Проверьте, что backend отдаёт H.264/yuv420p и совместимый звук AAC или поток без звука.";
    }

    if (mediaError.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED) {
        return "Источник видео не поддерживается браузером. Проверьте HLS playlist/сегменты и codec string.";
    }

    return `Ошибка воспроизведения видео. Код: ${mediaError.code}.`;
}

function getAuthToken(): string | null {
    return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

export function ClassroomCameraPanel({
    classroomId,
    camera,
}: ClassroomCameraPanelProps) {
    const videoRef = useRef<HTMLVideoElement | null>(null);

    const defaultQuality = useMemo<CameraQuality | null>(() => {
        if (camera.qualities.includes(camera.default_quality)) {
            return camera.default_quality;
        }

        if (camera.qualities.includes("sub")) {
            return "sub";
        }

        if (camera.qualities.includes("main")) {
            return "main";
        }

        return null;
    }, [camera.default_quality, camera.qualities]);

    const [isOpen, setIsOpen] = useState(false);
    const [selectedQuality, setSelectedQuality] = useState<CameraQuality | null>(
        defaultQuality,
    );
    const [session, setSession] = useState<CameraSessionResponse | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [, setStatus] = useState<string | null>(null);

    useEffect(() => {
        setSelectedQuality(defaultQuality);
    }, [defaultQuality]);

    useEffect(() => {
        let cancelled = false;
        let createdSessionId: string | null = null;

        async function openSession() {
            if (!isOpen || selectedQuality === null || camera.id === null) {
                setSession(null);
                setBusy(false);
                setStatus(null);
                return;
            }

            setBusy(true);
            setError(null);
            setStatus("Создание HLS-сессии...");
            setSession(null);

            try {
                const createdSession = await createClassroomCameraSession(
                    classroomId,
                    camera.id,
                    selectedQuality,
                );

                createdSessionId = createdSession.session_id;

                if (cancelled) {
                    await deleteCameraSession(createdSession.session_id);
                    return;
                }

                setSession(createdSession);
                setStatus("HLS-сессия создана. Загрузка playlist...");
            } catch (err) {
                if (!cancelled) {
                    setError(extractErrorDetail(err));
                    setStatus(null);
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
    }, [camera.id, classroomId, isOpen, selectedQuality]);

    const streamUrl = session ? getCameraStreamUrl(session.url) : null;

    useEffect(() => {
        const video = videoRef.current;

        if (!video || !streamUrl) {
            return undefined;
        }

        setError(null);
        setStatus("Инициализация HLS-плеера...");

        video.muted = true;
        video.autoplay = true;
        video.playsInline = true;
        video.pause();
        video.removeAttribute("src");
        video.load();

        let hls: Hls | null = null;
        let stopped = false;
        let recoverMediaErrorCount = 0;

        const handleVideoError = () => {
            if (!stopped) {
                setError(getVideoErrorMessage(video));
            }
        };

        video.addEventListener("error", handleVideoError);

        const tryPlay = () => {
            if (stopped) {
                return;
            }

            const playPromise = video.play();

            if (playPromise !== undefined) {
                playPromise.catch((err: unknown) => {
                    if (!stopped) {
                        setError(
                            `Не удалось запустить видео в браузере: ${extractErrorDetail(err)}`,
                        );
                    }
                });
            }
        };

        // Chrome/Edge/Firefox должны идти через hls.js. Нативный HLS оставляем только
        // как fallback для Safari, где MediaSource/Hls может быть недоступен.
        if (Hls.isSupported()) {
            hls = new Hls({
                enableWorker: true,
                lowLatencyMode: false,
                liveSyncDurationCount: 3,
                liveMaxLatencyDurationCount: 8,
                manifestLoadingMaxRetry: 8,
                manifestLoadingRetryDelay: 1000,
                levelLoadingMaxRetry: 8,
                levelLoadingRetryDelay: 1000,
                fragLoadingMaxRetry: 8,
                fragLoadingRetryDelay: 1000,
                backBufferLength: 30,
                xhrSetup: (xhr) => {
                    const token = getAuthToken();

                    if (token) {
                        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
                    }
                },
            });

            hls.on(Hls.Events.MEDIA_ATTACHED, () => {
                if (stopped) {
                    return;
                }

                setStatus("MediaSource подключён. Загрузка playlist...");
                hls?.loadSource(streamUrl);
            });

            hls.on(Hls.Events.MANIFEST_PARSED, (_event, data) => {
                setStatus(`Playlist загружен. Уровней качества: ${data.levels.length}. Запуск видео...`);
                tryPlay();
            });

            hls.on(Hls.Events.LEVEL_LOADED, () => {
                setStatus("HLS playlist загружен. Ожидание сегментов...");
                tryPlay();
            });

            hls.on(Hls.Events.FRAG_LOADED, () => {
                setStatus("HLS-сегмент загружен. Запуск видео...");
                tryPlay();
            });

            hls.on(Hls.Events.FRAG_BUFFERED, () => {
                setStatus(null);
                tryPlay();
            });

            hls.on(Hls.Events.ERROR, (_event, data) => {
                const message = `HLS error: type=${data.type}; details=${data.details}; fatal=${String(data.fatal)}`;

                if (!data.fatal) {
                    setStatus(message);
                    return;
                }

                setError(message);

                if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
                    hls?.startLoad();
                    return;
                }

                if (data.type === Hls.ErrorTypes.MEDIA_ERROR && recoverMediaErrorCount < 3) {
                    recoverMediaErrorCount += 1;
                    hls?.recoverMediaError();
                    return;
                }

                hls?.destroy();
                hls = null;
            });

            hls.attachMedia(video);

            return () => {
                stopped = true;
                video.removeEventListener("error", handleVideoError);
                hls?.destroy();
                video.pause();
                video.removeAttribute("src");
                video.load();
            };
        }

        if (video.canPlayType("application/vnd.apple.mpegurl")) {
            setStatus("Используется нативный HLS-плеер браузера...");
            video.src = streamUrl;
            video.addEventListener("loadedmetadata", tryPlay);
            video.addEventListener("canplay", tryPlay);
            video.load();
            tryPlay();

            return () => {
                stopped = true;
                video.removeEventListener("error", handleVideoError);
                video.removeEventListener("loadedmetadata", tryPlay);
                video.removeEventListener("canplay", tryPlay);
                video.pause();
                video.removeAttribute("src");
                video.load();
            };
        }

        setError("HLS не поддерживается этим браузером.");

        return () => {
            stopped = true;
            video.removeEventListener("error", handleVideoError);
        };
    }, [streamUrl]);

    if (!camera.enabled || camera.id === null || selectedQuality === null) {
        return null;
    }

    const canSelectQuality = camera.qualities.length > 1 && !busy;

    function togglePanel() {
        setError(null);
        setStatus(null);
        setIsOpen((value) => !value);
    }

    function handleQualityChange(value: string) {
        if (!isCameraQuality(value)) {
            return;
        }

        setError(null);
        setStatus(null);
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
                <span>Камера: {camera.name}</span>
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
                            ref={videoRef}
                            className="classroom-camera-panel__video"
                            controls
                            muted
                            autoPlay
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
