using Avalonia.Controls;

namespace gui.Views;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        this.Closing += OnClosing;
    }

    private void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        // Cancel actual close
        e.Cancel = true;

        // Hide instead (tray behavior)
        this.Hide();
        this.ShowInTaskbar = false;
    }
}