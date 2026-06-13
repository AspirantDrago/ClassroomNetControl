export function parseRequiredString(value: string, fieldName: string): string {
    const trimmed = value.trim();

    if (!trimmed) {
        throw new Error(`${fieldName} не может быть пустым`);
    }

    return trimmed;
}

export function parseOptionalInteger(
    value: string,
    fieldName: string,
    options: {
        min?: number;
        max?: number;
    } = {},
): number | null {
    const trimmed = value.trim();

    if (!trimmed) {
        return null;
    }

    const parsed = Number(trimmed);

    if (!Number.isInteger(parsed)) {
        throw new Error(`${fieldName} должен быть целым числом`);
    }

    if (options.min !== undefined && parsed < options.min) {
        throw new Error(`${fieldName} должен быть не меньше ${options.min}`);
    }

    if (options.max !== undefined && parsed > options.max) {
        throw new Error(`${fieldName} должен быть не больше ${options.max}`);
    }

    return parsed;
}
