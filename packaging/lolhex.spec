# PyInstaller 配置：游戏机助手（onedir，无控制台窗口）。
# 用法：pyinstaller packaging/lolhex.spec --noconfirm --distpath build/dist --workpath build/work
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = collect_data_files("rapidocr")  # OCR 模型（.onnx）与配置（.yaml）
datas += [("../lolhex/ui/icon.png", "lolhex/ui")]
datas += [("../lolhex/data/hero_aliases.json", "lolhex/data")]  # 英雄别名（Hexdata）
datas += [("../lolhex/data/hero_nicknames.json", "lolhex/data")]  # 英雄外号（网上常见叫法）
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    ["launcher.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=["lolhex.ui.overlay", "lolhex.vision.detector", "lolhex.vision.capture", "lolhex.vision.ocr",
                   "lolhex.game.liveclient", "lolhex.ui.mainwindow", "lolhex.ui.autostart",
                   "PySide6.QtNetwork"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "lolhex.service"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="LolHex",
    console=False,
    icon="lolhex.ico",
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LolHex")
