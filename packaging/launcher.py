"""打包后的程序入口（PyInstaller）。"""

import sys

from lolhex.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
