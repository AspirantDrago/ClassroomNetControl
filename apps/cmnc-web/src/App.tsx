import { SettingsPage } from "./pages/SettingsPage/SettingsPage";
import { useDisplaySettings } from "./config/displaySettings";
import { useNotify, bulkNotification } from "./components/Notifications/notificationContext";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
    allowClassroomWan,
    allowDeviceWan,
    wakeDevice,
    wakeClassroom,
    getClassroomVeyonStatus,
    powerVeyonDevice,
    powerVeyonClassroom,
    type VeyonBulkPowerAction,
    blockClassroomWan,
    blockDeviceWan,
    cleanupStaleObservedDevices,
    cleanupAllObservedDevices,
    clearAccessToken,
    deleteObservedDevice,
    extractErrorDetail,
    type AdminRouter,
    type BuildInfo,
    type Classroom,
    type ClassroomDashboard,
    type CurrentPrincipal,
    type DashboardDevice,
    type DynamicDevice,
    createClassroom,
    getAdminRouters,
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
import { ClassroomVeyonActions } from "./components/Veyon/ClassroomVeyonActions";
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
import { REFRESH_INTERVALS } from "./config/refreshIntervals";
import {
    ClassroomStatisticsButton
} from "./components/ClassroomStatisticsModal/ClassroomStatisticsModal.tsx";

type AppPage = "dashboard" | "account" | "access" | "maintenance" | "routers" | "settings";

