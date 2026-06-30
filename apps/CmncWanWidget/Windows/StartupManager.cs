using Microsoft.Win32;
using System.Diagnostics;

namespace CmncWanWidget;

public static class StartupManager
{
    private const string RunRegistryPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string AppName = "CmncWanWidget";

    public static bool IsEnabled()
    {
        using var key = Registry.CurrentUser.OpenSubKey(RunRegistryPath, writable: false);

        var value = key?.GetValue(AppName) as string;

        if (string.IsNullOrWhiteSpace(value))
            return false;

        var currentExePath = GetCurrentExecutablePath();

        if (string.IsNullOrWhiteSpace(currentExePath))
            return false;

        return value.Contains(currentExePath, StringComparison.OrdinalIgnoreCase);
    }

    public static void Enable()
    {
        var currentExePath = GetCurrentExecutablePath();

        if (string.IsNullOrWhiteSpace(currentExePath))
            throw new InvalidOperationException("Не удалось определить путь к exe-файлу приложения.");

        using var key = Registry.CurrentUser.CreateSubKey(RunRegistryPath);

        key.SetValue(AppName, Quote(currentExePath));
    }

    public static void Disable()
    {
        using var key = Registry.CurrentUser.OpenSubKey(RunRegistryPath, writable: true);

        key?.DeleteValue(AppName, throwOnMissingValue: false);
    }

    public static void Toggle()
    {
        if (IsEnabled())
            Disable();
        else
            Enable();
    }

    private static string? GetCurrentExecutablePath()
    {
        if (!string.IsNullOrWhiteSpace(Environment.ProcessPath))
            return Environment.ProcessPath;

        return Process.GetCurrentProcess().MainModule?.FileName;
    }

    private static string Quote(string value)
    {
        return $"\"{value}\"";
    }
}