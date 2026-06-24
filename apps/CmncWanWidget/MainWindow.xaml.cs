using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;

namespace CmncWanWidget;

public partial class MainWindow
{
    private readonly AppConfig _config;
    private readonly ApiClient _api;
    private readonly DispatcherTimer _timer;

    private ClassroomInfo? _classroom;

    public MainWindow()
    {
        InitializeComponent();

        _config = LoadConfig();
        _api = new ApiClient(_config);

        _timer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(Math.Max(3, _config.RefreshSeconds))
        };

        _timer.Tick += async (_, _) => await RefreshStateAsync();

        Loaded += async (_, _) =>
        {
            await RefreshStateAsync();
            _timer.Start();
        };
    }

    private static AppConfig LoadConfig()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "appsettings.json");

        if (!File.Exists(path))
            throw new FileNotFoundException("Не найден appsettings.json.", path);

        var json = File.ReadAllText(path);

        return JsonSerializer.Deserialize<AppConfig>(json, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        }) ?? new AppConfig();
    }

    private async Task RefreshStateAsync()
    {
        SetBusy(true);

        try
        {
            _classroom = await _api.GetFirstClassroomAsync();

            if (_classroom == null || string.IsNullOrWhiteSpace(_classroom.Id))
            {
                SetState(WanWidgetState.NoAccess, "Аудитория: нет", "Нет доступа");
                return;
            }

            ClassroomText.Text = $"Аудитория: {_classroom.Name}";

            var devices = await _api.GetDevicesAsync(_classroom.Id);

            var targetDevices = devices
                .Where(x => x.IsStatic && !x.IsProtectedFromBlocking)
                .ToList();

            if (targetDevices.Count == 0)
            {
                SetState(WanWidgetState.NoAccess, $"Аудитория: {_classroom.Name}", "Нет доступных устройств для управления");
                return;
            }

            var enabledCount = targetDevices.Count(x => x.WanEnabled);
            var disabledCount = targetDevices.Count - enabledCount;

            if (enabledCount == targetDevices.Count)
            {
                SetState(WanWidgetState.AllWanEnabled, $"Аудитория: {_classroom.Name}", "У всех включен WAN");
            }
            else if (disabledCount == targetDevices.Count)
            {
                SetState(WanWidgetState.AllBlockableStaticWanDisabled, $"Аудитория: {_classroom.Name}", "У всех управляемых статических устройств WAN выключен");
            }
            else
            {
                SetState(WanWidgetState.Mixed, $"Аудитория: {_classroom.Name}", "WAN включен не у всех");
            }
        }
        catch
        {
            SetState(WanWidgetState.NoAccess, "Аудитория: недоступна", "Нет доступа");
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void SetState(WanWidgetState state, string classroomText, string statusText)
    {
        ClassroomText.Text = classroomText;
        StatusText.Text = statusText;

        StatusBorder.Background = state switch
        {
            WanWidgetState.NoAccess => new SolidColorBrush(Color.FromRgb(210, 210, 210)),
            WanWidgetState.AllWanEnabled => new SolidColorBrush(Color.FromRgb(210, 245, 210)),
            WanWidgetState.AllBlockableStaticWanDisabled => new SolidColorBrush(Color.FromRgb(255, 220, 220)),
            WanWidgetState.Mixed => new SolidColorBrush(Color.FromRgb(255, 240, 190)),
            _ => new SolidColorBrush(Color.FromRgb(230, 230, 230))
        };
    }

    private void SetBusy(bool isBusy)
    {
        BlockButton.IsEnabled = !isBusy && _classroom != null;
        UnblockButton.IsEnabled = !isBusy && _classroom != null;
    }

    private async void RefreshButton_Click(object sender, RoutedEventArgs e)
    {
        await RefreshStateAsync();
    }

    private async void BlockButton_Click(object sender, RoutedEventArgs e)
    {
        if (_classroom == null)
            return;

        SetBusy(true);

        try
        {
            await _api.BlockWanAsync(_classroom.Id);
            await RefreshStateAsync();
        }
        catch
        {
            SetState(WanWidgetState.NoAccess, "Аудитория: недоступна", "Ошибка выключения WAN");
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void UnblockButton_Click(object sender, RoutedEventArgs e)
    {
        if (_classroom == null)
            return;

        SetBusy(true);

        try
        {
            await _api.UnblockWanAsync(_classroom.Id);
            await RefreshStateAsync();
        }
        catch
        {
            SetState(WanWidgetState.NoAccess, "Аудитория: недоступна", "Ошибка включения WAN");
        }
        finally
        {
            SetBusy(false);
        }
    }
}
