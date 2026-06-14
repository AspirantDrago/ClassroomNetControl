import { type FormEvent, useEffect, useMemo, useState } from "react";
import {
    type AdminRole,
    type AdminUser,
    type AdminWorkstation,
    type Classroom,
    type CurrentPrincipal,
    createAdminUser,
    createAdminWorkstation,
    extractErrorDetail,
    getAdminRoles,
    getAdminUsers,
    getAdminWorkstations,
    updateAdminUser,
    updateAdminUserClassrooms,
    updateAdminWorkstation,
    updateAdminWorkstationClassrooms,
} from "../../api";
import {
    ROLE_TEACHER,
    ROLE_WORKSTATION,
    canManageUsers,
    canManageWorkstations,
    getManageableUserRoles,
} from "../../auth/permissions";
import "./AdminAccessPage.css";

type AdminAccessPageProps = {
    principal: CurrentPrincipal;
    classrooms: Classroom[];
};

type PageTab = "users" | "workstations";

type UserFormState = {
    mode: "create" | "edit";
    user: AdminUser | null;
    username: string;
    password: string;
    displayName: string;
    role: string;
    isActive: boolean;
    classroomIds: number[];
};

type WorkstationFormState = {
    mode: "create" | "edit";
    workstation: AdminWorkstation | null;
    name: string;
    ipAddress: string;
    isActive: boolean;
    classroomIds: number[];
};

