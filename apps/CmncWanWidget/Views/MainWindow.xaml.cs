using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using System.ComponentModel;
using System.Windows.Input;

namespace CmncWanWidget;

public partial class MainWindow
{
    private readonly AppConfig _config;
    private readonly ApiClient _api;
    private readonly DispatcherTimer _timer;

    private ClassroomInfo? _classroom;
    private bool _isMoveMode;
    private bool _allowClose;
    private bool _busy;
    private WanWidgetState _state = WanWidgetState.NoAccess;

    public MainWindow()
    {
        InitializeComponent();

        WidgetPositionStore.Restore(this);

        Closing += MainWindow_Closing;

        SourceInitialized += (_, _) =>
        {
            DesktopWidgetHost.Attach(this);

            WindowMinimizeGuard.Attach(
                this,
                () => _isMoveMode,
                () => DesktopWidgetHost.SendToBottom(this)
            );
        };

        Loaded += async (_, _) =>
        {
            DesktopWidgetHost.SendToBottom(this);

            await RefreshStateAsync();
            _timer.Start();
        };

        Activated += (_, _) =>
        {
            if (!_isMoveMode)
                DesktopWidgetHost.SendToBottom(this);
        };

        _config = LoadConfig();
        _api = new ApiClient(_config);

        _timer = new DispatcherTimer
        {
            Interval = TimeSpan.FromSeconds(Math.Max(3, _config.RefreshSeconds))
        };

        _timer.Tick += async (_, _) => await RefreshStateAsync();
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
        _busy = true;

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
        catch (Exception ex)
        {
            SetState(
                WanWidgetState.NoAccess,
                "Аудитория: недоступна",
                $"Нет доступа: {ex.Message}"
            );
        }
        finally
        {
            _busy = false;
        }
    }

    private void SetState(WanWidgetState state, string classroomText, string statusText)
    {
        ClassroomText.Text = classroomText;
        StatusText.Text = statusText;
        _state = state;

        StatusBorder.Background = state switch
        {
            WanWidgetState.NoAccess => new SolidColorBrush(Color.FromRgb(210, 210, 210)),
            WanWidgetState.AllWanEnabled => new SolidColorBrush(Color.FromRgb(210, 245, 210)),
            WanWidgetState.AllBlockableStaticWanDisabled => new SolidColorBrush(Color.FromRgb(255, 220, 220)),
            WanWidgetState.Mixed => new SolidColorBrush(Color.FromRgb(255, 240, 190)),
            _ => new SolidColorBrush(Color.FromRgb(230, 230, 230))
        };
    }

    private async void Toggle_Click()
    {
        if (_classroom == null)
            return;
        if (_busy)
            return;
        if (_state == WanWidgetState.NoAccess)
        {
            await RefreshStateAsync();
            return;
        }
        _busy = true;
        bool target_wan_block = _state switch
        {
            WanWidgetState.AllWanEnabled => true,
            WanWidgetState.AllBlockableStaticWanDisabled => false,
            WanWidgetState.Mixed => false
        };

        try
        {
            if (target_wan_block)
                await _api.BlockWanAsync(_classroom.Id);
            else
                await _api.UnblockWanAsync(_classroom.Id);
            await RefreshStateAsync();
        }
        catch
        {
            SetState(WanWidgetState.NoAccess, "Аудитория: недоступна",
                target_wan_block ? "Ошибка включения WAN" : "Ошибка выключения WAN");
        }
        finally
        {
            _busy = false;
        }
    }

    private async void RefreshMenuItem_Click(object sender, RoutedEventArgs e)
    {
        await RefreshStateAsync();
    }

    private void MoveLockMenuItem_Click(object sender, RoutedEventArgs e)
    {
        SetMoveMode(!_isMoveMode);
    }

    private void CloseMenuItem_Click(object sender, RoutedEventArgs e)
    {
        ConfirmAndClose();
    }

    private void RootBorder_PreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (!_isMoveMode)
        {
            Toggle_Click();
            return;
        }
        
        if (e.LeftButton != MouseButtonState.Pressed)
            return;

        try
        {
            DragMove();
            e.Handled = true;
        }
        catch (InvalidOperationException)
        {
            // DragMove может упасть, если кнопка мыши уже отпущена.
        }
    }

    private void SetMoveMode(bool enabled)
    {
        _isMoveMode = enabled;

        MoveLockMenuItem.Header = enabled
            ? "Зафиксировать"
            : "Переместить";

        Cursor = enabled
            ? Cursors.SizeAll
            : null;

        if (!enabled)
        {
            WidgetPositionStore.Save(this);
            DesktopWidgetHost.SendToBottom(this);
        }
    }

    private void ConfirmAndClose()
    {
        var result = MessageBox.Show(
            this,
            "Закрыть виджет управления WAN?",
            "Подтверждение",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question,
            MessageBoxResult.No
        );

        if (result != MessageBoxResult.Yes)
            return;

        _allowClose = true;
        _timer.Stop();
        Close();
    }

    private void MainWindow_Closing(object? sender, CancelEventArgs e)
    {
        if (_allowClose)
            return;

        e.Cancel = true;
        ConfirmAndClose();
    }
}
