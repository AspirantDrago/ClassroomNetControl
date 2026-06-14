import type { CurrentPrincipal } from "../api";

export const ROLE_WORKSTATION = "workstation";
export const ROLE_TEACHER = "teacher";
export const ROLE_MODERATOR = "moderator";
export const ROLE_ADMIN = "admin";
export const ROLE_SUPERADMIN = "superadmin";

export const PERMISSION_CLASSROOMS_READ_ALL = "classrooms:read:all";
export const PERMISSION_CLASSROOMS_READ_ASSIGNED = "classrooms:read:assigned";

export const PERMISSION_CLASSROOMS_MANAGE = "classrooms:manage";
export const PERMISSION_DEVICES_MANAGE = "devices:manage";

export const PERMISSION_WAN_CONTROL_ALL = "wan:control:all";
export const PERMISSION_WAN_CONTROL_ASSIGNED = "wan:control:assigned";

export const PERMISSION_USERS_MANAGE_ADMIN = "users:manage:admin";
export const PERMISSION_USERS_MANAGE_LOWER = "users:manage:lower";

export const PERMISSION_WORKSTATIONS_MANAGE = "workstations:manage";

export type AppPermission =
    | typeof PERMISSION_CLASSROOMS_READ_ALL
    | typeof PERMISSION_CLASSROOMS_READ_ASSIGNED
    | typeof PERMISSION_CLASSROOMS_MANAGE
    | typeof PERMISSION_DEVICES_MANAGE
    | typeof PERMISSION_WAN_CONTROL_ALL
    | typeof PERMISSION_WAN_CONTROL_ASSIGNED
    | typeof PERMISSION_USERS_MANAGE_ADMIN
    | typeof PERMISSION_USERS_MANAGE_LOWER
    | typeof PERMISSION_WORKSTATIONS_MANAGE;

export type AppRole =
    | typeof ROLE_WORKSTATION
    | typeof ROLE_TEACHER
    | typeof ROLE_MODERATOR
    | typeof ROLE_ADMIN
    | typeof ROLE_SUPERADMIN;

export function hasPermission(
    principal: CurrentPrincipal | null,
    permission: AppPermission,
): boolean {
    return principal?.permissions.includes(permission) ?? false;
}

export function hasAnyPermission(
    principal: CurrentPrincipal | null,
    permissions: AppPermission[],
): boolean {
    return permissions.some((permission) => hasPermission(principal, permission));
}

export function canManageClassrooms(principal: CurrentPrincipal | null): boolean {
    return hasPermission(principal, PERMISSION_CLASSROOMS_MANAGE);
}

export function canManageWorkstations(principal: CurrentPrincipal | null): boolean {
    return hasAnyPermission(principal, [
        PERMISSION_WORKSTATIONS_MANAGE,
        PERMISSION_DEVICES_MANAGE,
    ]);
}

export function canViewDynamicDevices(principal: CurrentPrincipal | null): boolean {
    return principal?.role === ROLE_SUPERADMIN || principal?.role === ROLE_ADMIN;
}

export function canControlWanForClassroom(
    principal: CurrentPrincipal | null,
    classroomId: number | null,
): boolean {
    if (hasPermission(principal, PERMISSION_WAN_CONTROL_ALL)) {
        return true;
    }

    if (
        classroomId !== null &&
        hasPermission(principal, PERMISSION_WAN_CONTROL_ASSIGNED)
    ) {
        return getAssignedClassroomIds(principal).includes(classroomId);
    }

    return false;
}

function getAssignedClassroomIds(principal: CurrentPrincipal | null): number[] {
    if (principal === null) {
        return [];
    }

    return principal.classroom_ids ?? principal.allowed_classroom_ids ?? [];
}
