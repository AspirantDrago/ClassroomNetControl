import "./Topbar.css";

type TopbarProps = {
    onReload: () => void;
    reloadDisabled: boolean;
    onCreateClassroom: () => void;
};

export function Topbar(props: TopbarProps) {
    const {onReload, reloadDisabled, onCreateClassroom} = props;

    return (
        <header className="topbar">
            <div className="topbar__main">
                <div className="topbar__logo">
                    <img src="/favicon.svg" alt="Описание картинки"/>
                </div>
                <div>
                    <h1>Classroom MikroTik Net Control</h1>
                    <p>Управление доступом ученических ПК в WAN</p>
                </div>
            </div>

            <div className="topbar-actions">
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
            </div>
        </header>
    );
}
