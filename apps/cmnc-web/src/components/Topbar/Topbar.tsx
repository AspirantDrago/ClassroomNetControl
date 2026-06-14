import "./Topbar.css";

type AppPage = "dashboard" | "access";

type TopbarProps = {
    currentPage: AppPage;
    onReload: () => void;
    reloadDisabled: boolean;
    onCreateClassroom: () => void;
    canCreateClassroom: boolean;
    canOpenAccessAdmin: boolean;
    onOpenDashboard: () => void;
    onOpenAccessAdmin: () => void;
    principalName: string;
    onLogout: () => void;
};

export function Topbar(props: TopbarProps) {
    const {
        currentPage,
        onReload,
        reloadDisabled,
        onCreateClassroom,
        canCreateClassroom,
        canOpenAccessAdmin,
        onOpenDashboard,
        onOpenAccessAdmin,
        principalName,
        onLogout,
    } = props;

    return (
        <header className="topbar">
            <div className="topbar__main">
                <div className="topbar__logo">
                    <img src="/favicon.svg" alt="CMNC" />
                </div>
                <div>
                    <h1>Classroom MikroTik Net Control</h1>
                    <p>Управление доступом ученических ПК в WAN</p>
                </div>
            </div>

            <div className="topbar-actions">
                <span className="topbar-user">{principalName}</span>

                <button
                    className={
                        currentPage === "dashboard"
                            ? "secondary-button topbar-active-button"
                            : "secondary-button"
                    }
                    onClick={onOpenDashboard}
                >
                    Аудитории
                </button>

                {canOpenAccessAdmin && (
                    <button
                        className={
                            currentPage === "access"
                                ? "secondary-button topbar-active-button"
                                : "secondary-button"
                        }
                        onClick={onOpenAccessAdmin}
                    >
                        Пользователи
                    </button>
                )}

                {currentPage === "dashboard" && canCreateClassroom && (
                    <button
                        className="secondary-button"
                        onClick={onCreateClassroom}
                    >
                        Новая аудитория
                    </button>
                )}

                {currentPage === "dashboard" && (
                    <button
                        className="secondary-button"
                        onClick={onReload}
                        disabled={reloadDisabled}
                    >
                        Обновить
                    </button>
                )}

                <button
                    className="secondary-button"
                    onClick={onLogout}
                >
                    Выйти
                </button>
            </div>
        </header>
    );
}
