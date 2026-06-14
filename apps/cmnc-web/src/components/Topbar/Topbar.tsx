import "./Topbar.css";

type TopbarProps = {
    onReload: () => void;
    reloadDisabled: boolean;
    onCreateClassroom: () => void;
    principalName: string;
    onLogout: () => void;
};

export function Topbar(props: TopbarProps) {
    const {
        onReload,
        reloadDisabled,
        onCreateClassroom,
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
                    className="secondary-button"
                    onClick={onCreateClassroom}
                >
                    Новая аудитория
                </button>

                <button
                    className="secondary-button"
                    onClick={onReload}
                    disabled={reloadDisabled}
                >
                    Обновить
                </button>

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
