@echo off
chcp 65001 >nul
rem 海克斯大乱斗助手（游戏机）：首次运行创建虚拟环境并安装依赖，之后直接启动浮窗。
cd /d %~dp0
if not exist .venv\Scripts\pythonw.exe (
  echo 首次运行：创建虚拟环境并安装依赖……
  py -3.12 -m venv .venv 2>nul || python -m venv .venv
  .venv\Scripts\python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt || (
    echo 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
  )
)
start "" .venv\Scripts\pythonw.exe -m lolhex
