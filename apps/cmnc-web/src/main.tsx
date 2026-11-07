import React from "react";
import ReactDOM from "react-dom/client";
import "./styles/global.css";
import { App } from "./App";
import { DeviceScreen } from "./components/Veyon/DeviceScreen";

const screenParameter = new URLSearchParams(window.location.search).get("veyon_device");
const screenDeviceId = screenParameter && /^\d+$/.test(screenParameter) ? Number(screenParameter) : 0;
const standaloneScreen = Number.isSafeInteger(screenDeviceId) && screenDeviceId > 0;
if (standaloneScreen) document.title = "Экран устройства";

ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
        {standaloneScreen ? <main className="veyon-screen-window"><DeviceScreen deviceId={screenDeviceId} standalone /></main> : <App />}
    </React.StrictMode>,
);