import { useEffect, useRef, useState } from "react";
import type { BuildInfo } from "../../api";
import "./Topbar.css";

type AppPage = "dashboard" | "account" | "access" | "maintenance";

type TopbarProps = {
    currentPage: AppPage;
    buildInfo: BuildInfo | null;
    onReload: () => void;
    reloadDisabled: boolean;
    onCreateClassroom: () => void;
    canCreateClassroom: boolean;
    canOpenAccessAdmin: boolean;
    canOpenMaintenance: boolean;
    onOpenDashboard: () => void;
    onOpenAccount: () => void;
    onOpenAccessAdmin: () => void;
    onOpenMaintenance: () => void;
    principalName: string;
    onLogout: () => void;
};

export function Topbar(props: TopbarProps) {
    const {
        currentPage,
        buildInfo,
        onReload,
        reloadDisabled,
        onCreateClassroom,
        canCreateClassroom,
        canOpenAccessAdmin,
        canOpenMaintenance,
        onOpenDashboard,
        onOpenAccount,
        onOpenAccessAdmin,
        onOpenMaintenance,
        principalName,
        onLogout,
    } = props;

    const [menuOpen, setMenuOpen] = useState(false);
    const menuRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        if (!menuOpen) {
            return;
        }

        function handlePointerDown(event: PointerEvent) {
            if (
                menuRef.current !== null &&
                !menuRef.current.contains(event.target as Node)
            ) {
                setMenuOpen(false);
            }
        }

        function handleKeyDown(event: KeyboardEvent) {
            if (event.key === "Escape") {
                setMenuOpen(false);
            }
        }

        document.addEventListener("pointerdown", handlePointerDown);
        document.addEventListener("keydown", handleKeyDown);

        return () => {
            document.removeEventListener("pointerdown", handlePointerDown);
            document.removeEventListener("keydown", handleKeyDown);
        };
    }, [menuOpen]);

    function runMenuAction(action: () => void) {
        setMenuOpen(false);
        action();
    }

    return (
        <header className="topbar">
            <div className="topbar__main" onClick={() => runMenuAction(onOpenDashboard)}>
                <div className="topbar__logo">
                    <img src="/favicon.svg" alt="CMNC" />
                </div>
                <div>
                    <h1>Classroom MikroTik Net Control</h1>
                    <p>Управление доступом ученических ПК в WAN</p>
                    {buildInfo && (
                        <div
                            className="topbar__build-info"
                            title={formatBuildInfoTitle(buildInfo)}
                        >
                            <span>{formatBuildVersion(buildInfo)}</span>
                            {buildInfo.built_at && (
                                <span>{formatBuildDate(buildInfo.built_at)}</span>
                            )}
                        </div>
                    )}
                </div>
            </div>

            <div className="topbar-menu" ref={menuRef}>
                <button
                    className="topbar-burger"
                    type="button"
                    aria-label="Открыть меню"
                    aria-expanded={menuOpen}
                    onClick={() => setMenuOpen((opened) => !opened)}
                >
                    <span />
                    <span />
                    <span />
                </button>

                {menuOpen && (
                    <div className="topbar-dropdown">
                        <div className="topbar-dropdown__user">
                            {principalName}
                        </div>

                        <button
                            className={
                                currentPage === "account"
                                    ? "topbar-menu-item topbar-menu-item--active"
                                    : "topbar-menu-item"
                            }
                            type="button"
                            onClick={() => runMenuAction(onOpenAccount)}
                        >
                            Учётная запись
                        </button>

                        {canOpenAccessAdmin && (
                            <button
                                className={
                                    currentPage === "access"
                                        ? "topbar-menu-item topbar-menu-item--active"
                                        : "topbar-menu-item"
                                }
                                type="button"
                                onClick={() => runMenuAction(onOpenAccessAdmin)}
                            >
                                Пользователи
                            </button>
                        )}

                        {canOpenMaintenance && (
                            <button
                                className={
                                    currentPage === "maintenance"
                                        ? "topbar-menu-item topbar-menu-item--active"
                                        : "topbar-menu-item"
                                }
                                type="button"
                                onClick={() => runMenuAction(onOpenMaintenance)}
                            >
                                Обслуживание
                            </button>
                        )}

                        <div className="topbar-dropdown__separator" />

                        <button
                            className={
                                currentPage === "dashboard"
                                    ? "topbar-menu-item topbar-menu-item--active"
                                    : "topbar-menu-item"
                            }
                            type="button"
                            onClick={() => runMenuAction(onOpenDashboard)}
                        >
                            Аудитории
                        </button>

                        {currentPage === "dashboard" && canCreateClassroom && (
                            <button
                                className="topbar-menu-item"
                                type="button"
                                onClick={() => runMenuAction(onCreateClassroom)}
                            >
                                Новая аудитория
                            </button>
                        )}

                        <div className="topbar-dropdown__separator" />

                        {currentPage === "dashboard" && (
                            <button
                                className="topbar-menu-item"
                                type="button"
                                onClick={() => runMenuAction(onReload)}
                                disabled={reloadDisabled}
                            >
                                Обновить
                            </button>
                        )}

                        <div className="topbar-dropdown__separator" />

                        <button
                            className="topbar-menu-item topbar-menu-item--danger"
                            type="button"
                            onClick={() => runMenuAction(onLogout)}
                        >
                            Выйти
                        </button>
                    </div>
                )}
            </div>
        </header>
    );
}


function formatBuildVersion(buildInfo: BuildInfo): string {
    if (buildInfo.version.trim() !== "") {
        return buildInfo.version;
    }

    return `v ${buildInfo.git_commit_count}.${buildInfo.compose_build_number}`;
}

function formatBuildDate(value: string): string {
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
    });
}

function formatBuildInfoTitle(buildInfo: BuildInfo): string {
    const parts = [
        `Версия: ${formatBuildVersion(buildInfo)}`,
        `Коммитов: ${buildInfo.git_commit_count}`,
        `Сборка compose: ${buildInfo.compose_build_number}`,
    ];

    if (buildInfo.built_at) {
        parts.push(`Дата сборки: ${formatBuildDate(buildInfo.built_at)}`);
    }

    return parts.join("\n");
}
