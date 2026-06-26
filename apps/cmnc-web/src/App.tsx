import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
    allowClassroomWan,
    allowDeviceWan,
    blockClassroomWan,
    blockDeviceWan,
    cleanupStaleObservedDevices,
    clearAccessToken,
    deleteObservedDevice,
    extractErrorDetail,
    type BuildInfo,
    type Classroom,
    type ClassroomDashboard,
    type CurrentPrincipal,
    type DashboardDevice,
    type DynamicDevice,
    createClassroom,
    getClassroomDashboard,
    getClassrooms,
    getBuildInfo,
    getCurrentPrincipal,
    login,
    pinObservedDevice,
    unpinDevice,
    updateClassroom,
    updateDevice,
} from "./api";
import "./App.css";
import { ClassroomTabs } from "./components/ClassroomTabs/ClassroomTabs";
import { ClassroomCameraPanel } from "./components/ClassroomCameraPanel/ClassroomCameraPanel";
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
import { LoginPage } from "./pages/LoginPage/LoginPage";
import { AdminAccessPage } from "./pages/AdminAccessPage/AdminAccessPage";
import { AccountPage } from "./pages/AccountPage/AccountPage";
import { MaintenancePage } from "./pages/MaintenancePage/MaintenancePage";
import { RoutersAdminPage } from "./pages/RoutersAdminPage/RoutersAdminPage";
import {
    canControlWanForClassroom,
    canManageClassrooms,
    canManageWorkstations,
    canOpenAccessAdmin,
    canOpenMaintenance,
    canViewDynamicDevices,
} from "./auth/permissions";
import {
    buildDeviceGrid,
    emptyStringToNull,
    parseOptionalPositiveInteger,
} from "./utils/devices";
import { parseOptionalInteger, parseRequiredString } from "./utils/forms";

type AppPage = "dashboard" | "account" | "access" | "maintenance" | "routers";

