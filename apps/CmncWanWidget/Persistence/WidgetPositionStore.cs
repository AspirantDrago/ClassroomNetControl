using System;
using System.IO;
using System.Text.Json;
using System.Windows;

namespace CmncWanWidget;

public static class WidgetPositionStore
{
    private const string DirectoryName = "ClassroomNetControl";
    private const string AppDirectoryName = "CmncWanWidget";
    private const string FileName = "window-position.json";

    public static void Restore(Window window)
    {
        var position = TryReadPosition();

        if (position == null)
            return;

        var width = GetSafeSize(window.Width, window.ActualWidth, 380);
        var height = GetSafeSize(window.Height, window.ActualHeight, 230);

        window.Left = Clamp(
            position.Left,
            SystemParameters.VirtualScreenLeft,
            SystemParameters.VirtualScreenLeft + SystemParameters.VirtualScreenWidth - width
        );

        window.Top = Clamp(
            position.Top,
            SystemParameters.VirtualScreenTop,
            SystemParameters.VirtualScreenTop + SystemParameters.VirtualScreenHeight - height
        );
    }

    public static void Save(Window window)
    {
        var position = new WidgetPosition
        {
            Left = window.Left,
            Top = window.Top
        };

        var directory = GetStoreDirectory();
        Directory.CreateDirectory(directory);

        var json = JsonSerializer.Serialize(position, new JsonSerializerOptions
        {
            WriteIndented = true
        });

        File.WriteAllText(GetStorePath(), json);
    }

    private static WidgetPosition? TryReadPosition()
    {
        var path = GetStorePath();

        if (!File.Exists(path))
            return null;

        try
        {
            var json = File.ReadAllText(path);

            return JsonSerializer.Deserialize<WidgetPosition>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });
        }
        catch
        {
            return null;
        }
    }

    private static string GetStoreDirectory()
    {
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);

        return Path.Combine(appData, DirectoryName, AppDirectoryName);
    }

    private static string GetStorePath()
    {
        return Path.Combine(GetStoreDirectory(), FileName);
    }

    private static double GetSafeSize(double primary, double secondary, double fallback)
    {
        if (!double.IsNaN(primary) && primary > 0)
            return primary;

        if (!double.IsNaN(secondary) && secondary > 0)
            return secondary;

        return fallback;
    }

    private static double Clamp(double value, double min, double max)
    {
        if (max < min)
            return min;

        if (value < min)
            return min;

        if (value > max)
            return max;

        return value;
    }

    private sealed class WidgetPosition
    {
        public double Left { get; set; }
        public double Top { get; set; }
    }
}