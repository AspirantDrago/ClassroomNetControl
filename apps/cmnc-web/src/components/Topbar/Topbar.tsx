import "./Topbar.css";

type TopbarProps = {
    onReload: () => void;
    reloadDisabled: boolean;
};

export function Topbar(props: TopbarProps) {
    const { onReload, reloadDisabled } = props;

    return (
        <header className="topbar">
            <div>
                <h1>Classroom MikroTik Net Control</h1>
                <p>Управление доступом ученических ПК в WAN</p>
            </div>

            <button
                className="secondary-button"
                onClick={onReload}
                disabled={reloadDisabled}
            >
                Обновить
            </button>
        </header>
    );
}
