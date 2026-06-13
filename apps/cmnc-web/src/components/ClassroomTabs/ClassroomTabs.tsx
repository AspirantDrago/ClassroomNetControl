import type { Classroom } from "../../api";
import "./ClassroomTabs.css";

type ClassroomTabsProps = {
    classrooms: Classroom[];
    selectedClassroomId: number | null;
    onSelect: (classroomId: number) => void;
};

export function ClassroomTabs(props: ClassroomTabsProps) {
    const { classrooms, selectedClassroomId, onSelect } = props;

    return (
        <section className="classroom-tabs">
            {classrooms.map((classroom) => (
                <button
                    key={classroom.id}
                    className={classroom.id === selectedClassroomId ? "tab active-tab" : "tab"}
                    onClick={() => onSelect(classroom.id)}
                >
                    {classroom.name}
                </button>
            ))}
        </section>
    );
}
