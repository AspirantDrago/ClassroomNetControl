import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
    allowDeviceWan,
    blockDeviceWan,
    type Classroom,
    type ClassroomDashboard,
    type DynamicDevice,
    getClassroomDashboard,
    getClassrooms,
    pinObservedDevice,
} from "./api";
import "./App.css";
import { ClassroomTabs } from "./components/ClassroomTabs/ClassroomTabs";
import { DeviceGrid } from "./components/DeviceGrid/DeviceGrid";
import { DynamicDevicesTable } from "./components/DynamicDevicesTable/DynamicDevicesTable";
import {
    PinObservedDeviceModal,
    type PinObservedFormState,
} from "./components/PinObservedDeviceModal/PinObservedDeviceModal";
import { Topbar } from "./components/Topbar/Topbar";
import {
    buildDeviceGrid,
    emptyStringToNull,
    parseOptionalPositiveInteger,
} from "./utils/devices";

export function App() {
    const [classrooms, setClassrooms] = useState<Classroom[]>([]);
    const [selectedClassroomId, setSelectedClassroomId] = useState<number | null>(null);
    const [dashboard, setDashboard] = useState<ClassroomDashboard | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busyDeviceId, setBusyDeviceId] = useState<number | null>(null);
    const [pinForm, setPinForm] = useState<PinObservedFormState | null>(null);
    const [busyPinMac, setBusyPinMac] = useState<string | null>(null);

    async function loadClassrooms() {
        const data = await getClassrooms();

        setClassrooms(data);

        if (selectedClassroomId === null && data.length > 0) {
            setSelectedClassroomId(data[0].id);
        }
    }

    async function loadDashboard(classroomId: number) {
        const data = await getClassroomDashboard(classroomId);
        setDashboard(data);
    }

    async function reload() {
        if (selectedClassroomId === null) {
            return;
        }

        setError(null);

        try {
            await loadDashboard(selectedClassroomId);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        }
    }

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setLoading(true);
        setError(null);

        loadClassrooms()
            .catch((err) => {
                setError(err instanceof Error ? err.message : "Unknown error");
            })
            .finally(() => {
                setLoading(false);
            });
    }, []);

    useEffect(() => {
        if (selectedClassroomId === null) {
            return;
        }

        // eslint-disable-next-line react-hooks/set-state-in-effect
        setLoading(true);
        setError(null);

        loadDashboard(selectedClassroomId)
            .catch((err) => {
                setError(err instanceof Error ? err.message : "Unknown error");
            })
            .finally(() => {
                setLoading(false);
            });

        const timerId = window.setInterval(() => {
            loadDashboard(selectedClassroomId).catch(() => {
                // Ошибку polling не показываем поверх экрана.
            });
        }, 5000);

        return () => window.clearInterval(timerId);
    }, [selectedClassroomId]);

    async function handleBlock(deviceId: number) {
        setBusyDeviceId(deviceId);
        setError(null);

        try {
            await blockDeviceWan(deviceId);
            await reload();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        } finally {
            setBusyDeviceId(null);
        }
    }

    async function handleAllow(deviceId: number) {
        setBusyDeviceId(deviceId);
        setError(null);

        try {
            await allowDeviceWan(deviceId);
            await reload();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        } finally {
            setBusyDeviceId(null);
        }
    }

    function openPinObservedForm(device: DynamicDevice) {
        setError(null);

        setPinForm({
            device,
            inventoryName: device.hostname ?? "",
            rowIndex: "",
            columnIndex: "",
        });
    }

    function closePinObservedForm() {
        setPinForm(null);
    }

    async function handlePinObservedSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (selectedClassroomId === null || pinForm === null) {
            return;
        }

        setError(null);
        setBusyPinMac(pinForm.device.mac_address);

        try {
            const rowIndex = parseOptionalPositiveInteger(pinForm.rowIndex, "row_index");
            const columnIndex = parseOptionalPositiveInteger(pinForm.columnIndex, "column_index");

            await pinObservedDevice(selectedClassroomId, {
                mac_address: pinForm.device.mac_address,
                inventory_name: emptyStringToNull(pinForm.inventoryName),
                row_index: rowIndex,
                column_index: columnIndex,
            });

            setPinForm(null);
            await reload();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        } finally {
            setBusyPinMac(null);
        }
    }

    const deviceGrid = useMemo(() => {
        return buildDeviceGrid(dashboard?.devices ?? []);
    }, [dashboard]);

    return (
        <div className="page">
            <Topbar
                onReload={reload}
                reloadDisabled={selectedClassroomId === null}
            />

            <main className="content">
                <ClassroomTabs
                    classrooms={classrooms}
                    selectedClassroomId={selectedClassroomId}
                    onSelect={setSelectedClassroomId}
                />

                {error && <pre className="error-box">{error}</pre>}

                {loading && <div className="loading">Загрузка...</div>}

                {dashboard && (
                    <>
                        <section className="classroom-header">
                            <div>
                                <h2>{dashboard.classroom.name}</h2>
                                <div className="muted">
                                    subnet: {dashboard.classroom.subnet_cidr}, VLAN:{" "}
                                    {dashboard.classroom.vlan_id ?? "-"}
                                </div>
                            </div>
                        </section>

                        <DeviceGrid
                            deviceGrid={deviceGrid}
                            busyDeviceId={busyDeviceId}
                            onBlock={handleBlock}
                            onAllow={handleAllow}
                        />

                        <DynamicDevicesTable
                            devices={dashboard.dynamic_devices}
                            busyPinMac={busyPinMac}
                            onOpenPinForm={openPinObservedForm}
                        />
                    </>
                )}
            </main>

            {pinForm && (
                <PinObservedDeviceModal
                    form={pinForm}
                    busyPinMac={busyPinMac}
                    onChange={setPinForm}
                    onClose={closePinObservedForm}
                    onSubmit={handlePinObservedSubmit}
                />
            )}
        </div>
    );
}
