import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
    allowDeviceWan,
    blockDeviceWan,
    type Classroom,
    type ClassroomDashboard,
    type DashboardDevice,
    type DynamicDevice,
    createClassroom,
    getClassroomDashboard,
    getClassrooms,
    pinObservedDevice,
    unpinDevice,
    updateClassroom,
    updateDevice,
} from "./api";
import "./App.css";
import { ClassroomTabs } from "./components/ClassroomTabs/ClassroomTabs";
import {
    ClassroomFormModal,
    type ClassroomFormState,
} from "./components/ClassroomFormModal/ClassroomFormModal";
import {
    DeviceFormModal,
    type DeviceFormState,
} from "./components/DeviceFormModal/DeviceFormModal";
import { DeviceGrid } from "./components/DeviceGrid/DeviceGrid";
import { DynamicDevicesTable } from "./components/DynamicDevicesTable/DynamicDevicesTable";
import { Topbar } from "./components/Topbar/Topbar";
import {
    buildDeviceGrid,
    emptyStringToNull,
    parseOptionalPositiveInteger,
} from "./utils/devices";
import { parseOptionalInteger, parseRequiredString } from "./utils/forms";

export function App() {
    const [classrooms, setClassrooms] = useState<Classroom[]>([]);
    const [selectedClassroomId, setSelectedClassroomId] = useState<number | null>(
        null,
    );
    const [dashboard, setDashboard] = useState<ClassroomDashboard | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busyDeviceId, setBusyDeviceId] = useState<number | null>(null);
    const [deviceForm, setDeviceForm] = useState<DeviceFormState | null>(null);
    const [busyForm, setBusyForm] = useState(false);
    const [classroomForm, setClassroomForm] = useState<ClassroomFormState | null>(
        null,
    );
    const [busyClassroomForm, setBusyClassroomForm] = useState(false);

    async function reload() {
        if (selectedClassroomId === null) {
            return;
        }

        setError(null);

        try {
            const data = await getClassroomDashboard(selectedClassroomId);
            setDashboard(data);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        }
    }

    async function reloadClassrooms(preferredClassroomId?: number | null) {
        const data = await getClassrooms();
        setClassrooms(data);

        if (data.length === 0) {
            setSelectedClassroomId(null);
            setDashboard(null);
            return;
        }

        if (
            preferredClassroomId !== undefined &&
            preferredClassroomId !== null &&
            data.some((classroom) => classroom.id === preferredClassroomId)
        ) {
            setSelectedClassroomId(preferredClassroomId);
            return;
        }

        if (
            selectedClassroomId !== null &&
            data.some((classroom) => classroom.id === selectedClassroomId)
        ) {
            return;
        }

        setSelectedClassroomId(data[0].id);
    }

    function openCreateClassroomForm() {
        setError(null);

        setClassroomForm({
            mode: "create",
            classroom: null,
            name: "",
            subnetCidr: "",
            vlanId: "",
            displayOrder: "",
        });
    }

    function openEditClassroomForm(classroom: Classroom) {
        setError(null);

        setClassroomForm({
            mode: "edit",
            classroom,
            name: classroom.name,
            subnetCidr: classroom.subnet_cidr,
            vlanId: classroom.vlan_id?.toString() ?? "",
            displayOrder: classroom.display_order.toString(),
        });
    }

    function closeClassroomForm() {
        setClassroomForm(null);
    }

    async function handleClassroomFormSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (classroomForm === null) {
            return;
        }

        setError(null);
        setBusyClassroomForm(true);

        try {
            const name = parseRequiredString(classroomForm.name, "Название");
            const subnetCidr = parseRequiredString(
                classroomForm.subnetCidr,
                "Подсеть",
            );
            const vlanId = parseOptionalInteger(classroomForm.vlanId, "VLAN", {
                min: 1,
                max: 4094,
            });
            const displayOrder =
                parseOptionalInteger(classroomForm.displayOrder, "Порядок", {
                    min: 0,
                }) ?? 0;

            if (classroomForm.mode === "create") {
                const created = await createClassroom({
                    name,
                    subnet_cidr: subnetCidr,
                    vlan_id: vlanId,
                    display_order: displayOrder,
                    is_active: true,
                });

                setClassroomForm(null);
                await reloadClassrooms(created.id);
                return;
            }

            const updated = await updateClassroom(classroomForm.classroom.id, {
                name,
                subnet_cidr: subnetCidr,
                vlan_id: vlanId,
                display_order: displayOrder,
                is_active: true,
            });

            setClassroomForm(null);
            await reloadClassrooms(updated.id);
            await reload();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        } finally {
            setBusyClassroomForm(false);
        }
    }

    async function handleDeactivateClassroom() {
        if (classroomForm === null || classroomForm.mode !== "edit") {
            return;
        }

        const confirmed = window.confirm(
            `Деактивировать аудиторию "${classroomForm.classroom.name}"? Она исчезнет из списка вкладок, но останется в базе данных.`,
        );

        if (!confirmed) {
            return;
        }

        setError(null);
        setBusyClassroomForm(true);

        try {
            await updateClassroom(classroomForm.classroom.id, {
                is_active: false,
            });

            setClassroomForm(null);
            await reloadClassrooms(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        } finally {
            setBusyClassroomForm(false);
        }
    }

    useEffect(() => {
        let cancelled = false;

        async function loadInitialClassrooms() {
            setLoading(true);
            setError(null);

            try {
                const data = await getClassrooms();

                if (cancelled) {
                    return;
                }

                setClassrooms(data);
                setSelectedClassroomId(data[0]?.id ?? null);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Unknown error");
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        void loadInitialClassrooms();

        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        if (selectedClassroomId === null) {
            return;
        }

        let cancelled = false;

        async function loadSelectedDashboard() {
            setLoading(true);
            setError(null);

            try {
                const data = await getClassroomDashboard(selectedClassroomId);

                if (!cancelled) {
                    setDashboard(data);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Unknown error");
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        }

        void loadSelectedDashboard();

        const timerId = window.setInterval(() => {
            getClassroomDashboard(selectedClassroomId)
                .then((data) => {
                    if (!cancelled) {
                        setDashboard(data);
                    }
                })
                .catch(() => {
                    // Ошибку polling не показываем поверх экрана.
                });
        }, 5000);

        return () => {
            cancelled = true;
            window.clearInterval(timerId);
        };
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

        setDeviceForm({
            mode: "pin-observed",
            device,
            inventoryName: device.hostname ?? "",
            rowIndex: "",
            columnIndex: "",
            wanProtected: false,
        });
    }

    function openEditDeviceForm(device: DashboardDevice) {
        setError(null);

        setDeviceForm({
            mode: "edit-device",
            device,
            inventoryName: device.inventory_name,
            rowIndex: device.row_index?.toString() ?? "",
            columnIndex: device.column_index?.toString() ?? "",
            wanProtected: device.wan_protected,
        });
    }

    function closeDeviceForm() {
        setDeviceForm(null);
    }

    async function handleDeviceFormSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (selectedClassroomId === null || deviceForm === null) {
            return;
        }

        setError(null);
        setBusyForm(true);

        try {
            const rowIndex = parseOptionalPositiveInteger(
                deviceForm.rowIndex,
                "row_index",
            );
            const columnIndex = parseOptionalPositiveInteger(
                deviceForm.columnIndex,
                "column_index",
            );

            if (deviceForm.mode === "pin-observed") {
                await pinObservedDevice(selectedClassroomId, {
                    mac_address: deviceForm.device.mac_address,
                    inventory_name: emptyStringToNull(deviceForm.inventoryName),
                    row_index: rowIndex,
                    column_index: columnIndex,
                    wan_protected: deviceForm.wanProtected,
                });
            } else {
                await updateDevice(deviceForm.device.id, {
                    inventory_name: emptyStringToNull(deviceForm.inventoryName),
                    row_index: rowIndex,
                    column_index: columnIndex,
                    wan_protected: deviceForm.wanProtected,
                });
            }

            setDeviceForm(null);
            await reload();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        } finally {
            setBusyForm(false);
        }
    }

    async function handleUnpinDevice() {
        if (deviceForm === null || deviceForm.mode !== "edit-device") {
            return;
        }

        setError(null);
        setBusyForm(true);

        try {
            await unpinDevice(deviceForm.device.id);
            setDeviceForm(null);
            await reload();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Unknown error");
        } finally {
            setBusyForm(false);
        }
    }

    const deviceGrid = useMemo(() => {
        return buildDeviceGrid(dashboard?.devices ?? []);
    }, [dashboard]);

    const busyPinMac =
        deviceForm?.mode === "pin-observed" && busyForm
            ? deviceForm.device.mac_address
            : null;

    return (
        <div className="page">
            <Topbar
                onReload={reload}
                reloadDisabled={selectedClassroomId === null}
                onCreateClassroom={openCreateClassroomForm}
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

                            <button
                                className="secondary-button"
                                onClick={() => openEditClassroomForm(dashboard.classroom)}
                            >
                                Редактировать аудиторию
                            </button>
                        </section>

                        <DeviceGrid
                            deviceGrid={deviceGrid}
                            busyDeviceId={busyDeviceId}
                            onBlock={handleBlock}
                            onAllow={handleAllow}
                            onEdit={openEditDeviceForm}
                        />

                        <DynamicDevicesTable
                            devices={dashboard.dynamic_devices}
                            busyPinMac={busyPinMac}
                            onOpenPinForm={openPinObservedForm}
                        />
                    </>
                )}
            </main>

            {deviceForm && (
                <DeviceFormModal
                    form={deviceForm}
                    busy={busyForm}
                    onChange={setDeviceForm}
                    onClose={closeDeviceForm}
                    onSubmit={handleDeviceFormSubmit}
                    onUnpin={
                        deviceForm.mode === "edit-device" ? handleUnpinDevice : undefined
                    }
                />
            )}

            {classroomForm && (
                <ClassroomFormModal
                    form={classroomForm}
                    busy={busyClassroomForm}
                    onChange={setClassroomForm}
                    onClose={closeClassroomForm}
                    onSubmit={handleClassroomFormSubmit}
                    onDeactivate={
                        classroomForm.mode === "edit"
                            ? handleDeactivateClassroom
                            : undefined
                    }
                />
            )}
        </div>
    );
}
