import type {FormEvent} from "react";
import type {Classroom} from "../../api";
import "./ClassroomFormModal.css";

export type ClassroomFormState =
    | {
    mode: "create";
    classroom: null;
    name: string;
    subnetCidr: string;
    vlanId: string;
    displayOrder: string;
}
    | {
    mode: "edit";
    classroom: Classroom;
    name: string;
    subnetCidr: string;
    vlanId: string;
    displayOrder: string;
};

type ClassroomFormModalProps = {
    form: ClassroomFormState;
    busy: boolean;
    onChange: (form: ClassroomFormState) => void;
    onClose: () => void;
    onSubmit: (event: FormEvent<HTMLFormElement>) => void;
    onDeactivate?: () => void;
};

export function ClassroomFormModal(props: ClassroomFormModalProps) {
    const {form, busy, onChange, onClose, onSubmit, onDeactivate} = props;

    return (
        <div className="modal-backdrop" onMouseDown={onClose}>
            <form
                className="modal-card classroom-modal-card"
                onSubmit={onSubmit}
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
                                : "Можно изменить название, подсеть, VLAN и порядок отображения."}
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
        </div>
    );
}