export function App() {
    const notify = useNotify();
    const [principal, setPrincipal] = useState<CurrentPrincipal | null>(null);
    const [displaySettings, setDisplaySettings] = useDisplaySettings(principal);
    const userCanOpenSettings = principal?.role === "admin" || principal?.role === "superadmin";
    const showInactiveClassrooms = userCanOpenSettings && displaySettings.showInactiveClassrooms;
    const [authChecked, setAuthChecked] = useState(false);
    const [authBusy, setAuthBusy] = useState(false);
    const [authError, setAuthError] = useState<string | null>(null);
    const [currentPage, setCurrentPage] = useState<AppPage>("dashboard");
    const [buildInfo, setBuildInfo] = useState<BuildInfo | null>(null);

    const [classrooms, setClassrooms] = useState<Classroom[]>([]);
    const [routers, setRouters] = useState<AdminRouter[]>([]);
    const [selectedClassroomId, setSelectedClassroomId] = useState<number | null>(null);
    const [dashboard, setDashboard] = useState<ClassroomDashboard | null>(null);
    const veyonConfigured = dashboard?.veyon_configured === true;
    useEffect(() => {
        if (!dashboard?.veyon_configuration_stale) return;
        const classroomId = dashboard.classroom.id;
        let stopped = false;
        void getClassroomVeyonStatus(classroomId).then(status => {
            if (!stopped) setDashboard(current => current?.classroom.id === classroomId
                ? {...current, veyon_configured: status.configured, veyon_configuration_stale: false} : current);
        }).catch(() => {});
        return () => {stopped = true;};
    }, [dashboard]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [busyDeviceId, setBusyDeviceId] = useState<number | null>(null);
    const [showDeviceThumbnails, setShowDeviceThumbnails] = useState(true);
    const [busyPower, setBusyPower] = useState(false);
    const [busyClassroomPowerAction, setBusyClassroomPowerAction] = useState<VeyonBulkPowerAction | null>(null);
    const [busyWakeAction, setBusyWakeAction] = useState<number | "all" | null>(null);
    const [wakeMessage, setWakeMessage] = useState<string | null>(null);
    const [busyClassroomWanAction, setBusyClassroomWanAction] = useState<"block" | "allow" | null>(null);
    const [busyDeleteObservedDeviceId, setBusyDeleteObservedDeviceId] = useState<number | null>(null);
    const [busyCleanupStaleObservedDevices, setBusyCleanupStaleObservedDevices] = useState(false);
    const [busyCleanupAllObservedDevices, setBusyCleanupAllObservedDevices] = useState(false);
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
                const data = await getClassrooms(showInactiveClassrooms);

                if (cancelled) {
                    return;
                }

                setClassrooms(data);
                setSelectedClassroomId(previous => data.some(classroom => classroom.id === previous && classroom.is_active) ? previous : data.find(classroom => classroom.is_active)?.id ?? null);
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
    }, [principal, showInactiveClassrooms]);

    useEffect(() => {
        if (principal === null || !canManageClassrooms(principal)) {
            setRouters([]);
            return;
        }

        let cancelled = false;

        async function loadRouters() {
            try {
                const data = await getAdminRouters();

                if (!cancelled) {
                    setRouters(data);
                }
            } catch {
                if (!cancelled) {
                    setRouters([]);
                }
            }
        }

        void loadRouters();

        return () => {
            cancelled = true;
        };
    }, [principal]);

    useEffect(() => {
        if (
            principal === null ||
            selectedClassroomId === null ||
            currentPage !== "dashboard"
        ) {
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
            if (document.visibilityState !== "visible") {
                return;
            }

            getClassroomDashboard(selectedClassroomId)
                .then((data) => {
                    if (!cancelled) {
                        setDashboard(data);
                    }
                })
                .catch(() => {
                    // Ошибку polling не показываем поверх экрана.
                });
        }, REFRESH_INTERVALS.dashboard);

        return () => {
            cancelled = true;
            window.clearInterval(timerId);
        };
    }, [principal, selectedClassroomId, currentPage]);

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

    async function reloadRouters() {
        if (principal === null || !canManageClassrooms(principal)) {
            setRouters([]);
            return;
        }

        try {
            const data = await getAdminRouters();
            setRouters(data);
        } catch {
            setRouters([]);
        }
    }

    async function reloadClassrooms(preferredClassroomId?: number | null) {
        const data = await getClassrooms(showInactiveClassrooms);
        setClassrooms(data);

        if (!data.some(classroom => classroom.is_active)) {
            setSelectedClassroomId(null);
            setDashboard(null);
            return;
        }

        if (
            preferredClassroomId !== undefined &&
            preferredClassroomId !== null &&
            data.some((classroom) => classroom.id === preferredClassroomId && classroom.is_active)
        ) {
            setSelectedClassroomId(preferredClassroomId);
            return;
        }

        if (
            selectedClassroomId !== null &&
            data.some((classroom) => classroom.id === selectedClassroomId && classroom.is_active)
        ) {
            return;
        }

        setSelectedClassroomId(previous => data.some(classroom => classroom.id === previous && classroom.is_active) ? previous : data.find(classroom => classroom.is_active)?.id ?? null);
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
        setRouters([]);
        setSelectedClassroomId(null);
        setDashboard(null);
        setError(null);
        setBusyClassroomWanAction(null);
        setBusyDeleteObservedDeviceId(null);
        setBusyCleanupStaleObservedDevices(false);
        setBusyCleanupAllObservedDevices(false);
        setDeviceForm(null);
        setClassroomForm(null);
        setCurrentPage("dashboard");
    }

    function getDefaultClassroomRouterId(): number {
        return (
            dashboard?.classroom.router_id ??
            classrooms[0]?.router_id ??
            routers.find((router) => router.is_enabled)?.id ??
            routers[0]?.id ??
            1
        );
    }

    function openCreateClassroomForm() {
        if (!canManageClassrooms(principal)) {
            return;
        }

        setError(null);
        void reloadRouters();

        setClassroomForm({
            mode: "create",
            classroom: null,
            routerId: getDefaultClassroomRouterId().toString(),
            name: "",
            subnetCidr: "",
            vlanId: "",
            displayOrder: "",
            isService: false,
            isActive: true,
        });
    }

    function openEditClassroomForm(classroom: Classroom) {
        if (!canManageClassrooms(principal)) {
            return;
        }

        setError(null);
        void reloadRouters();

        setClassroomForm({
            mode: "edit",
            classroom,
            routerId: classroom.router_id.toString(),
            name: classroom.name,
            subnetCidr: classroom.subnet_cidr,
            vlanId: classroom.vlan_id?.toString() ?? "",
            displayOrder: classroom.display_order.toString(),
            isService: classroom.is_service,
            isActive: classroom.is_active,
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
            const routerId = parseOptionalInteger(classroomForm.routerId, "MikroTik", {
                min: 1,
            });
            const vlanId = parseOptionalInteger(classroomForm.vlanId, "VLAN", {
                min: 1,
                max: 4094,
            });
            const displayOrder = parseOptionalInteger(classroomForm.displayOrder, "Порядок", {
                min: 0,
            }) ?? 0;

            if (routerId === null) {
                throw new Error("MikroTik должен быть выбран");
            }

            if (classroomForm.mode === "create") {
                const created = await createClassroom({
                    name,
                    router_id: routerId,
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
                router_id: routerId,
                subnet_cidr: subnetCidr,
                vlan_id: vlanId,
                display_order: displayOrder,
                is_active: classroomForm.isActive,
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

    async function handlePower(device: DashboardDevice, action: "power-down" | "reboot") {
        if (busyPower) return;
        const verb = action === "power-down" ? "Выключить" : "Перезагрузить";
        if (!window.confirm(`${verb} устройство «${device.inventory_name || device.mac_address}»? Несохранённые данные могут быть потеряны.`)) return;
        setBusyPower(true); setError(null); setWakeMessage(null);
        try {
            await powerVeyonDevice(device.id, action);
            setWakeMessage(`Команда «${verb}» отправлена через Veyon.`);
        } catch (err) { setError(extractErrorDetail(err)); }
        finally { setBusyPower(false); }
    }

    async function handleClassroomPower(action: VeyonBulkPowerAction) {
        if (!dashboard || dashboard.classroom.id !== selectedClassroomId || busyPower) return;
        if (action === "install-updates-and-power-down" && principal?.role !== "admin" && principal?.role !== "superadmin") return;
        const targets = dashboard.devices.filter((device) => device.is_pinned && !device.veyon_bulk_protected);
        if (!targets.length) return;
        const labels = {
            "power-down": {question: "Выключить", result: "выключения"},
            "reboot": {question: "Перезагрузить", result: "перезагрузки"},
            "install-updates-and-power-down": {question: "Установить обновления и выключить", result: "установки обновлений и выключения"},
        }[action];
        if (!window.confirm(`${labels.question} устройства аудитории «${dashboard.classroom.name}» (${targets.length})? Устройства с защитой от массового управления через Veyon будут пропущены. Несохранённые данные могут быть потеряны.`)) return;
        setBusyPower(true); setBusyClassroomPowerAction(action); setError(null); setWakeMessage(null);
        try {
            const result = await powerVeyonClassroom(dashboard.classroom.id, action);
            const notification = bulkNotification(dashboard.classroom.name, `${labels.question} все`, result);
            notify(notification.content, notification.kind);
        } catch (err) { notify({context: dashboard.classroom.name, action: `${labels.question} все`, items: [extractErrorDetail(err)]}, "error"); }
        finally { setBusyPower(false); setBusyClassroomPowerAction(null); }
    }

    async function handleWake(deviceId?: number) {
        if (selectedClassroomId === null || busyWakeAction !== null) return;
        setBusyWakeAction(deviceId ?? "all");
        setWakeMessage(null);
        setError(null);
        try {
            const result = deviceId === undefined
                ? await wakeClassroom(selectedClassroomId)
                : await wakeDevice(deviceId);
            setWakeMessage((result.failed_count
                ? `Пакеты WoL отправлены: ${result.sent_count}. Не удалось отправить: ${result.failed_count}. ${result.results.find((item) => !item.sent)?.error ?? ""}`
                : result.sent_count ? "Пакеты WoL отправлены." : "Нет устройств для пробуждения.")
                + (result.skipped_count ? ` Пропущено защищённых: ${result.skipped_count}.` : ""));
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusyWakeAction(null);
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

    async function handleCleanupAllObservedDevices() {
        if (selectedClassroomId === null || !canManageWorkstations(principal) ||
            busyCleanupAllObservedDevices || busyCleanupStaleObservedDevices) {
            return;
        }

        const confirmed = window.confirm(
            "Удалить из базы данных ВСЕ незакреплённые устройства текущей аудитории, включая активные? Закреплённые устройства останутся. Активные устройства могут появиться снова после опроса MikroTik.",
        );
        if (!confirmed) return;

        setBusyCleanupAllObservedDevices(true);
        setError(null);
        try {
            await cleanupAllObservedDevices(selectedClassroomId);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusyCleanupAllObservedDevices(false);
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
            veyonBulkProtected: false,
            wolProtected: false,
        });
    }

    function openEditDeviceForm(device: DashboardDevice) {
        setError(null);
        setWakeMessage(null);

        setDeviceForm({
            mode: "edit-device",
            device,
            inventoryName: device.inventory_name,
            rowIndex: device.row_index?.toString() ?? "",
            columnIndex: device.column_index?.toString() ?? "",
            wanProtected: device.wan_protected,
            veyonBulkProtected: device.veyon_bulk_protected ?? false,
            wolProtected: device.wol_protected ?? false,
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
                    veyon_bulk_protected: deviceForm.veyonBulkProtected,
                    wol_protected: deviceForm.wolProtected,
                });
            } else {
                await updateDevice(deviceForm.device.id, {
                    inventory_name: emptyStringToNull(deviceForm.inventoryName),
                    row_index: rowIndex,
                    column_index: columnIndex,
                    wan_protected: deviceForm.wanProtected,
                    veyon_bulk_protected: deviceForm.veyonBulkProtected,
                    wol_protected: deviceForm.wolProtected,
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

    const routerNames = useMemo(() => {
        return new Map(routers.map((router) => [router.id, router.name]));
    }, [routers]);

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
    const hasPowerDownTargets = veyonConfigured && (dashboard?.devices.some((device) => device.is_pinned && !device.veyon_bulk_protected) ?? false);
    const hasWakeTargets = dashboard?.devices.some((device) => device.is_pinned && !device.wol_protected) ?? false;

    useEffect(() => {
        if (currentPage === "settings" && !userCanOpenSettings) setCurrentPage("dashboard");
        if (currentPage === "access" && !userCanOpenAccessAdmin) {
            setCurrentPage("dashboard");
        }

        if (currentPage === "maintenance" && !userCanOpenMaintenance) {
            setCurrentPage("dashboard");
        }

        if (currentPage === "routers" && !userCanOpenRouters) {
            setCurrentPage("dashboard");
        }
    }, [currentPage, userCanOpenSettings, userCanOpenAccessAdmin, userCanOpenMaintenance, userCanOpenRouters]);

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
                canOpenSettings={userCanOpenSettings}
                onOpenSettings={() => setCurrentPage("settings")}
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
                ) : currentPage === "settings" && userCanOpenSettings ? (
                    <SettingsPage settings={displaySettings} onChange={setDisplaySettings} />
                ) : currentPage === "access" && userCanOpenAccessAdmin ? (
                    <AdminAccessPage principal={principal} classrooms={classrooms.filter(classroom => classroom.is_active)} displaySettings={displaySettings} />
                ) : currentPage === "maintenance" && userCanOpenMaintenance ? (
                    <MaintenancePage />
                ) : currentPage === "routers" && userCanOpenRouters ? (
                    <RoutersAdminPage />
                ) : (
                    <>
                        <ClassroomTabs
                            classrooms={classrooms}
                            selectedClassroomId={selectedClassroomId}
                            onSelect={(id) => { const classroom = classrooms.find(item => item.id === id); if (classroom && !classroom.is_active) {openEditClassroomForm(classroom); return;} setWakeMessage(null); setSelectedClassroomId(id); }}
                        />

                        {error && <pre className="error-box">{error}</pre>}
                        {wakeMessage && <div className="muted" role="status">{wakeMessage}</div>}

                        {loading && <div className="loading">Загрузка...</div>}

                        {dashboard && (
                            <>
                                <section className="classroom-header">
                                    <div>
                                        <h2>{dashboard.classroom.name}</h2>
                                        <div className="muted">
                                            subnet: {dashboard.classroom.subnet_cidr}, VLAN:{" "}
                                            {dashboard.classroom.vlan_id ?? "-"}, MikroTik:{" "}
                                            {getRouterDisplayName(
                                                dashboard.classroom.router_id,
                                                routerNames,
                                            )}
                                        </div>
                                    </div>

                                    <div className="classroom-actions">
                                        <ClassroomStatisticsButton
                                            key={dashboard.classroom.id}
                                            classroomId={dashboard.classroom.id}
                                            classroomName={dashboard.classroom.name}
                                        />
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

                                <div className="classroom-device-actions">
                                    {userCanControlWan && dashboard.devices.some((device) => !device.wan_allowed || !device.wan_protected) && (
                                        <section className="classroom-action-row" aria-label="Интернет">
                                            <span className="classroom-action-label">Интернет:</span>
                                            <div className="classroom-actions">
                                    {userCanControlWan && dashboard.devices.some((device) => !device.wan_protected && device.wan_allowed) && (
                                        <button
                                            className="danger-button"
                                            disabled={busyClassroomWanAction !== null || dashboard.classroom.id !== selectedClassroomId}
                                            onClick={() => void handleBlockClassroomWan()}
                                        >
                                            {busyClassroomWanAction === "block" ? "Отключение..." : "Отключить всем Интернет"}
                                        </button>
                                    )}
                                    {userCanControlWan && dashboard.devices.some((device) => !device.wan_allowed) && (
                                        <button
                                            className="success-button"
                                            disabled={busyClassroomWanAction !== null || dashboard.classroom.id !== selectedClassroomId}
                                            onClick={() => void handleAllowClassroomWan()}
                                        >
                                            {busyClassroomWanAction === "allow" ? "Включение..." : "Включить всем Интернет"}
                                        </button>
                                    )}
                                            </div>
                                        </section>
                                    )}
                                    <ClassroomVeyonActions key={dashboard.classroom.id}
                                        classroomId={dashboard.classroom.id} classroomName={dashboard.classroom.name} veyonConfigured={veyonConfigured}
                                        targetCount={dashboard.devices.filter(device => device.is_pinned && !device.veyon_bulk_protected).length}
                                        showPowerRow={hasPowerDownTargets || hasWakeTargets} role={principal.role}
                                        disabled={busyPower || dashboard.classroom.id !== selectedClassroomId} onBusyChange={setBusyPower}>
                                                {hasPowerDownTargets && <button className="danger-button"
                                                    disabled={busyPower || dashboard.classroom.id !== selectedClassroomId}
                                                    onClick={() => void handleClassroomPower("power-down")}>
                                                    {busyClassroomPowerAction === "power-down" ? "Отправка команды..." : "Выключить все"}
                                                </button>}
                                                {hasPowerDownTargets && <button className="secondary-button"
                                                    disabled={busyPower || dashboard.classroom.id !== selectedClassroomId}
                                                    onClick={() => void handleClassroomPower("reboot")}>
                                                    {busyClassroomPowerAction === "reboot" ? "Отправка команды..." : "Перезагрузить всё"}
                                                </button>}
                                                {hasWakeTargets && <button className="success-button"
                                                    disabled={busyWakeAction !== null || dashboard.classroom.id !== selectedClassroomId}
                                                    onClick={() => void handleWake()}>
                                                    {busyWakeAction === "all" ? "Отправка WoL..." : "Разбудить всё"}
                                                </button>}
                                                {hasPowerDownTargets && (principal.role === "admin" || principal.role === "superadmin") && <button className="danger-button"
                                                    disabled={busyPower || dashboard.classroom.id !== selectedClassroomId}
                                                    onClick={() => void handleClassroomPower("install-updates-and-power-down")}>
                                                    {busyClassroomPowerAction === "install-updates-and-power-down" ? "Отправка команды..." : "Установить обновления и выключить все"}
                                                </button>}
                                    </ClassroomVeyonActions>
                                </div>

                                <div className="device-view-controls">
                                        <div className="device-view-switch">
                                            <span>Описание</span>
                                            <button type="button" role="switch" aria-label="Миниатюры экранов" aria-checked={showDeviceThumbnails}
                                                onClick={() => {
                                                    const next = !showDeviceThumbnails;
                                                    setShowDeviceThumbnails(next);
                                                }}><span /></button>
                                            <span>Миниатюры</span>
                                        </div>
                                </div>

                                <DeviceGrid
                                    deviceGrid={deviceGrid}
                                    showThumbnails={showDeviceThumbnails}
                                    busyDeviceId={busyDeviceId}
                                    onBlock={handleBlock}
                                    onAllow={handleAllow}
                                    onEdit={openEditDeviceForm}
                                    canControlWan={userCanControlWan}
                                />

                                {userCanViewDynamicDevices && (
                                    <DynamicDevicesTable
                                        devices={dashboard.dynamic_devices}
                                        busyPinMac={busyPinMac}
                                        busyDeleteObservedDeviceId={busyDeleteObservedDeviceId}
                                        busyCleanupStale={busyCleanupStaleObservedDevices}
                                        busyCleanupAll={busyCleanupAllObservedDevices}
                                        onOpenPinForm={openPinObservedForm}
                                        onDeleteInactive={handleDeleteInactiveObservedDevice}
                                        onCleanupStale={handleCleanupStaleObservedDevices}
                                        onCleanupAll={handleCleanupAllObservedDevices}
                                        canManageWorkstations={userCanManageWorkstations}
                                    />
                                )}
                            </>
                        )}
                    </>
                )}
            </main>

            {deviceForm && (deviceForm.mode === "edit-device" || userCanManageWorkstations) && (
                <DeviceFormModal
                    veyonConfigured={veyonConfigured}
                    principalRole={principal.role}
                    classroomName={classrooms.find((classroom) => classroom.id === (deviceForm.mode === "edit-device" ? deviceForm.device.classroom_id : selectedClassroomId))?.name}
                    key={`${deviceForm.mode}:${deviceForm.device.id}`}
                    form={deviceForm.mode === "edit-device" ? {
                        ...deviceForm,
                        device: dashboard?.devices.find((device) => device.id === deviceForm.device.id) ?? deviceForm.device,
                    } : deviceForm}
                    busy={busyForm}
                    canManage={userCanManageWorkstations && (principal.role === "admin" || principal.role === "superadmin")}
                    canControlWan={userCanControlWan}
                    wanBusy={busyDeviceId === deviceForm.device.id}
                    wakeBusy={busyWakeAction !== null}
                    powerBusy={busyPower}
                    onPower={(device, action) => void handlePower(device, action)}
                    onWake={(device) => void handleWake(device.id)}
                    wakeMessage={wakeMessage}
                    onToggleWan={(device) => {
                        if (device.wan_allowed) void handleBlock(device.id);
                        else void handleAllow(device.id);
                    }}
                    error={error}
                    onChange={setDeviceForm}
                    onClose={closeDeviceForm}
                    onSubmit={handleDeviceFormSubmit}
                    onUnpin={deviceForm.mode === "edit-device" ? handleUnpinDevice : undefined}
                />
            )}

            {classroomForm && userCanManageClassrooms && (
                <ClassroomFormModal
                    form={classroomForm}
                    routers={routers}
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

function getRouterDisplayName(
    routerId: number,
    routerNames: Map<number, string>,
): string {
    const routerName = routerNames.get(routerId);

    if (routerName) {
        return `${routerName} (#${routerId})`;
    }

    return `#${routerId}`;
}
