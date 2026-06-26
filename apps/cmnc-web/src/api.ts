const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const ACCESS_TOKEN_STORAGE_KEY = "cmnc_access_token";

export type Classroom = {
    id: number;
    router_id: number;
    name: string;
    subnet_cidr: string;
    vlan_id: number | null;
    display_order: number;
    is_active: boolean;
    is_service: boolean;
};

export type DashboardDevice = {
    id: number;
    classroom_id: number;
    mac_address: string;
    inventory_name: string;
    hostname: string | null;
    static_ip: string | null;
    active_ip: string | null;
    observed_hostname: string | null;
    row_index: number | null;
    column_index: number | null;
    is_pinned: boolean;
    wan_allowed: boolean;
    wan_protected: boolean;
    policy_generation: number;
    sync_status: string;
    sync_error: string | null;
    online: boolean;
    last_seen_at: string | null;
};

export type DynamicDevice = {
    id: number;
    router_id: number;
    mac_address: string;
    active_ip: string | null;
    hostname: string | null;
    dynamic: boolean | null;
    active: boolean;
    last_seen_at: string | null;
    raw: Record<string, unknown>;
};

export type CameraQuality = "main" | "sub";

export type ClassroomCamera = {
    id: number | null;
    name: string;
    enabled: boolean;
    qualities: CameraQuality[];
    default_quality: CameraQuality;
};

export type CameraSessionResponse = {
    mode: "hls" | "fmp4" | "webrtc" | string;
    quality: CameraQuality;
    session_id: string;
    url: string;
    expires_in_seconds: number | null;
};

export type ClassroomDashboard = {
    classroom: Classroom;
    devices: DashboardDevice[];
    dynamic_devices: DynamicDevice[];
    cameras: ClassroomCamera[];
};

export type CurrentPrincipal = {
    user_id?: number | string;
    id?: number | string;
    username?: string;
    login?: string;
    display_name?: string | null;
    principal_type?: string;
    role?: string;
    permissions: string[];
    classroom_ids?: number[];
    allowed_classroom_ids?: number[];
};

export type LoginResponse = {
    access_token: string;
    token_type: string;
};

export type BuildInfo = {
    git_commit_count: number;
    compose_build_number: number;
    version: string;
    built_at: string | null;
};

export function getAccessToken(): string | null {
    return window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
}

export function setAccessToken(token: string): void {
    window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
}

export function extractErrorDetail(error: unknown): string {
    const fallback = "Unknown error";

    if (error instanceof Error) {
        return extractErrorDetail(error.message);
    }

    if (typeof error === "object" && error !== null) {
        if ("detail" in error) {
            return stringifyErrorDetail((error as { detail: unknown }).detail) || fallback;
        }

        if ("message" in error) {
            return extractErrorDetail((error as { message: unknown }).message);
        }
    }

    if (typeof error !== "string") {
        return fallback;
    }

    const text = error.trim();

    if (text === "") {
        return fallback;
    }

    try {
        const parsed = JSON.parse(text) as unknown;

        if (typeof parsed === "object" && parsed !== null) {
            if ("detail" in parsed) {
                return stringifyErrorDetail((parsed as { detail: unknown }).detail) || text;
            }

            if ("message" in parsed) {
                return extractErrorDetail((parsed as { message: unknown }).message);
            }
        }
    } catch {
        // Это обычная строка, не JSON.
    }

    return text;
}

function stringifyErrorDetail(detail: unknown): string {
    if (typeof detail === "string") {
        return detail;
    }

    if (Array.isArray(detail)) {
        return detail
            .map((item) => {
                if (typeof item === "object" && item !== null && "msg" in item) {
                    return String((item as { msg: unknown }).msg);
                }

                return extractErrorDetail(item);
            })
            .filter((item) => item.trim() !== "")
            .join("; ");
    }

    if (detail === null || detail === undefined) {
        return "";
    }

    return String(detail);
}

export function clearAccessToken(): void {
    window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
    window.localStorage.removeItem("access_token");
    window.localStorage.removeItem("token");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const token = getAccessToken();

    const response = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            ...(init?.headers ?? {}),
        },
    });

    if (response.status === 401) {
        clearAccessToken();
    }

    if (!response.ok) {
        const message = await readErrorMessage(response);
        throw new Error(message || `HTTP ${response.status}`);
    }

    if (response.status === 204) {
        return undefined as T;
    }

    const data: unknown = await response.json();
    return data as T;
}

async function readErrorMessage(response: Response): Promise<string> {
    const text = await response.text();
    return extractErrorDetail(text);
}

