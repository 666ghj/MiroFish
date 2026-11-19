/*
 * MiroFish.exe —— 桌面版启动器 (Windows x64)
 *
 * 职责：
 *   1. 定位 Python 解释器（支持两种安装形态）：
 *        runtime\venv\Scripts\pythonw.exe    <- Setup.bat 首次运行时创建的虚拟环境
 *        runtime\python\pythonw.exe          <- 完整离线版内置的 embeddable Python
 *   2. 首次运行且找不到解释器时，询问并调用 Setup.bat 自动初始化。
 *   3. 以安装目录为工作目录运行 app\app.py，透传命令行参数，等待其退出。
 *   4. --console 时保留控制台窗口，方便查看报错。
 *
 * 交叉编译（Linux，使用 zig）：
 *   zig cc -target x86_64-windows-gnu -O2 -municode -mwindows \
 *          -o MiroFish.exe launcher.c app.rc -lole32 -lshell32 -luser32
 */

#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <wchar.h>

#define PATH_CAP 4096

static void dirname_of(wchar_t *path)
{
    wchar_t *p = wcsrchr(path, L'\\');
    if (p) *p = L'\0';
}

static int file_exists(const wchar_t *path)
{
    DWORD attr = GetFileAttributesW(path);
    return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}

static void show_error(const wchar_t *message, const wchar_t *detail)
{
    wchar_t buf[4096];
    _snwprintf(buf, 4096, L"%ls\n\n%ls", message, detail ? detail : L"");
    MessageBoxW(NULL, buf, L"MiroFish", MB_OK | MB_ICONERROR);
}

static void append_arg(wchar_t *out, size_t cap, const wchar_t *arg)
{
    size_t used = wcslen(out);
    if (used + 2 >= cap) return;
    out[used++] = L' ';
    out[used++] = L'"';
    out[used] = L'\0';
    for (const wchar_t *p = arg; *p && used + 4 < cap; ++p) {
        if (*p == L'"') {
            out[used++] = L'\\';
            out[used++] = L'"';
        } else {
            out[used++] = *p;
        }
        out[used] = L'\0';
    }
    if (used + 2 < cap) {
        out[used++] = L'"';
        out[used] = L'\0';
    }
}

static int has_flag(int argc, wchar_t **argv, const wchar_t *flag)
{
    for (int i = 1; i < argc; ++i) {
        if (_wcsicmp(argv[i], flag) == 0) return 1;
    }
    return 0;
}

/* 返回 1 表示找到解释器 */
static int find_python(const wchar_t *app_dir, int console_mode, wchar_t *out)
{
    const wchar_t *candidates[] = {
        L"runtime\\venv\\Scripts\\pythonw.exe",
        L"runtime\\venv\\Scripts\\python.exe",
        L"runtime\\python\\pythonw.exe",
        L"runtime\\python\\python.exe",
        L"resources\\runtime\\python\\pythonw.exe",
        NULL
    };
    for (int i = 0; candidates[i]; ++i) {
        const wchar_t *name = candidates[i];
        if (console_mode) {
            /* 控制台模式优先 python.exe */
            if (wcsstr(name, L"pythonw.exe")) continue;
        }
        _snwprintf(out, PATH_CAP, L"%ls\\%ls", app_dir, name);
        if (file_exists(out)) return 1;
    }
    /* 兜底：环境变量 */
    wchar_t env_py[PATH_CAP];
    DWORD n = GetEnvironmentVariableW(L"MIROFISH_PYTHON", env_py, PATH_CAP);
    if (n > 0 && n < PATH_CAP && file_exists(env_py)) {
        wcscpy(out, env_py);
        return 1;
    }
    return 0;
}