export function AdminAccessPage(props: AdminAccessPageProps) {
    const { principal, classrooms } = props;

    const userManagementAllowed = canManageUsers(principal);
    const workstationManagementAllowed = canManageWorkstations(principal);

    const initialTab: PageTab = userManagementAllowed ? "users" : "workstations";

    const [activeTab, setActiveTab] = useState<PageTab>(initialTab);
    const [roles, setRoles] = useState<AdminRole[]>([]);
    const [users, setUsers] = useState<AdminUser[]>([]);
    const [workstations, setWorkstations] = useState<AdminWorkstation[]>([]);
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [userForm, setUserForm] = useState<UserFormState | null>(null);
    const [workstationForm, setWorkstationForm] =
        useState<WorkstationFormState | null>(null);

    const manageableUserRoles = useMemo(() => {
        const allowedRoles = new Set(getManageableUserRoles(principal));
        const existingRoles = roles.map((role) => role.name);
        const filteredExistingRoles = existingRoles.filter((role) =>
            allowedRoles.has(role),
        );

        if (filteredExistingRoles.length > 0) {
            return filteredExistingRoles;
        }

        return [...allowedRoles];
    }, [principal, roles]);

    useEffect(() => {
        void reload();
    }, []);

    async function reload() {
        setLoading(true);
        setError(null);

        try {
            const [loadedRoles, loadedUsers, loadedWorkstations] = await Promise.all([
                getAdminRoles(),
                userManagementAllowed ? getAdminUsers() : Promise.resolve([]),
                workstationManagementAllowed
                    ? getAdminWorkstations()
                    : Promise.resolve([]),
            ]);

            setRoles(loadedRoles);
            setUsers(loadedUsers);
            setWorkstations(loadedWorkstations);
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setLoading(false);
        }
    }

    function openCreateUserForm() {
        const defaultRole = manageableUserRoles[0] ?? "teacher";

        setError(null);
        setUserForm({
            mode: "create",
            user: null,
            username: "",
            password: "",
            displayName: "",
            role: defaultRole,
            isActive: true,
            classroomIds: [],
        });
    }

    function openEditUserForm(user: AdminUser) {
        setError(null);
        setUserForm({
            mode: "edit",
            user,
            username: user.username,
            password: "",
            displayName: user.display_name,
            role: user.role,
            isActive: user.is_active,
            classroomIds: user.classroom_ids,
        });
    }

    function openCreateWorkstationForm() {
        setError(null);
        setWorkstationForm({
            mode: "create",
            workstation: null,
            name: "",
            ipAddress: "",
            isActive: true,
            classroomIds: [],
        });
    }

    function openEditWorkstationForm(workstation: AdminWorkstation) {
        setError(null);
        setWorkstationForm({
            mode: "edit",
            workstation,
            name: workstation.name,
            ipAddress: workstation.ip_address,
            isActive: workstation.is_active,
            classroomIds: workstation.classroom_ids,
        });
    }

    async function handleUserSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (userForm === null) {
            return;
        }

        const username = userForm.username.trim();
        const password = userForm.password.trim();
        const displayName = userForm.displayName.trim();
        const role = userForm.role.trim();
        const classroomIds = role === ROLE_TEACHER ? userForm.classroomIds : [];

        if (!username || !displayName || !role) {
            setError("Заполните username, отображаемое имя и роль.");
            return;
        }

        if (userForm.mode === "create" && !password) {
            setError("Для нового пользователя нужен пароль.");
            return;
        }

        setBusy(true);
        setError(null);

        try {
            if (userForm.mode === "create") {
                await createAdminUser({
                    username,
                    password,
                    display_name: displayName,
                    role,
                    is_active: userForm.isActive,
                    classroom_ids: classroomIds,
                });
            } else if (userForm.user !== null) {
                const payload = {
                    username,
                    display_name: displayName,
                    role,
                    is_active: userForm.isActive,
                    ...(password ? { password } : {}),
                };

                await updateAdminUser(userForm.user.id, payload);
                await updateAdminUserClassrooms(
                    userForm.user.id,
                    classroomIds,
                );
            }

            setUserForm(null);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusy(false);
        }
    }

    async function handleWorkstationSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        if (workstationForm === null) {
            return;
        }

        const name = workstationForm.name.trim();
        const ipAddress = workstationForm.ipAddress.trim();

        if (!name || !ipAddress) {
            setError("Заполните название рабочей станции и IP-адрес.");
            return;
        }

        setBusy(true);
        setError(null);

        try {
            if (workstationForm.mode === "create") {
                await createAdminWorkstation({
                    name,
                    ip_address: ipAddress,
                    role: ROLE_WORKSTATION,
                    is_active: workstationForm.isActive,
                    classroom_ids: workstationForm.classroomIds,
                });
            } else if (workstationForm.workstation !== null) {
                await updateAdminWorkstation(workstationForm.workstation.id, {
                    name,
                    ip_address: ipAddress,
                    role: ROLE_WORKSTATION,
                    is_active: workstationForm.isActive,
                });
                await updateAdminWorkstationClassrooms(
                    workstationForm.workstation.id,
                    workstationForm.classroomIds,
                );
            }

            setWorkstationForm(null);
            await reload();
        } catch (err) {
            setError(extractErrorDetail(err));
        } finally {
            setBusy(false);
        }
    }

    return (
        <section className="admin-access-page">
            <div className="admin-access-header">
                <div>
                    <h2>Пользователи и рабочие станции</h2>
                    <p className="muted">
                        Управление ролями, доступом к аудиториям и автоматической
                        авторизацией по IP.
                    </p>
                </div>

                <button
                    className="secondary-button"
                    disabled={loading || busy}
                    onClick={reload}
                >
                    Обновить
                </button>
            </div>

            <div className="admin-access-tabs">
                {userManagementAllowed && (
                    <button
                        className={activeTab === "users" ? "tab active-tab" : "tab"}
                        onClick={() => setActiveTab("users")}
                    >
                        Пользователи
                    </button>
                )}

                {workstationManagementAllowed && (
                    <button
                        className={
                            activeTab === "workstations" ? "tab active-tab" : "tab"
                        }
                        onClick={() => setActiveTab("workstations")}
                    >
                        Рабочие станции
                    </button>
                )}
            </div>

            {error && <pre className="error-box">{error}</pre>}
            {loading && <div className="loading">Загрузка...</div>}

            {activeTab === "users" && userManagementAllowed && (
                <div className="admin-card">
                    <div className="admin-card-header">
                        <h3>Пользователи</h3>
                        <button
                            className="primary-button"
                            disabled={busy || manageableUserRoles.length === 0}
                            onClick={openCreateUserForm}
                        >
                            Новый пользователь
                        </button>
                    </div>

                    {userForm && (
                        <UserForm
                            form={userForm}
                            roles={manageableUserRoles}
                            classrooms={classrooms}
                            busy={busy}
                            onChange={setUserForm}
                            onCancel={() => setUserForm(null)}
                            onSubmit={handleUserSubmit}
                        />
                    )}

                    <UsersTable
                        users={users}
                        classrooms={classrooms}
                        onEdit={openEditUserForm}
                    />
                </div>
            )}

            {activeTab === "workstations" && workstationManagementAllowed && (
                <div className="admin-card">
                    <div className="admin-card-header">
                        <h3>Рабочие станции</h3>
                        <button
                            className="primary-button"
                            disabled={busy}
                            onClick={openCreateWorkstationForm}
                        >
                            Новая рабочая станция
                        </button>
                    </div>

                    {workstationForm && (
                        <WorkstationForm
                            form={workstationForm}
                            classrooms={classrooms}
                            busy={busy}
                            onChange={setWorkstationForm}
                            onCancel={() => setWorkstationForm(null)}
                            onSubmit={handleWorkstationSubmit}
                        />
                    )}

                    <WorkstationsTable
                        workstations={workstations}
                        classrooms={classrooms}
                        onEdit={openEditWorkstationForm}
                    />
                </div>
            )}
        </section>
    );
}

