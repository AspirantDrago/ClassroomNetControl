import type { DisplaySettings } from "../../config/displaySettings";
import "./SettingsPage.css";

export function SettingsPage({settings, onChange}: {settings: DisplaySettings; onChange: (settings: DisplaySettings) => void}) {
    const options: [keyof DisplaySettings, string][] = [
        ["showInactiveClassrooms", "Показывать деактивированные аудитории"],
        ["showInactiveUsers", "Показывать деактивированных пользователей"],
        ["showInactiveWorkstations", "Показывать деактивированные рабочие станции"],
    ];
    return <section className="settings-page"><h2>Настройки</h2>
        <div className="settings-card">{options.map(([key, label]) => <label key={key} className="settings-option">
            <span>{label}</span>
            <input type="checkbox" role="switch" checked={settings[key]} onChange={event => onChange({...settings, [key]: event.target.checked})}/>
        </label>)}</div>
    </section>;
}
