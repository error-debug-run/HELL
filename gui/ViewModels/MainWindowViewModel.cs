using System;
using System.Net.Http;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;

namespace gui.ViewModels;

public partial class MainWindowViewModel : ViewModelBase
{
    private readonly HttpClient _http   = new();
    private const    string     ApiBase = "http://127.0.0.1:8000";

    [RelayCommand]
    private async Task StartupMode()
    {
        Console.WriteLine("StartupMode clicked");
        await SendIntent("startup_mode");
    }

    [RelayCommand]
    private async Task DevMode()
    {
        Console.WriteLine("DevMode clicked");
        await SendIntent("dev_mode");
    }

    [RelayCommand]
    private async Task GameMode()
    {
        Console.WriteLine("GameMode clicked");
        await SendIntent("game_mode");
    }

    [RelayCommand]
    private void OpenDashboard()
    {
        Console.WriteLine("OpenDashboard clicked");
        if (Application.Current?.ApplicationLifetime
            is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow?.Show();
            desktop.MainWindow?.Activate();
            desktop.MainWindow!.ShowInTaskbar = true;
            desktop.MainWindow!.WindowState   = Avalonia.Controls.WindowState.Normal;
        }
    }

    [RelayCommand]
    private void Exit()
    {
        Console.WriteLine("Exit clicked");
        if (Application.Current?.ApplicationLifetime
            is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.Shutdown();
        }
    }

    private async Task SendIntent(string intent)
    {
        try
        {
            Console.WriteLine($"Sending intent: {intent}");
            await _http.PostAsync(
                $"{ApiBase}/intent",
                new StringContent(
                    $"{{\"input\": \"{intent}\"}}",
                    System.Text.Encoding.UTF8,
                    "application/json"
                )
            );
        }
        catch (Exception ex)
        {
            // API not running — log but don't crash
            Console.WriteLine($"API not running: {ex.Message}");
        }
    }
}