static int run_setup(const wchar_t *app_dir)
{
    wchar_t script[PATH_CAP];
    _snwprintf(script, PATH_CAP, L"%ls\\Setup.bat", app_dir);
    if (!file_exists(script)) return 0;

    int answer = MessageBoxW(NULL,
        L"首次运行需要初始化运行环境。\n\n"
        L"将从网络下载 Python 与依赖（约 500 MB～1 GB，视网络而定），\n"
        L"之后再启动就不需要联网了。\n\n"
        L"现在开始初始化吗？",
        L"MiroFish 首次运行", MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON1);
    if (answer != IDYES) return 0;

    wchar_t cmd[PATH_CAP * 2];
    _snwprintf(cmd, PATH_CAP * 2, L"cmd.exe /c \"\"%ls\"\"", script);

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessW(NULL, cmd, NULL, NULL, TRUE, 0, NULL, app_dir, &si, &pi)) {
        return 0;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return code == 0;
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR lpCmdLine, int nCmdShow)
{
    (void)hInstance; (void)hPrevInstance; (void)lpCmdLine; (void)nCmdShow;

    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);

    wchar_t exe_path[PATH_CAP];
    DWORD len = GetModuleFileNameW(NULL, exe_path, PATH_CAP);
    if (len == 0 || len >= PATH_CAP) {
        show_error(L"无法确定程序所在目录。", NULL);
        return 2;
    }
    wchar_t app_dir[PATH_CAP];
    wcscpy(app_dir, exe_path);
    dirname_of(app_dir);

    int want_console = has_flag(argc, argv, L"--console");
    int headless = has_flag(argc, argv, L"--headless");
    int want_browser = has_flag(argc, argv, L"--browser");
    int console_mode = want_console || headless || want_browser;

    wchar_t python[PATH_CAP];
    if (!find_python(app_dir, console_mode, python)) {
        if (has_flag(argc, argv, L"--no-setup") || !run_setup(app_dir)) {
            if (!find_python(app_dir, console_mode, python)) {
                show_error(L"MiroFish 尚未初始化：找不到 Python 运行环境。",
                           L"请双击安装目录中的 Setup.bat 完成初始化（需要联网），"
                           L"或使用完整离线版安装包。");
                return 3;
            }
        }
        if (!find_python(app_dir, console_mode, python)) {
            show_error(L"初始化失败：仍然找不到 Python 运行环境。",
                       L"请查看 Setup.bat 窗口中的报错信息。");
            return 3;
        }
    }

    wchar_t script[PATH_CAP];
    _snwprintf(script, PATH_CAP, L"%ls\\app\\app.py", app_dir);
    if (!file_exists(script)) {
        show_error(L"MiroFish 安装不完整：找不到 app\\app.py。",
                   L"请重新解压安装包。");
        return 4;
    }

    static wchar_t cmd[32768];
    cmd[0] = L'\0';
    append_arg(cmd, 32768, python);
    append_arg(cmd, 32768, script);
    for (int i = 1; i < argc; ++i) {
        append_arg(cmd, 32768, argv[i]);
    }

    if (want_console && GetConsoleWindow() == NULL) {
        AllocConsole();
        SetConsoleTitleW(L"MiroFish 日志");
        FILE *f;
        freopen_s(&f, "CONOUT$", "w", stdout);
        freopen_s(&f, "CONOUT$", "w", stderr);
    }

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    DWORD flags = CREATE_UNICODE_ENVIRONMENT;
    if (!CreateProcessW(python, cmd, NULL, NULL, want_console ? TRUE : FALSE,
                        flags, NULL, app_dir, &si, &pi)) {
        wchar_t detail[PATH_CAP * 2];
        _snwprintf(detail, PATH_CAP * 2, L"CreateProcess 失败 (错误码 %lu)\n%ls",
                   GetLastError(), cmd);
        show_error(L"无法启动 MiroFish 后端。", detail);
        return 5;
    }

    WaitForSingleObject(pi.hProcess, INFINITE);

    DWORD exit_code = 0;
    GetExitCodeProcess(pi.hProcess, &exit_code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    LocalFree(argv);

    if (want_console) {
        wprintf(L"\n[launcher] 后端已退出，退出码 %lu。按回车关闭窗口...\n", exit_code);
        getchar();
    }
    return (int)exit_code;
}
