@echo off
chcp 65001 >nul
echo ============================================
echo   通知雷达 · 公网演示模式
echo ============================================
echo.
echo [1/2] 启动本地服务（另开一个窗口，别关）
start "NoticeRadar-Server" cmd /k python app.py
timeout /t 4 >nul

echo [2/2] 启动公网隧道
echo.
echo 下面会出现一行 https://xxxx.trycloudflare.com
echo 把那个网址发给别人，手机流量也能打开。
echo 关掉这个窗口，公网就断了。
echo.
"%~dp0..\tools-bin\cloudflared.exe" tunnel --url http://127.0.0.1:8000 --no-autoupdate
pause