export function App() {
    const [principal, setPrincipal] = useState<CurrentPrincipal | null>(null);
    const [authChecked, setAuthChecked] = useState(false);
    const [authBusy, setAuthBusy] = useState(false);
    const [authError, setAuthError] = useState<string | null>(null);
    const [currentPage, setCurrentPage] = useState<AppPage>("dashboard");
    const [buildInfo, setBuildInfo] = useState<BuildInfo | null>(null);

    const [classrooms, setClassrooms] = useState<Classroom[]>([]);
    const [selectedClassroomId, setSelectedClassroomId] = useState<number | null>(null);
    const [dashboard, setDashboard] = useState<ClassroomDashboard | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [busyDeviceId, setBusyDeviceId] = useState<number | null>(null);
    const [busyClassroomWanAction, setBusyClassroomWanAction] = useState<"block" | "allow" | null>(null);
    const [busyDeleteObservedDeviceId, setBusyDeleteObservedDeviceId] = useState<number | null>(null);
    const [busyCleanupStaleObservedDevices, setBusyCleanupStaleObservedDevices] = useState(false);
    const [deviceForm, setDeviceForm] = useState<DeviceFormState | null>(null);
    const [busyForm, setBusyForm] = useState(false);
    const [classroomForm, setClassroomForm] = useState<ClassroomFormState | null>(null);
    const [busyClassroomForm, setBusyClassroomForm] = useState(false);

    useEffect(() => {
        let cancelled = false;

        async function restoreSession() {
            try {
                const currentPrincipal = await getCurrentPrincipal();

                if (!cancelled) {
                    setPrincipal(currentPrincipal);
                }
            } catch {
                clearAccessToken();

                if (!cancelled) {
                    setPrincipal(null);
                }
            } finally {
                if (!cancelled) {
                    setAuthChecked(true);
                }
            }
        }

        void restoreSession();

        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        let cancelled = false;

        async function loadBuildInfo() {
            try {
                const data = await getBuildInfo();

                if (!cancelled) {
                    setBuildInfo(data);
                }
            } catch {
                if (!cancelled) {
                    setBuildInfo(null);
                }
            }
        }

        void loadBuildInfo();

        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        if (principal === null) {
            setClassrooms([]);
            setSelectedClassroomId(null);
            setDashboard(null);
            setLoading(false);
            return;
        }

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
                    setError(extractErrorDetail(err));
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
    }, [principal]);

    useEffect(() => {
        if (principal === null || selectedClassroomId === null) {
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
                    setError(extractErrorDetail(err));
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
    }, [principal, selectedClassroomId]);

    async function reload() {
        if (principal === null || selectedClassroomId === null) {
            return;
        }

        setError(null);

        try {
            const data = await getClassroomDashboard(selectedClassroomId);
            setDashboard(data);
        } catch (err) {
            setError(extractErrorDetail(err));
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

    async function handleLogin(username: string, password: string) {
        setAuthBusy(true);
        setAuthError(null);

        try {
            await login(username, password);
            const currentPrincipal = await getCurrentPrincipal();
            setPrincipal(currentPrincipal);
        } catch (err) {
            clearAccessToken();
            setPrincipal(null);
            setAuthError(extractErrorDetail(err));
        } finally {
            setAuthBusy(false);
        }
    }

    function handleLogout() {
        clearAccessToken();
        setPrincipal(null);
        setClassrooms([]);
        setSelectedClassroomId(null);
        setDashboard(null);
        setError(null);
        setBusyClassroomWanAction(null);
        setBusyDeleteObservedDeviceId(null);
        setBusyCleanupStaleObservedDevices(false);
        setDeviceForm(null);
        setClassroomForm(null);
        setCurrentPage("dashboard");
    }

    function openCreateClassroomForm() {
        if (!canManageClassrooms(principal)) {
            return;
        }

        setError(null);

        setClassroomForm({
            mode: "create",
            classroom: null,
            name: "",
            subnetCidr: "",
            vlanId: "",
            displayOrder: "",
            isService: false,
        });
    }

    function openEditClassroomForm(classroom: Classroom) {
        if (!canManageClassrooms(principal)) {
            return;
        }

        setError(null);

        setClassroomForm({
            mode: "edit",
            classroom,
            name: classroom.name,
            subnetCidr: classroom.subnet_cidr,
            vlanId: classroom.vlan_id?.toString() ?? "",
            displayOrder: classroom.display_order.toString(),
            isService: classroom.is_service,
        });
    }

    function closeClassroomForm() {
        setClassroomForm(null);
    }

    async function handleClassroomFormSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (classroomForm === null || !canManageClassrooms(principal)) {
            return;
        }

        setError(null);
        setBusyClassroomForm(true);

        try {
            const name = parseRequiredString(classroomForm.name, "Название");
            const subnetCidr = parseRequiredString(classroomForm.subnetCidr, "Подсеть");
            const vlanId = parseOptionalInteger(classroomForm.vlanId, "VLAN", {
                min: 1,
                max: 4094,
            });
            const displayOrder = parseOptionalInteger(classroomForm.displayOrder, "Порядок", {
                min: 0,
            }) ?? 0;

            if (classroomForm.mode === "create") {
                const created = await createClassroom({
                    name,
                    subnet_cidr: subnetCidr,
                    vlan_id: vlanId,
                    display_order: displayOrder,
                    is_active: true,
                    is_service: classroomForm.isService,
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
                is_service: classroomForm.isService,
            });

            setClassroomForm(null);
            await reloadClassrooms(updated.id);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusyClassroomForm(false);
        }
    }

    async function handleDeactivateClassroom() {
        if (
            classroomForm === null ||
            classroomForm.mode !== "edit" ||
            !canManageClassrooms(principal)
        ) {
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
            setError(extractErrorDetail(err));
        } finally {
            setBusyClassroomForm(false);
        }
    }

    async function handleBlock(deviceId: number) {
        if (!canControlWanForClassroom(principal, selectedClassroomId)) {
            return;
        }

        setBusyDeviceId(deviceId);
        setError(null);

        try {
            await blockDeviceWan(deviceId);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusyDeviceId(null);
        }
    }

    async function handleAllow(deviceId: number) {
        if (!canControlWanForClassroom(principal, selectedClassroomId)) {
            return;
        }

        setBusyDeviceId(deviceId);
        setError(null);

        try {
            await allowDeviceWan(deviceId);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusyDeviceId(null);
        }
    }

    async function handleBlockClassroomWan() {
        if (
            selectedClassroomId === null ||
            !canControlWanForClassroom(principal, selectedClassroomId)
        ) {
            return;
        }

        setBusyClassroomWanAction("block");
        setError(null);

        try {
            await blockClassroomWan(selectedClassroomId);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusyClassroomWanAction(null);
        }
    }

    async function handleAllowClassroomWan() {
        if (
            selectedClassroomId === null ||
            !canControlWanForClassroom(principal, selectedClassroomId)
        ) {
            return;
        }

        setBusyClassroomWanAction("allow");
        setError(null);

        try {
            await allowClassroomWan(selectedClassroomId);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusyClassroomWanAction(null);
        }
    }

    async function handleDeleteInactiveObservedDevice(device: DynamicDevice) {
        if (
            selectedClassroomId === null ||
            !canManageWorkstations(principal) ||
            device.active
        ) {
            return;
        }

        const confirmed = window.confirm(
            `Удалить неактивное устройство ${device.mac_address} из базы данных?`,
        );

        if (!confirmed) {
            return;
        }

        setBusyDeleteObservedDeviceId(device.id);
        setError(null);

        try {
            await deleteObservedDevice(selectedClassroomId, device.id);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusyDeleteObservedDeviceId(null);
        }
    }

    async function handleCleanupStaleObservedDevices() {
        if (selectedClassroomId === null || !canManageWorkstations(principal)) {
            return;
        }

        const confirmed = window.confirm(
            "Удалить из базы данных незакреплённые устройства, которые не появлялись больше 30 дней?",
        );

        if (!confirmed) {
            return;
        }

        setBusyCleanupStaleObservedDevices(true);
        setError(null);

        try {
            const result = await cleanupStaleObservedDevices(selectedClassroomId);
            await reload();

            if (result.deleted_count === 0) {
                setError("Нет незакреплённых устройств старше 30 дней.");
            }
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusyCleanupStaleObservedDevices(false);
        }
    }

    function openPinObservedForm(device: DynamicDevice) {
        if (!canManageWorkstations(principal)) {
            return;
        }

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
        if (!canManageWorkstations(principal)) {
            return;
        }

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

        if (
            selectedClassroomId === null ||
            deviceForm === null ||
            !canManageWorkstations(principal)
        ) {
            return;
        }

        setError(null);
        setBusyForm(true);

        try {
            const rowIndex = parseOptionalPositiveInteger(deviceForm.rowIndex, "row_index");
            const columnIndex = parseOptionalPositiveInteger(deviceForm.columnIndex, "column_index");

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
            setError(extractErrorDetail(err));
        } finally {
            setBusyForm(false);
        }
    }

    async function handleUnpinDevice() {
        if (
            deviceForm === null ||
            deviceForm.mode !== "edit-device" ||
            !canManageWorkstations(principal)
        ) {
            return;
        }

        setError(null);
        setBusyForm(true);

        try {
            await unpinDevice(deviceForm.device.id);
            setDeviceForm(null);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
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

    const userCanManageClassrooms = canManageClassrooms(principal);
    const userCanManageWorkstations = canManageWorkstations(principal);
    const userCanOpenAccessAdmin = canOpenAccessAdmin(principal);
    const userCanOpenMaintenance = canOpenMaintenance(principal);
    const userCanOpenRouters = userCanManageClassrooms;
    const userCanViewDynamicDevices = canViewDynamicDevices(principal);
    const userCanControlWan = canControlWanForClassroom(principal, selectedClassroomId);

    useEffect(() => {
        if (currentPage === "access" && !userCanOpenAccessAdmin) {
            setCurrentPage("dashboard");
        }

        if (currentPage === "maintenance" && !userCanOpenMaintenance) {
            setCurrentPage("dashboard");
        }

        if (currentPage === "routers" && !userCanOpenRouters) {
            setCurrentPage("dashboard");
        }
    }, [currentPage, userCanOpenAccessAdmin, userCanOpenMaintenance, userCanOpenRouters]);

    if (!authChecked) {
        return (
            <div className="page auth-page">
                <div className="loading">Проверка авторизации...</div>
            </div>
        );
    }

    if (principal === null) {
        return <LoginPage busy={authBusy} error={authError} onLogin={handleLogin} />;
    }

    return (
        <div className="page">
            <Topbar
                currentPage={currentPage}
                buildInfo={buildInfo}
                onReload={reload}
                reloadDisabled={selectedClassroomId === null}
                onCreateClassroom={openCreateClassroomForm}
                canCreateClassroom={userCanManageClassrooms}
                canOpenAccessAdmin={userCanOpenAccessAdmin}
                canOpenMaintenance={userCanOpenMaintenance}
                canOpenRouters={userCanOpenRouters}
                onOpenDashboard={() => setCurrentPage("dashboard")}
                onOpenAccount={() => setCurrentPage("account")}
                onOpenAccessAdmin={() => setCurrentPage("access")}
                onOpenMaintenance={() => setCurrentPage("maintenance")}
                onOpenRouters={() => setCurrentPage("routers")}
                principalName={getPrincipalName(principal)}
                onLogout={handleLogout}
            />

            <main className="content">
                {currentPage === "account" ? (
                    <AccountPage principal={principal} onPrincipalChanged={setPrincipal} />
                ) : currentPage === "access" && userCanOpenAccessAdmin ? (
                    <AdminAccessPage principal={principal} classrooms={classrooms} />
                ) : currentPage === "maintenance" && userCanOpenMaintenance ? (
                    <MaintenancePage />
                ) : currentPage === "routers" && userCanOpenRouters ? (
                    <RoutersAdminPage />
                ) : (
                    <>
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
                                            {dashboard.classroom.vlan_id ?? "-"}, MikroTik:{" "}
                                            {dashboard.classroom.router_id}
                                        </div>
                                    </div>

                                    <div className="classroom-actions">
                                        {userCanControlWan && (
                                            <>
                                                <button
                                                    className="danger-button"
                                                    disabled={busyClassroomWanAction !== null}
                                                    onClick={() => void handleBlockClassroomWan()}
                                                >
                                                    {busyClassroomWanAction === "block"
                                                        ? "Блокировка..."
                                                        : "Блокировать всё"}
                                                </button>

                                                <button
                                                    className="secondary-button"
                                                    disabled={busyClassroomWanAction !== null}
                                                    onClick={() => void handleAllowClassroomWan()}
                                                >
                                                    {busyClassroomWanAction === "allow"
                                                        ? "Разблокировка..."
                                                        : "Разблокировать всё"}
                                                </button>
                                            </>
                                        )}

                                        {userCanManageClassrooms && (
                                            <button
                                                className="secondary-button"
                                                onClick={() => openEditClassroomForm(dashboard.classroom)}
                                            >
                                                Редактировать аудиторию
                                            </button>
                                        )}
                                    </div>
                                </section>

                                {(dashboard.cameras ?? [])
                                    .filter((camera) => camera.enabled)
                                    .map((camera) => (
                                        <ClassroomCameraPanel
                                            key={camera.id ?? camera.name}
                                            classroomId={dashboard.classroom.id}
                                            camera={camera}
                                        />
                                    ))}

                                <DeviceGrid
                                    deviceGrid={deviceGrid}
                                    busyDeviceId={busyDeviceId}
                                    onBlock={handleBlock}
                                    onAllow={handleAllow}
                                    onEdit={openEditDeviceForm}
                                    canControlWan={userCanControlWan}
                                    canManageWorkstations={userCanManageWorkstations}
                                />

                                {userCanViewDynamicDevices && (
                                    <DynamicDevicesTable
                                        devices={dashboard.dynamic_devices}
                                        busyPinMac={busyPinMac}
                                        busyDeleteObservedDeviceId={busyDeleteObservedDeviceId}
                                        busyCleanupStale={busyCleanupStaleObservedDevices}
                                        onOpenPinForm={openPinObservedForm}
                                        onDeleteInactive={handleDeleteInactiveObservedDevice}
                                        onCleanupStale={handleCleanupStaleObservedDevices}
                                        canManageWorkstations={userCanManageWorkstations}
                                    />
                                )}
                            </>
                        )}
                    </>
                )}
            </main>

            {deviceForm && userCanManageWorkstations && (
                <DeviceFormModal
                    form={deviceForm}
                    busy={busyForm}
                    onChange={setDeviceForm}
                    onClose={closeDeviceForm}
                    onSubmit={handleDeviceFormSubmit}
                    onUnpin={deviceForm.mode === "edit-device" ? handleUnpinDevice : undefined}
                />
            )}

            {classroomForm && userCanManageClassrooms && (
                <ClassroomFormModal
                    form={classroomForm}
                    busy={busyClassroomForm}
                    onChange={setClassroomForm}
                    onClose={closeClassroomForm}
                    onSubmit={handleClassroomFormSubmit}
                    onDeactivate={classroomForm.mode === "edit" ? handleDeactivateClassroom : undefined}
                    onCamerasChanged={reload}
                />
            )}
        </div>
    );
}

function getPrincipalName(principal: CurrentPrincipal): string {
    return (
        principal.display_name ||
        principal.username ||
        principal.login ||
        String(principal.user_id ?? principal.id ?? "Пользователь")
    );
}
