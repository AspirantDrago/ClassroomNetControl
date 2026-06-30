using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Threading;

namespace CmncWanWidget;

public static class WindowMinimizeGuard
{
    private const int WM_SYSCOMMAND = 0x0112;
    private const int WM_SIZE = 0x0005;

    private const int SC_MINIMIZE = 0xF020;
    private const int SIZE_MINIMIZED = 1;

    private const int SW_SHOWNOACTIVATE = 4;
    private const int SW_RESTORE = 9;

    private static readonly IntPtr HWND_TOPMOST = new(-1);
    private static readonly IntPtr HWND_NOTOPMOST = new(-2);

    private const uint SWP_NOSIZE = 0x0001;
    private const uint SWP_NOMOVE = 0x0002;
    private const uint SWP_NOACTIVATE = 0x0010;
    private const uint SWP_SHOWWINDOW = 0x0040;

    private static readonly Dictionary<IntPtr, GuardState> States = new();

    public static void Attach(
        Window window,
        Func<bool> isMoveMode,
        Action sendToBottom
    )
    {
        var hwnd = new WindowInteropHelper(window).Handle;

        if (hwnd == IntPtr.Zero)
            return;

        var state = new GuardState();
        States[hwnd] = state;

        HwndSourceHook hook = (
            IntPtr windowHandle,
            int msg,
            IntPtr wParam,
            IntPtr lParam,
            ref bool handled
        ) =>
        {
            if (msg == WM_SYSCOMMAND)
            {
                var command = wParam.ToInt32() & 0xFFF0;

                if (command == SC_MINIMIZE)
                {
                    handled = true;
                    ForceVisibleOnDesktop(window, state);
                    return IntPtr.Zero;
                }
            }

            if (msg == WM_SIZE && wParam.ToInt32() == SIZE_MINIMIZED)
            {
                handled = true;
                ForceVisibleOnDesktop(window, state);
                return IntPtr.Zero;
            }

            return IntPtr.Zero;
        };

        var source = HwndSource.FromHwnd(hwnd);
        source?.AddHook(hook);

        window.StateChanged += (_, _) =>
        {
            if (window.WindowState == WindowState.Minimized)
                ForceVisibleOnDesktop(window, state);
        };

        var timer = new DispatcherTimer(DispatcherPriority.Send, window.Dispatcher)
        {
            Interval = TimeSpan.FromMilliseconds(150)
        };

        timer.Tick += (_, _) =>
        {
            var currentHwnd = new WindowInteropHelper(window).Handle;

            if (currentHwnd == IntPtr.Zero)
                return;

            var desktopIsForeground = IsDesktopOrTaskbarForeground();

            if (desktopIsForeground || IsIconic(currentHwnd) || window.WindowState == WindowState.Minimized)
            {
                ForceVisibleOnDesktop(window, state);
                return;
            }

            if (state.IsTemporarilyTopmost && !isMoveMode())
            {
                var foreground = GetForegroundWindow();

                if (foreground == currentHwnd)
                    return;

                if (foreground == IntPtr.Zero)
                    return;

                SetNotTopmost(currentHwnd);
                state.IsTemporarilyTopmost = false;
                sendToBottom();
            }
        };

        timer.Start();

        window.Closed += (_, _) =>
        {
            timer.Stop();
            source?.RemoveHook(hook);
            States.Remove(hwnd);
        };
    }

    private static void ForceVisibleOnDesktop(Window window, GuardState state)
    {
        window.Dispatcher.BeginInvoke(() =>
        {
            var hwnd = new WindowInteropHelper(window).Handle;

            if (hwnd == IntPtr.Zero)
                return;

            if (!window.IsVisible)
                window.Show();

            if (window.WindowState == WindowState.Minimized)
                window.WindowState = WindowState.Normal;

            ShowWindow(hwnd, SW_RESTORE);
            ShowWindow(hwnd, SW_SHOWNOACTIVATE);

            SetTopmost(hwnd);
            state.IsTemporarilyTopmost = true;
        }, DispatcherPriority.Send);
    }

    private static void SetTopmost(IntPtr hwnd)
    {
        SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        );
    }

    private static void SetNotTopmost(IntPtr hwnd)
    {
        SetWindowPos(
            hwnd,
            HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        );
    }

    private static bool IsDesktopOrTaskbarForeground()
    {
        var foreground = GetForegroundWindow();

        if (foreground == IntPtr.Zero)
            return false;

        var className = GetWindowClassName(foreground);

        return className is
            "Progman" or
            "WorkerW" or
            "Shell_TrayWnd" or
            "TrayNotifyWnd" or
            "TrayShowDesktopButtonWClass";
    }

    private static string GetWindowClassName(IntPtr hwnd)
    {
        var buffer = new StringBuilder(256);
        var length = GetClassName(hwnd, buffer, buffer.Capacity);

        return length > 0
            ? buffer.ToString()
            : string.Empty;
    }

    private sealed class GuardState
    {
        public bool IsTemporarilyTopmost { get; set; }
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetWindowPos(
        IntPtr hWnd,
        IntPtr hWndInsertAfter,
        int x,
        int y,
        int cx,
        int cy,
        uint flags
    );

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern int GetClassName(
        IntPtr hWnd,
        StringBuilder lpClassName,
        int nMaxCount
    );

    public static bool IsTemporarilyKeepingVisible(Window window)
    {
        var hwnd = new WindowInteropHelper(window).Handle;

        if (hwnd == IntPtr.Zero)
            return false;

        return States.TryGetValue(hwnd, out var state) && state.IsTemporarilyTopmost;
    }
}