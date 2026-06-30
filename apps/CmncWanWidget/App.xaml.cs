using System.Threading;
using System.Windows;

namespace CmncWanWidget;

public partial class App
{
    private const string MutexName = @"Global\ClassroomNetControl.CmncWanWidget";

    private Mutex? _singleInstanceMutex;
    private bool _ownsMutex;

    protected override void OnStartup(StartupEventArgs e)
    {
        try
        {
            _singleInstanceMutex = new Mutex(
                initiallyOwned: true,
                name: MutexName,
                createdNew: out var createdNew
            );

            _ownsMutex = createdNew;

            if (!createdNew)
            {
                Shutdown(0);
                return;
            }
        }
        catch
        {
            Shutdown(1);
            return;
        }

        base.OnStartup(e);
    }

    protected override void OnExit(ExitEventArgs e)
    {
        if (_ownsMutex)
        {
            try
            {
                _singleInstanceMutex?.ReleaseMutex();
            }
            catch
            {
                // Игнорируем ошибку освобождения mutex при завершении приложения.
            }
        }

        _singleInstanceMutex?.Dispose();

        base.OnExit(e);
    }
}