async function postLoginJson(username: string, password: string): Promise<Response> {
    return fetch(`${API_BASE_URL}/api/auth/login`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
    });
}

async function postLoginForm(username: string, password: string): Promise<Response> {
    const body = new URLSearchParams();
    body.set("username", username);
    body.set("password", password);

    return fetch(`${API_BASE_URL}/api/auth/login`, {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body,
    });
}

export async function login(username: string, password: string): Promise<LoginResponse> {
    let response = await postLoginJson(username, password);

    if (response.status === 400 || response.status === 415 || response.status === 422) {
        response = await postLoginForm(username, password);
    }

    if (!response.ok) {
        const message = await readErrorMessage(response);
        throw new Error(message || `HTTP ${response.status}`);
    }

    const data = (await response.json()) as LoginResponse;

    if (!data.access_token) {
        throw new Error("Login response does not contain access_token");
    }

    setAccessToken(data.access_token);
    return data;
}

export function getCurrentPrincipal(): Promise<CurrentPrincipal> {
    return request<CurrentPrincipal>("/api/me");
}

export function getBuildInfo(): Promise<BuildInfo> {
    return request<BuildInfo>("/api/build-info");
}

export type CurrentAccountUpdateRequest = {
    display_name: string;
    password?: string;
};

export function updateCurrentAccount(
    payload: CurrentAccountUpdateRequest,
): Promise<CurrentPrincipal> {
    return request<CurrentPrincipal>("/api/me", {
        method: "PATCH",
        body: JSON.stringify(payload),
    });
}

export function getClassrooms(): Promise<Classroom[]> {
    return request<Classroom[]>("/api/classrooms");
}

export function getClassroomDashboard(classroomId: number | null): Promise<ClassroomDashboard> {
    return request<ClassroomDashboard>(`/api/classrooms/${classroomId}/dashboard`);
}

export function blockDeviceWan(deviceId: number): Promise<unknown> {
    return request(`/api/devices/${deviceId}/wan/block`, {
        method: "POST",
    });
}

export function allowDeviceWan(deviceId: number): Promise<unknown> {
    return request(`/api/devices/${deviceId}/wan/allow`, {
        method: "POST",
    });
}

export function blockClassroomWan(classroomId: number): Promise<unknown> {
    return request(`/api/classrooms/${classroomId}/wan/block-all`, {
        method: "POST",
    });
}

export function allowClassroomWan(classroomId: number): Promise<unknown> {
    return request(`/api/classrooms/${classroomId}/wan/allow-all`, {
        method: "POST",
    });
}

export function createClassroomCameraSession(
    classroomId: number,
    cameraId: number,
    quality: CameraQuality,
): Promise<CameraSessionResponse> {
    return request<CameraSessionResponse>(
        `/api/classrooms/${classroomId}/cameras/${cameraId}/session`,
        {
            method: "POST",
            body: JSON.stringify({ quality }),
        },
    );
}

export function deleteCameraSession(sessionId: string): Promise<undefined> {
    return request<undefined>(`/api/camera/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
    });
}

export function getCameraStreamUrl(path: string): string {
    return `${API_BASE_URL}${path}`;
}

export type PinObservedDeviceRequest = {
    mac_address: string;
    inventory_name?: string | null;
    row_index?: number | null;
    column_index?: number | null;
    wan_protected?: boolean;
};

export type DeleteObservedDevicesResponse = {
    deleted_ids: number[];
    deleted_count: number;
};

export function deleteObservedDevice(
    classroomId: number,
    observedDeviceId: number,
): Promise<DeleteObservedDevicesResponse> {
    return request<DeleteObservedDevicesResponse>(
        `/api/admin/classrooms/${classroomId}/observed-devices/${observedDeviceId}/delete`,
        {
            method: "POST",
        },
    );
}

export function cleanupStaleObservedDevices(
    classroomId: number,
): Promise<DeleteObservedDevicesResponse> {
    return request<DeleteObservedDevicesResponse>(
        `/api/admin/classrooms/${classroomId}/observed-devices/cleanup-stale`,
        {
            method: "POST",
        },
    );
}

export function pinObservedDevice(
    classroomId: number,
    payload: PinObservedDeviceRequest,
): Promise<unknown> {
    return request(
        `/api/admin/classrooms/${classroomId}/devices/pin-observed`,
        {
            method: "POST",
            body: JSON.stringify(payload),
        },
    );
}

export type UpdateDeviceRequest = {
    inventory_name?: string | null;
    row_index?: number | null;
    column_index?: number | null;
    wan_protected?: boolean;
};

export function updateDevice(
    deviceId: number,
    payload: UpdateDeviceRequest,
): Promise<unknown> {
    return request(`/api/admin/devices/${deviceId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
    });
}

