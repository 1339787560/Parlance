# CPP Build & Debug Guide

> VSCode + VS2013 v120 toolset, MSBuild, cppvsdbg.
> Server name varies: `zgdasvr`, `xzmosvr`, `xzmssvr`, `xzmsSvr` — adapt paths accordingly.

## Project Info

| Item | Value (zgdasvr) | Value (xzmsSvr / zhong) |
|------|-----------------|-------------------------|
| Solution | `zgdasvr/zgdasvr.sln` | `zhong.sln` |
| Project | `zgdasvr/ZgDaSvr.vcxproj` | `gamesvr/gameSvr.vcxproj` |
| App type | MFC console (Win32/x86) | MFC console (Win32/x86) |
| Toolset | v120 (VS2013) | v120 |
| Entry | `_tmain` in `ZgDaSvr.cpp` | `_tmain` in `GameSvr.cpp` |
| Debug exe | `zgdasvr/Debug/zgdasvrcd.exe` | `gamesvr/Debug/xzmsSvr.exe` |
| Preprocessor | `UWL_TRACE;WIN32;_DEBUG;_CONSOLE` | `_SHOWALLCARDS;UWL_TRACE;WIN32;_DEBUG;_MAKECARD;_CONSOLE` |
| PDB | `zgdasvr/Debug/ZgDaSvrcd.pdb` | `gamesvr/Debug/xzmsSvr.pdb` |

## Command-Line Build (from Bash)

### Approach 1: Batch file + powershell (recommended)

Create a `.bat` file:
```bat
@echo off
set VSCMD_SKIP_SENDTELEMETRY=1
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat"
msbuild gamesvr/gameSvr.vcxproj /p:Configuration=Debug /p:Platform=Win32 /p:PlatformToolset=v120 /m
```
Then run via powershell to avoid bash quoting issues:
```bash
powershell -Command "cmd.exe /c 'build.bat'"
```

### Approach 2: devenv.com (simpler, no rsp interference)
```bash
powershell -Command "devenv.com 'gamesvr/gameSvr.vcxproj' '/Build' 'Debug|Win32'"
```
**Note**: `devenv.com` lives at `C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\devenv.com`. VsDevCmd.bat sets the PATH so it can be found.

### Pitfall: MSBuild.rsp interference
`C:\Program Files\...\MSBuild\Current\Bin\MSBuild.rsp` auto-appends arguments. Calling `MSBuild.exe` directly from bash can cause "MSB1008: only one project". Always use VsDevCmd.bat or devenv.com instead.

## Running the Debug Exe

```bash
# Exe outputs GBK text — use python to read logs
powershell -Command "cmd.exe /c 'gamesvr/Debug/xzmsSvr.exe'"
# Or read the background output file with:
python -c "import sys; print(open(sys.argv[1],'r',encoding='gbk').read())" <output_file>
```

- `chCurrentDir()` auto-switches working dir to exe dir
- Ini file (`xzmsSvr.ini`) must be in exe dir
- Exe enters `WatchInput()` and waits for keyboard input (type "q" to quit)
- Port bind error (10048) means another instance is already running

## Build Performance

- **Incremental**: ~0.3s (cached .obj files remain across builds)
- **Full rebuild**: slow — links many static libs from `LibraryVC12_P`
- Precompiled headers (`.pch`) speed up compilation; avoid unnecessary `Rebuild All`

## Reading Test Output

The DEBUG build calls `execAllTest()` at startup. Tests run on the `_tmain` thread before the server loop. Check the first few lines of output for PASS/FAIL.

## VSCode Config Files

Create under project root `.vscode/`:

**launch.json** — `cppvsdbg` debugger, `cwd` set to exe dir, `preLaunchTask` triggers build.

**tasks.json** — use the batch file above as the task command.

**c_cpp_properties.json** — include paths match vcxproj `AdditionalIncludeDirectories`; defines match preprocessor; `intelliSenseMode: windows-msvc-x86`.

## Prerequisites

- v120 toolset installed (via VS Installer)
- Environment vars `VS_CTNetlibPath` / `VS_CTLibPath` configured (pointing to `D:\LibraryVC12\...`)
- Dependent libs (`tcgament`, `tcgmj`, `xygame`, `uwl` etc.) pre-compiled at `LibraryVC12_P`
- MFC debug DLLs (`mfc120d.dll` etc.) in PATH or exe dir
- `xzmsSvr.ini` in exe working dir

## Verification

1. Run the build -> check for 0 errors and 0 warnings
2. Run the exe -> verify "helloworld" log appears after "MS PWD" in the output
3. `Ctrl+Shift+B` in VSCode — build task runs successfully
