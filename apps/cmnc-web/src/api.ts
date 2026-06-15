const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const ACCESS_TOKEN_STORAGE_KEY = "cmnc_access_token";

export type Classroom = {
    id: number;
    name: string;
    subnet_cidr: string;
    vlan_id: number | null;
    display_order: number;
    is_active: boolean;
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
    router_id: number;
    mac_address: string;
    active_ip: string | null;
    hostname: string | null;
    dynamic: boolean | null;
    active: boolean;
    last_seen_at: string | null;
    raw: Record<string, unknown>;
};

export type ClassroomDashboard = {
    classroom: Classroom;
    devices: DashboardDevice[];
    dynamic_devices: DynamicDevice[];
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

export type PinObservedDeviceRequest = {
    mac_address: string;
    inventory_name?: string | null;
    row_index?: number | null;
    column_index?: number | null;
    wan_protected?: boolean;
};

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
    subnet_cidr: string;
    vlan_id?: number | null;
    display_order?: number;
    is_active?: boolean;
};

export type ClassroomUpdateRequest = {
    name?: string;
    subnet_cidr?: string;
    vlan_id?: number | null;
    display_order?: number;
    is_active?: boolean;
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