type UserFormProps = {
    form: UserFormState;
    roles: string[];
    classrooms: Classroom[];
    busy: boolean;
    onChange: (form: UserFormState) => void;
    onCancel: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

function UserForm(props: UserFormProps) {
    const { form, roles, classrooms, busy, onChange, onCancel, onSubmit } = props;

    return (
        <form className="admin-form" onSubmit={onSubmit}>
            <div className="admin-form-grid">
                <label>
                    Username
                    <input
                        value={form.username}
                        onChange={(event) =>
                            onChange({ ...form, username: event.target.value })
                        }
                        placeholder="user"
                    />
                </label>

                <label>
                    <div>
                        Пароль {form.mode === "edit" && <span className="muted">(не менять - оставить пустым)</span>}
                    </div>
                    <input
                        type="password"
                        value={form.password}
                        onChange={(event) =>
                            onChange({ ...form, password: event.target.value })
                        }
                        placeholder="пароль"
                    />
                </label>

                <label>
                    Отображаемое имя
                    <input
                        value={form.displayName}
                        onChange={(event) =>
                            onChange({ ...form, displayName: event.target.value })
                        }
                        placeholder="Имя Фамилия"
                    />
                </label>

                <label>
                    Роль
                    <select
                        value={form.role}
                        onChange={(event) => {
                            const nextRole = event.target.value;

                            onChange({
                                ...form,
                                role: nextRole,
                                classroomIds:
                                    nextRole === ROLE_TEACHER ? form.classroomIds : [],
                            });
                        }}
                    >
                        {roles.map((role) => (
                            <option key={role} value={role}>
                                {formatRole(role)}
                            </option>
                        ))}
                    </select>
                </label>
            </div>
            <div>
                <label className="admin-checkbox-row">
                    <input
                        type="checkbox"
                        checked={form.isActive}
                        onChange={(event) =>
                            onChange({ ...form, isActive: event.target.checked })
                        }
                    />
                    Активен
                </label>
            </div>

            {form.role === ROLE_TEACHER && (
                <ClassroomChecklist
                    classrooms={classrooms}
                    selectedIds={form.classroomIds}
                    onChange={(classroomIds) => onChange({ ...form, classroomIds })}
                />
            )}

            <div className="admin-form-actions">
                <button className="primary-button" disabled={busy} type="submit">
                    Сохранить
                </button>
                <button
                    className="secondary-button"
                    disabled={busy}
                    type="button"
                    onClick={onCancel}
                >
                    Отмена
                </button>
            </div>
        </form>
    );
}

type WorkstationFormProps = {
    form: WorkstationFormState;
    classrooms: Classroom[];
    busy: boolean;
    onChange: (form: WorkstationFormState) => void;
    onCancel: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

function WorkstationForm(props: WorkstationFormProps) {
    const { form, classrooms, busy, onChange, onCancel, onSubmit } = props;

    return (
        <form className="admin-form" onSubmit={onSubmit}>
            <div className="admin-form-grid">
                <label>
                    Название
                    <input
                        value={form.name}
                        onChange={(event) =>
                            onChange({ ...form, name: event.target.value })
                        }
                        placeholder="Workstation name"
                    />
                </label>

                <label>
                    IP-адрес
                    <input
                        value={form.ipAddress}
                        onChange={(event) =>
                            onChange({ ...form, ipAddress: event.target.value })
                        }
                        placeholder="192.168.0.1"
                    />
                </label>
            </div>

            <div>
                <label className="admin-checkbox-row">
                    <input
                        type="checkbox"
                        checked={form.isActive}
                        onChange={(event) =>
                            onChange({ ...form, isActive: event.target.checked })
                        }
                    />
                    Активна
                </label>
            </div>

            <ClassroomChecklist
                classrooms={classrooms}
                selectedIds={form.classroomIds}
                onChange={(classroomIds) => onChange({ ...form, classroomIds })}
            />

            <div className="admin-form-actions">
                <button className="primary-button" disabled={busy} type="submit">
                    Сохранить
                </button>
                <button
                    className="secondary-button"
                    disabled={busy}
                    type="button"
                    onClick={onCancel}
                >
                    Отмена
                </button>
            </div>
        </form>
    );
}

type ClassroomChecklistProps = {
    classrooms: Classroom[];
    selectedIds: number[];
    onChange: (classroomIds: number[]) => void;
};

function ClassroomChecklist(props: ClassroomChecklistProps) {
    const { classrooms, selectedIds, onChange } = props;
    const selectedSet = new Set(selectedIds);

    function toggle(classroomId: number, checked: boolean) {
        const next = new Set(selectedIds);

        if (checked) {
            next.add(classroomId);
        } else {
            next.delete(classroomId);
        }

        onChange([...next].sort((left, right) => left - right));
    }

    return (
        <div className="classroom-checklist">
            <div className="classroom-checklist-title">Назначенные аудитории</div>

            {classrooms.length === 0 ? (
                <div className="muted">Нет доступных аудиторий.</div>
            ) : (
                <div className="classroom-checklist-grid">
                    {classrooms.map((classroom) => (
                        <label key={classroom.id}>
                            <input
                                type="checkbox"
                                checked={selectedSet.has(classroom.id)}
                                onChange={(event) =>
                                    toggle(classroom.id, event.target.checked)
                                }
                            />
                            {classroom.name}
                        </label>
                    ))}
                </div>
            )}
        </div>
    );
}

type UsersTableProps = {
    users: AdminUser[];
    classrooms: Classroom[];
    onEdit: (user: AdminUser) => void;
};

function UsersTable(props: UsersTableProps) {
    const { users, classrooms, onEdit } = props;

    if (users.length === 0) {
        return <div className="muted">Пользователи не найдены.</div>;
    }

    return (
        <div className="admin-table-wrapper">
            <table>
                <thead>
                <tr>
                    <th>Username</th>
                    <th>Имя</th>
                    <th>Роль</th>
                    <th>Активен</th>
                    <th>Аудитории</th>
                    <th>Last login</th>
                    <th>Действие</th>
                </tr>
                </thead>
                <tbody>
                {users.map((user) => (
                    <tr key={user.id} className={user.is_active ? "user-item__active" : "user-item__disabled"}>
                        <td>{user.username}</td>
                        <td>{user.display_name}</td>
                        <td>{formatRole(user.role)}</td>
                        <td>{user.is_active ? "да" : "нет"}</td>
                        <td>{formatUserClassrooms(user, classrooms)}</td>
                        <td>{formatDate(user.last_login_at)}</td>
                        <td>
                            <button
                                className="secondary-button compact-button"
                                onClick={() => onEdit(user)}
                            >
                                Изменить
                            </button>
                        </td>
                    </tr>
                ))}
                </tbody>
            </table>
        </div>
    );
}

type WorkstationsTableProps = {
    workstations: AdminWorkstation[];
    classrooms: Classroom[];
    onEdit: (workstation: AdminWorkstation) => void;
};

function WorkstationsTable(props: WorkstationsTableProps) {
    const { workstations, classrooms, onEdit } = props;

    if (workstations.length === 0) {
        return <div className="muted">Рабочие станции не найдены.</div>;
    }

    return (
        <div className="admin-table-wrapper">
            <table>
                <thead>
                <tr>
                    <th>Название</th>
                    <th>IP</th>
                    <th>Активна</th>
                    <th>Аудитории</th>
                    <th>Last seen</th>
                    <th>Действие</th>
                </tr>
                </thead>
                <tbody>
                {workstations.map((workstation) => (
                    <tr key={workstation.id} className={workstation.is_active ? "user-item__active" : "user-item__disabled"}>
                        <td>{workstation.name}</td>
                        <td>{workstation.ip_address}</td>
                        <td>{workstation.is_active ? "да" : "нет"}</td>
                        <td>{formatClassrooms(workstation.classroom_ids, classrooms)}</td>
                        <td>{formatDate(workstation.last_seen_at)}</td>
                        <td>
                            <button
                                className="secondary-button compact-button"
                                onClick={() => onEdit(workstation)}
                            >
                                Изменить
                            </button>
                        </td>
                    </tr>
                ))}
                </tbody>
            </table>
        </div>
    );
}

function formatUserClassrooms(user: AdminUser, classrooms: Classroom[]): string {
    if (user.role !== ROLE_TEACHER) {
        return "-";
    }

    return formatClassrooms(user.classroom_ids, classrooms);
}

function formatClassrooms(classroomIds: number[], classrooms: Classroom[]): string {
    if (classroomIds.length === 0) {
        return "-";
    }

    const classroomNamesById = new Map(
        classrooms.map((classroom) => [classroom.id, classroom.name]),
    );

    return classroomIds
        .map((classroomId) => classroomNamesById.get(classroomId) ?? `#${classroomId}`)
        .join(", ");
}

function formatDate(value: string | null): string {
    if (!value) {
        return "-";
    }

    return new Date(value).toLocaleString().replace(",", "");
}

function formatRole(role: string): string {
    const labels: Record<string, string> = {
        superadmin: "superadmin",
        admin: "admin",
        moderator: "moderator",
        teacher: "teacher",
        workstation: "workstation",
    };

    return labels[role] ?? role;
}
