using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using gui.ViewModels;
using gui.Views;
using System;

namespace gui;

public partial class App : Application
{
    private MainWindowViewModel? _viewModel;
    private TrayIcon? _trayIcon;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            // 🔹 Single ViewModel for entire app
            _viewModel = new MainWindowViewModel();

            // 🔹 Always start with StartupWindow
            desktop.MainWindow = new StartupWindow(_viewModel);

            // 🔹 Initialize tray
            InitializeTray(desktop);
        }

        base.OnFrameworkInitializationCompleted();
    }

    private void InitializeTray(IClassicDesktopStyleApplicationLifetime desktop)
    {
        _trayIcon = new TrayIcon
        {
            ToolTipText = "HELL",
            Icon = new WindowIcon(
                AssetLoader.Open(
                    new Uri("avares://gui/Assets/avalonia-logo.ico")
                )
            ),
            Menu = BuildTrayMenu(),
        };

        _trayIcon.Clicked += (_, _) =>
        {
            if (desktop.MainWindow is Window window)
            {
                window.Show();
                window.ShowInTaskbar = true;
                window.WindowState = WindowState.Normal;
                window.Activate();
            }
        };

        desktop.Exit += (_, _) => _trayIcon?.Dispose();
    }

    private NativeMenu BuildTrayMenu()
    {
        var menu = new NativeMenu();

        menu.Add(new NativeMenuItem { Header = "HELL v0.1", IsEnabled = false });
        menu.Add(new NativeMenuItemSeparator());

        menu.Add(new NativeMenuItem
        {
            Header = "⚡ Startup Mode",
            Command = _viewModel!.StartupModeCommand
        });
        menu.Add(new NativeMenuItem
        {
            Header = "💻 Dev Mode",
            Command = _viewModel!.DevModeCommand
        });
        menu.Add(new NativeMenuItem
        {
            Header = "🎮 Game Mode",
            Command = _viewModel!.GameModeCommand
        });

        menu.Add(new NativeMenuItemSeparator());

        menu.Add(new NativeMenuItem
        {
            Header = "📊 Open Dashboard",
            Command = _viewModel!.OpenDashboardCommand
        });

        menu.Add(new NativeMenuItemSeparator());

        menu.Add(new NativeMenuItem
        {
            Header = "✕ Exit",
            Command = _viewModel!.ExitCommand
        });

        return menu;
    }
}