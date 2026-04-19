using Avalonia;
using System;
using System.Threading;

namespace gui;

class Program
{
    private static Mutex? _mutex;
    
    [STAThread]
    public static void Main(string[] args)
    {
        bool isNewInstance;

        _mutex = new Mutex(true, "HELL_APP_MUTEX", out isNewInstance);
        if (!isNewInstance)
        {
            // App already running → exit
            return;
        }

        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();
 }