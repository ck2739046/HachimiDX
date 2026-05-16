using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

class Program
{
    [DllImport("kernel32.dll")]
    private static extern IntPtr GetConsoleWindow();

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    private enum ConsoleState
    {
        Restore = 9,
        Minimize = 6
    }

    private static void SetConsoleState(ConsoleState state)
    {
        var handle = GetConsoleWindow();
        if (handle != IntPtr.Zero)
            ShowWindow(handle, (int)state);
    }

    static void Main()
    {
        SetConsoleState(ConsoleState.Minimize);

        var proc = Process.Start(new ProcessStartInfo
        {
            FileName = @".\python\python.exe",
            Arguments = "-u main.py",
            UseShellExecute = false
        });
        proc?.WaitForExit();

        if (proc?.ExitCode != 0)
        {
            SetConsoleState(ConsoleState.Restore);
            Console.WriteLine("\n按任意键继续...\nPress any key to continue...");
            Console.ReadKey(true);
        }
    }
}
