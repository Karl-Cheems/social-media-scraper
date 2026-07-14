@echo off
chcp 936 >nul
title 社交媒体监控工具 - 一键部署
echo ============================================
echo   社交媒体监控工具 - 一键部署
echo ============================================
echo.
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
cd /d "%SCRIPT_DIR%"
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 请右键选择 "以管理员身份运行" 本脚本
    pause
    exit /b 1
)
echo [1/8] 检测 Python 环境...
set "PYTHON_DIR=%SCRIPT_DIR%\python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
if exist "%PYTHON_EXE%" (
    echo   -^> 已检测到便携 Python
    goto :INSTALL_PIP
)
echo   -^> 正在下载 Python 3.12...
set "PYTHON_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
set "ZIP_FILE=%TEMP%\python312.zip"
echo   -^> 下载中（约 10MB）...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = 'tls12, tls11, tls'; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%ZIP_FILE%' -UseBasicParsing"
if %errorlevel% neq 0 ( echo [!] 下载失败 & pause & exit /b 1 )
echo   -^> 解压中...
powershell -Command "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath '%PYTHON_DIR%' -Force"
del "%ZIP_FILE%" 2>nul
if not exist "%PYTHON_EXE%" ( echo [!] 解压失败 & pause & exit /b 1 )
echo   -^> 配置 Python 搜索路径...
set "PTH_FILE=%PYTHON_DIR%\python312._pth"
powershell -Command "(Get-Content '%PTH_FILE%') -replace '^#import site','import site' | Set-Content '%PTH_FILE%'"
:INSTALL_PIP
echo [2/8] 安装 pip...
set "GET_PIP=%TEMP%\get-pip.py"
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = 'tls12, tls11, tls'; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%GET_PIP%' -UseBasicParsing"
if %errorlevel% neq 0 ( echo [!] 下载 pip 失败 & pause & exit /b 1 )
"%PYTHON_EXE%" "%GET_PIP%" --quiet
del "%GET_PIP%" 2>nul
echo [3/8] 安装 Python 依赖...
"%PYTHON_EXE%" -m pip install playwright pydantic requests -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
if %errorlevel% neq 0 ( echo [!] 安装依赖失败 & pause & exit /b 1 )
echo [4/8] 写入配置文件...
echo # AI Agent> "%SCRIPT_DIR%\.env"
echo AGENT_URL=http://101.42.14.156:8443/paopao/rpc>> "%SCRIPT_DIR%\.env"
echo AGENT_SENDER=ou_66f8c01a0c53113c68ced2a1685ddf72>> "%SCRIPT_DIR%\.env"
echo AGENT_CHAT=oc_bbe844f289a0a097f093bfc4408ffc5d>> "%SCRIPT_DIR%\.env"
echo [5/8] 创建桌面快捷方式...
set "SHORTCUT=%USERPROFILE%\Desktop\社交媒体监控工具.lnk"
powershell -Command "$WS=New-Object -ComObject WScript.Shell; $SC=$WS.CreateShortcut('%SHORTCUT%'); $SC.TargetPath='%SCRIPT_DIR%\社交监控工具.exe'; $SC.WorkingDirectory='%SCRIPT_DIR%'; $SC.Save()"
echo.
echo ============================================
echo   部署完成！
echo   启动方式：桌面快捷方式或社交监控工具.exe
echo.
echo   请确保 Edge 浏览器已登录微博/小红书
echo ============================================
echo.
start "" "%SCRIPT_DIR%\社交监控工具.exe"
pause