export function unpinDevice(deviceId: number): Promise<unknown> {
    return request(`/api/admin/devices/${deviceId}/unpin`, {
        method: "POST",
    });
}

export type ClassroomCreateRequest = {
    name: string;
    router_id?: number;
    subnet_cidr: string;
    vlan_id?: number | null;
    display_order?: number;
    is_active?: boolean;
    is_service?: boolean;
};

export type ClassroomUpdateRequest = {
    name?: string;
    router_id?: number;
    subnet_cidr?: string;
    vlan_id?: number | null;
    display_order?: number;
    is_active?: boolean;
    is_service?: boolean;
};

export function createClassroom(
    payload: ClassroomCreateRequest,
): Promise<Classroom> {
    return request<Classroom>("/api/admin/classrooms", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export function updateClassroom(
    classroomId: number,
    payload: ClassroomUpdateRequest,
): Promise<Classroom> {
    return request<Classroom>(`/api/admin/classrooms/${classroomId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
    });
}

export type AdminClassroomCamera = {
    id: number;
    classroom_id: number;
    name: string;
    sort_order: number;
    is_enabled: boolean;
    rtsp_main_stream: string | null;
    rtsp_sub_stream: string | null;
    default_quality: CameraQuality;
};

export type AdminClassroomCameraCreateRequest = {
    name: string;
    sort_order: number;
    is_enabled: boolean;
    rtsp_main_stream: string | null;
    rtsp_sub_stream: string | null;
    default_quality: CameraQuality;
};

export type AdminClassroomCameraUpdateRequest = {
    name?: string;
    sort_order?: number;
    is_enabled?: boolean;
    rtsp_main_stream?: string | null;
    rtsp_sub_stream?: string | null;
    default_quality?: CameraQuality;
};

export function getAdminClassroomCameras(
    classroomId: number,
): Promise<AdminClassroomCamera[]> {
    return request<AdminClassroomCamera[]>(`/api/admin/classrooms/${classroomId}/cameras`);
}

export function createAdminClassroomCamera(
    classroomId: number,
    payload: AdminClassroomCameraCreateRequest,
): Promise<AdminClassroomCamera> {
    return request<AdminClassroomCamera>(`/api/admin/classrooms/${classroomId}/cameras`, {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export function updateAdminClassroomCamera(
    classroomId: number,
    cameraId: number,
    payload: AdminClassroomCameraUpdateRequest,
): Promise<AdminClassroomCamera> {
    return request<AdminClassroomCamera>(`/api/admin/classrooms/${classroomId}/cameras/${cameraId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
    });
}

export function deleteAdminClassroomCamera(classroomId: number, cameraId: number): Promise<undefined> {
    return request<undefined>(`/api/admin/classrooms/${classroomId}/cameras/${cameraId}`, {
        method: "DELETE",
    });
}

export type AdminRole = {
    id: number;
    name: string;
};

export type AdminUser = {
    id: number;
    username: string;
    display_name: string;
    role: string;
    is_active: boolean;
    classroom_ids: number[];
    created_at: string;
    updated_at: string;
    last_login_at: string | null;
};

export type AdminUserCreateRequest = {
    username: string;
    password: string;
    display_name: string;
    role: string;
    is_active: boolean;
    classroom_ids: number[];
};

export type AdminUserUpdateRequest = {
    username?: string;
    password?: string;
    display_name?: string;
    role?: string;
    is_active?: boolean;
};

export type AdminWorkstation = {
    id: number;
    name: string;
    ip_address: string;
    role: string;
    is_active: boolean;
    classroom_ids: number[];
    created_at: string;
    updated_at: string;
    last_seen_at: string | null;
};

export type AdminWorkstationCreateRequest = {
    name: string;
    ip_address: string;
    role: string;
    is_active: boolean;
    classroom_ids: number[];
};

export type AdminWorkstationUpdateRequest = {
    name?: string;
    ip_address?: string;
    role?: string;
    is_active?: boolean;
};

export function getAdminRoles(): Promise<AdminRole[]> {
    return request<AdminRole[]>("/api/admin/roles");
}

export function getAdminUsers(): Promise<AdminUser[]> {
    return request<AdminUser[]>("/api/admin/users");
}

export function createAdminUser(
    payload: AdminUserCreateRequest,
): Promise<AdminUser> {
    return request<AdminUser>("/api/admin/users", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export function updateAdminUser(
    userId: number,
    payload: AdminUserUpdateRequest,
): Promise<AdminUser> {
    return request<AdminUser>(`/api/admin/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
    });
}

export function updateAdminUserClassrooms(
    userId: number,
    classroomIds: number[],
): Promise<AdminUser> {
    return request<AdminUser>(`/api/admin/users/${userId}/classrooms`, {
        method: "POST",
        body: JSON.stringify({ classroom_ids: classroomIds }),
    });
}

export function getAdminWorkstations(): Promise<AdminWorkstation[]> {
    return request<AdminWorkstation[]>("/api/admin/workstations");
}

export function createAdminWorkstation(
    payload: AdminWorkstationCreateRequest,
): Promise<AdminWorkstation> {
    return request<AdminWorkstation>("/api/admin/workstations", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export function updateAdminWorkstation(
    workstationId: number,
    payload: AdminWorkstationUpdateRequest,
): Promise<AdminWorkstation> {
    return request<AdminWorkstation>(`/api/admin/workstations/${workstationId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
    });
}

export function updateAdminWorkstationClassrooms(
    workstationId: number,
    classroomIds: number[],
): Promise<AdminWorkstation> {
    return request<AdminWorkstation>(
        `/api/admin/workstations/${workstationId}/classrooms`,
        {
            method: "POST",
            body: JSON.stringify({ classroom_ids: classroomIds }),
        },
    );
}

export type AdminRouter = {
    id: number;
    name: string;
    api_host: string;
    api_port: number;
    api_use_ssl: boolean;
    api_verify_tls: boolean;
    api_username: string;
    is_enabled: boolean;
    poll_enabled: boolean;
    sync_enabled: boolean;
    poll_interval_seconds: number;
    created_at: string;
    updated_at: string;
};

export type AdminRouterCreateRequest = {
    name: string;
    api_host: string;
    api_port: number;
    api_use_ssl: boolean;
    api_verify_tls: boolean;
    api_username: string;
    api_password: string;
    is_enabled: boolean;
    poll_enabled: boolean;
    sync_enabled: boolean;
    poll_interval_seconds: number;
};

export type AdminRouterUpdateRequest = Partial<AdminRouterCreateRequest>;

export type AdminRouterServiceStatus = {
    id: number;
    router_id: number;
    service_name: string;
    worker_id: string | null;
    status: string;
    is_running: boolean;
    heartbeat_at: string | null;
    last_started_at: string | null;
    last_attempt_at: string | null;
    last_success_at: string | null;
    last_error_at: string | null;
    last_error: string | null;
    consecutive_failures: number;
    details: Record<string, unknown>;
    updated_at: string;
};

export type AdminRouterStatusItem = {
    router: AdminRouter;
    services: AdminRouterServiceStatus[];
};

export type AdminRouterTestConnectionResponse = {
    ok: boolean;
    router_id: number | null;
    base_url: string;
    checked_url: string;
    verify_tls: boolean;
    status_code: number | null;
    error: string | null;
    redirect_location: string | null;
    response_preview: string | null;
    resource: Record<string, unknown> | null;
    identity: Record<string, unknown> | null;
};

export type AdminRouterPollNowResponse = {
    ok: boolean;
    router_id: number;
    router_name: string;
    leases_count: number | null;
    snapshot_published: boolean | null;
    duration_ms: number | null;
    error: string | null;
    details: Record<string, unknown> | null;
};

export type AdminRouterSyncNowResponse = {
    ok: boolean;
    router_id: number;
    router_name: string;
    policy_generation: number | null;
    desired_count: number | null;
    added_count: number | null;
    removed_count: number | null;
    updated_count: number | null;
    connections_killed_count: number | null;
    duration_ms: number | null;
    error: string | null;
    details: Record<string, unknown> | null;
};

export type AdminRouterCapabilityResult = {
    name: string;
    label: string;
    ok: boolean;
    method: string;
    path: string;
    status_code: number | null;
    error: string | null;
    redirect_location: string | null;
    response_preview: string | null;
    item_count: number | null;
};

export type AdminRouterCapabilitiesResponse = {
    ok: boolean;
    router_id: number | null;
    base_url: string;
    verify_tls: boolean;
    capabilities: AdminRouterCapabilityResult[];
};

export function getAdminRouters(): Promise<AdminRouter[]> {
    return request<AdminRouter[]>("/api/admin/routers");
}

export function createAdminRouter(
    payload: AdminRouterCreateRequest,
): Promise<AdminRouter> {
    return request<AdminRouter>("/api/admin/routers", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}

export function updateAdminRouter(
    routerId: number,
    payload: AdminRouterUpdateRequest,
): Promise<AdminRouter> {
    return request<AdminRouter>(`/api/admin/routers/${routerId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
    });
}

export function getAdminRoutersStatus(): Promise<AdminRouterStatusItem[]> {
    return request<AdminRouterStatusItem[]>("/api/admin/routers/status");
}

export function getAdminRouterStatus(routerId: number): Promise<AdminRouterServiceStatus[]> {
    return request<AdminRouterServiceStatus[]>(`/api/admin/routers/${routerId}/status`);
}

export function testAdminRouterConnection(routerId: number): Promise<AdminRouterTestConnectionResponse> {
    return request<AdminRouterTestConnectionResponse>(`/api/admin/routers/${routerId}/test-connection`, {
        method: "POST",
    });
}

export function checkAdminRouterCapabilities(routerId: number): Promise<AdminRouterCapabilitiesResponse> {
    return request<AdminRouterCapabilitiesResponse>(`/api/admin/routers/${routerId}/check-capabilities`, {
        method: "POST",
    });
}

export function pollAdminRouterNow(routerId: number): Promise<AdminRouterPollNowResponse> {
    return request<AdminRouterPollNowResponse>(`/api/admin/routers/${routerId}/poll-now`, {
        method: "POST",
    });
}

export function syncAdminRouterNow(routerId: number): Promise<AdminRouterSyncNowResponse> {
    return request<AdminRouterSyncNowResponse>(`/api/admin/routers/${routerId}/sync-now`, {
        method: "POST",
    });
}

export type MaintenanceContainerStatus = {
    id: string;
    name: string;
    image: string;
    state: string;
    state_label: string;
    health: string | null;
    docker_status: string;
    cpu_percent: number | null;
    memory_usage_bytes: number | null;
    memory_limit_bytes: number | null;
    memory_percent: number | null;
    started_at: string | null;
};

export type MaintenanceContainersResponse = {
    containers: MaintenanceContainerStatus[];
};

export function getMaintenanceContainers(): Promise<MaintenanceContainersResponse> {
    return request<MaintenanceContainersResponse>("/api/admin/maintenance/containers");
}

export type MaintenanceContainerLogsResponse = {
    container_id: string;
    container_name: string | null;
    tail: number;
    logs: string;
};

export function getMaintenanceContainerLogs(
    containerId: string,
    tail: 100 | 1000 | 10000,
): Promise<MaintenanceContainerLogsResponse> {
    return request<MaintenanceContainerLogsResponse>(
        `/api/admin/maintenance/containers/${encodeURIComponent(containerId)}/logs?tail=${tail}`,
    );
}

export type MaintenanceDatabaseRestoreResponse = {
    restored: boolean;
    filename: string;
    size_bytes: number;
    databases: string[];
};

export async function downloadMaintenanceDatabaseBackup(): Promise<{ blob: Blob; filename: string | null }> {
    const token = getAccessToken();

    const response = await fetch(`${API_BASE_URL}/api/admin/maintenance/backups/database`, {
        method: "GET",
        headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
    });

    if (response.status === 401) {
        clearAccessToken();
    }

    if (!response.ok) {
        const message = await readErrorMessage(response);
        throw new Error(message || `HTTP ${response.status}`);
    }

    return {
        blob: await response.blob(),
        filename: extractFilenameFromContentDisposition(response.headers.get("Content-Disposition")),
    };
}

export async function uploadMaintenanceDatabaseBackup(
    file: File,
): Promise<MaintenanceDatabaseRestoreResponse> {
    const token = getAccessToken();
    const body = new FormData();
    body.append("file", file);

    const response = await fetch(`${API_BASE_URL}/api/admin/maintenance/backups/database`, {
        method: "POST",
        headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body,
    });

    if (response.status === 401) {
        clearAccessToken();
    }

    if (!response.ok) {
        const message = await readErrorMessage(response);
        throw new Error(message || `HTTP ${response.status}`);
    }

    const data: unknown = await response.json();
    return data as MaintenanceDatabaseRestoreResponse;
}

function extractFilenameFromContentDisposition(value: string | null): string | null {
    if (!value) {
        return null;
    }

    const encodedMatch = value.match(/filename\*=UTF-8''([^;]+)/i);
    if (encodedMatch?.[1]) {
        try {
            return decodeURIComponent(encodedMatch[1].trim());
        } catch {
            return encodedMatch[1].trim();
        }
    }

    const quotedMatch = value.match(/filename="([^"]+)"/i);
    if (quotedMatch?.[1]) {
        return quotedMatch[1].trim();
    }

    const plainMatch = value.match(/filename=([^;]+)/i);
    return plainMatch?.[1]?.trim() || null;
}
