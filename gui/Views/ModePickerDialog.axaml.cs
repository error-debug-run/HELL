using Avalonia.Controls;
using Avalonia.Interactivity;
using gui.Models;

namespace gui.Views;

public partial class ModePickerDialog : Window
{
    public ModePickerDialog(AppEntry app)
    {
        InitializeComponent();
        AppNameText.Text = app.Name;
    }

    private void OnStartup(object? sender, RoutedEventArgs e)
        => Close("startup");

    private void OnGame(object? sender, RoutedEventArgs e)
        => Close("game");

    private void OnDev(object? sender, RoutedEventArgs e)
        => Close("dev");

    private void OnCancel(object? sender, RoutedEventArgs e)
        => Close(null);
}