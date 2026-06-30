using System.Text.Json;

namespace CmncWanWidget;

public static class JsonHelpers
{
    public static JsonElement[] ExtractArray(JsonElement root, params string[] possiblePropertyNames)
    {
        if (root.ValueKind == JsonValueKind.Array)
            return root.EnumerateArray().ToArray();

        if (root.ValueKind != JsonValueKind.Object)
            return [];

        foreach (var name in possiblePropertyNames)
        {
            if (root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Array)
                return value.EnumerateArray().ToArray();
        }

        return [];
    }

    public static string GetString(JsonElement element, params string[] names)
    {
        foreach (var name in names)
        {
            if (!element.TryGetProperty(name, out var value))
                continue;

            if (value.ValueKind == JsonValueKind.String)
                return value.GetString() ?? "";

            if (value.ValueKind == JsonValueKind.Number)
                return value.ToString();
        }

        return "";
    }

    public static bool GetBool(JsonElement element, bool defaultValue, params string[] names)
    {
        foreach (var name in names)
        {
            if (!element.TryGetProperty(name, out var value))
                continue;

            if (value.ValueKind == JsonValueKind.True)
                return true;

            if (value.ValueKind == JsonValueKind.False)
                return false;

            if (value.ValueKind == JsonValueKind.String)
            {
                var text = value.GetString()?.Trim().ToLowerInvariant();

                if (text is "true" or "1" or "yes" or "enabled" or "on")
                    return true;

                if (text is "false" or "0" or "no" or "disabled" or "off")
                    return false;
            }

            if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number))
                return number != 0;
        }

        return defaultValue;
    }
}
