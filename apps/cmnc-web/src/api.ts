const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  const data: unknown = await response.json();
  return data as T;
}

export function getClassrooms(): Promise<Classroom[]> {
    return request<Classroom[]>("/api/classrooms");
}

export function getClassroomDashboard(classroomId: number): Promise<ClassroomDashboard> {
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

export type PinObservedDeviceRequest = {
    mac_address: string;
    inventory_name?: string | null;
    row_index?: number | null;
    column_index?: number | null;
};

export function pinObservedDevice(
    classroomId: number,
    payload: PinObservedDeviceRequest,
): Promise<DashboardDevice> {
    return request<DashboardDevice>(
        `/api/admin/classrooms/${classroomId}/devices/pin-observed`,
        {
            method: "POST",
            body: JSON.stringify(payload),
        },
    );
}
