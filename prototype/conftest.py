"""确保测试可直接 import fishagent_m1 (无需安装)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
