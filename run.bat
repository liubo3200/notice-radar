@echo off
chcp 65001 >nul
echo ============================================
echo   通知雷达 NoticeRadar  正在启动
echo ============================================
python -m pip install -r requirements.txt -q
echo.
echo 启动后请用浏览器打开: http://127.0.0.1:8000
echo 关闭本窗口即可停止服务
echo.
python app.py
pause
