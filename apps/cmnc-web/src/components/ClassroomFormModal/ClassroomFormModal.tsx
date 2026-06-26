import type { FormEvent } from "react";
import type { AdminRouter, Classroom } from "../../api";
import { ClassroomCamerasAdminPanel } from "../ClassroomCamerasAdminPanel/ClassroomCamerasAdminPanel";
import "./ClassroomFormModal.css";

export type ClassroomFormState =
    | {
          mode: "create";
          classroom: null;
          routerId: string;
          name: string;
          subnetCidr: string;
          vlanId: string;
          displayOrder: string;
          isService: boolean;
      }
    | {
          mode: "edit";
          classroom: Classroom;
          routerId: string;
          name: string;
          subnetCidr: string;
          vlanId: string;
          displayOrder: string;
          isService: boolean;
      };

type ClassroomFormModalProps = {
    form: ClassroomFormState;
    routers: AdminRouter[];
    busy: boolean;
    onChange: (form: ClassroomFormState) => void;
    onClose: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
    onDeactivate?: () => void;
    onCamerasChanged?: () => void | Promise<void>;
};

export function ClassroomFormModal(props: ClassroomFormModalProps) {
    const {
        form,
        routers,
        busy,
        onChange,
        onClose,
        onSubmit,
        onDeactivate,
        onCamerasChanged,
    } = props;

    const selectedRouterId = Number(form.routerId);
    const hasSelectedRouterInList = routers.some(
        (router) => router.id === selectedRouterId,
    );

    return (
        <div className="modal-backdrop" onMouseDown={onClose}>
            <div
                className="modal-card classroom-modal-card"
                onMouseDown={(event) => event.stopPropagation()}
            >
                <div className="modal-header">
                    <div>
                        <h3>
                            {form.mode === "create"
                                ? "Новая аудитория"
                                : "Редактировать аудиторию"}
                        </h3>
                        <div className="muted">
                            {form.mode === "create"
                                ? "Аудитория появится в списке вкладок."
                                : "Можно изменить название, подсеть, VLAN, MikroTik, порядок отображения, служебный статус и камеры."}
                        </div>
                    </div>

                    <button
                        type="button"
                        className="modal-close-button"
                        onClick={onClose}
                    >
                        ×
                    </button>
                </div>

                <form className="classroom-form-section" onSubmit={onSubmit}>
                    <div className="classroom-form-grid">
                        <label>
                            Название
                            <input
                                value={form.name}
                                onChange={(event) =>
                                    onChange({
                                        ...form,
                                        name: event.target.value,
                                    })
                                }
                                placeholder="Аудитория 1"
                            />
                        </label>

                        <label>
                            Подсеть
                            <input
                                value={form.subnetCidr}
                                onChange={(event) =>
                                    onChange({
                                        ...form,
                                        subnetCidr: event.target.value,
                                    })
                                }
                                placeholder="192.168.100.0/24"
                            />
                        </label>

                        <label>
                            MikroTik
                            <select
                                value={form.routerId}
                                onChange={(event) =>
                                    onChange({
                                        ...form,
                                        routerId: event.target.value,
                                    })
                                }
                            >
                                {!form.routerId && (
                                    <option value="">
                                        Выберите MikroTik
                                    </option>
                                )}

                                {form.routerId && !hasSelectedRouterInList && (
                                    <option value={form.routerId}>
                                        MikroTik #{form.routerId}
                                    </option>
                                )}

                                {routers.map((router) => (
                                    <option key={router.id} value={router.id}>
                                        {router.name} #{router.id}
                                        {router.is_enabled ? "" : " - отключён"}
                                    </option>
                                ))}
                            </select>
                        </label>

                        <label>
                            VLAN
                            <input
                                type="number"
                                min="1"
                                max="4094"
                                value={form.vlanId}
                                onChange={(event) =>
                                    onChange({
                                        ...form,
                                        vlanId: event.target.value,
                                    })
                                }
                                placeholder="100"
                            />
                        </label>

                        <label>
                            Порядок
                            <input
                                type="number"
                                min="0"
                                value={form.displayOrder}
                                onChange={(event) =>
                                    onChange({
                                        ...form,
                                        displayOrder: event.target.value,
                                    })
                                }
                                placeholder="10"
                            />
                        </label>
                    </div>

                    <label className="classroom-service-checkbox">
                        <input
                            type="checkbox"
                            checked={form.isService}
                            onChange={(event) =>
                                onChange({
                                    ...form,
                                    isService: event.target.checked,
                                })
                            }
                        />
                        <span>Служебная аудитория</span>
                    </label>

                    <div className="modal-actions classroom-modal-actions">
                        {form.mode === "edit" && onDeactivate && (
                            <button
                                type="button"
                                className="danger-button"
                                disabled={busy}
                                onClick={onDeactivate}
                            >
                                Деактивировать
                            </button>
                        )}

                        <button
                            type="button"
                            className="secondary-button"
                            disabled={busy}
                            onClick={onClose}
                        >
                            Отмена
                        </button>

                        <button
                            type="submit"
                            className="primary-button"
                            disabled={busy}
                        >
                            {form.mode === "create" ? "Создать" : "Сохранить"}
                        </button>
                    </div>
                </form>

                {form.mode === "edit" && onCamerasChanged && (
                    <ClassroomCamerasAdminPanel
                        classroomId={form.classroom.id}
                        onChanged={onCamerasChanged}
                    />
                )}
            </div>
        </div>
    );
}
