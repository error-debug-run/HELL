using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using gui.ViewModels;

namespace gui.Views;

public partial class StartupWindow : Window
{
    private readonly MainWindowViewModel _viewModel;

    public StartupWindow(MainWindowViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
    }
    
    private void OnContinueClicked(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        ContinueToMain();
    }

    private void ContinueToMain()
    {
        if (Application.Current?.ApplicationLifetime 
            is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var main = new MainWindow
            {
                DataContext = _viewModel
            };

            desktop.MainWindow = main;

            main.Show();
            main.ShowInTaskbar = true;
            main.Activate();

            this.Close();
        }
    }
}