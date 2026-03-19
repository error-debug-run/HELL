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
    private TrayIcon?             _trayIcon;

    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        _viewModel = new MainWindowViewModel();
        DataContext = _viewModel;

        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = new MainWindow
            {
                DataContext = _viewModel,
            };

            desktop.MainWindow.Hide();
            
            desktop.MainWindow.Loaded += (_, _) =>
            {
                desktop.MainWindow.Hide();
                desktop.MainWindow.ShowInTaskbar = false;
            };

            // build tray icon in code
            _trayIcon = new TrayIcon
            {
                ToolTipText = "HELL",
                Icon        = new WindowIcon(
                    AssetLoader.Open(
                        new Uri("avares://gui/Assets/avalonia-logo.ico")
                    )
                ),
                Menu = BuildTrayMenu(),
            };

            _trayIcon.Clicked += (_, _) => _viewModel.OpenDashboardCommand.Execute(null);

            desktop.Exit += (_, _) => _trayIcon.Dispose();
        }

        base.OnFrameworkInitializationCompleted();
    }

    private NativeMenu BuildTrayMenu()
    {
        var menu = new NativeMenu();

        menu.Add(new NativeMenuItem { Header = "HELL v0.1", IsEnabled = false });
        menu.Add(new NativeMenuItemSeparator());

        menu.Add(new NativeMenuItem
        {
            Header  = "⚡ Startup Mode",
            Command = _viewModel!.StartupModeCommand
        });
        menu.Add(new NativeMenuItem
        {
            Header  = "💻 Dev Mode",
            Command = _viewModel!.DevModeCommand
        });
        menu.Add(new NativeMenuItem
        {
            Header  = "🎮 Game Mode",
            Command = _viewModel!.GameModeCommand
        });

        menu.Add(new NativeMenuItemSeparator());

        menu.Add(new NativeMenuItem
        {
            Header  = "📊 Open Dashboard",
            Command = _viewModel!.OpenDashboardCommand
        });

        menu.Add(new NativeMenuItemSeparator());

        menu.Add(new NativeMenuItem
        {
            Header  = "✕ Exit",
            Command = _viewModel!.ExitCommand
        });

        return menu;
    }
}