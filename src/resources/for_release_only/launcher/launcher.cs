using System;
using System.Diagnostics;
using System.Runtime.InteropServices;

class Program
{
    [DllImport("kernel32.dll")]
    private static extern IntPtr GetConsoleWindow();

    [DllImport("kernel32.dll")]
    private static extern bool AllocConsole();

    [DllImport("kernel32.dll")]
    private static extern bool FreeConsole();

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);





    // 控制 console 状态
    private static readonly int SW_RESTORE = 9;
    private static readonly int SW_SHOWMINNOACTIVE = 7;

    private static void SetConsoleState(int state)
    {
        var handle = GetConsoleWindow();
        if (handle != IntPtr.Zero)
            ShowWindow(handle, state);
    }





    public static void Main()
    {
        AllocConsole();

        SetConsoleState(SW_SHOWMINNOACTIVE);

        var proc = Process.Start
        (
            new ProcessStartInfo
            {
                FileName = @".\python\python.exe",
                Arguments = "-u main.py",
                UseShellExecute = false
            }
        );
        proc?.WaitForExit();

        if (proc?.ExitCode != 0)
        {
            SetConsoleState(SW_RESTORE);
            Console.WriteLine("\n按任意键继续...\nPress any key to continue...");
            Console.ReadKey(true);
        }

        FreeConsole();
    }
}
