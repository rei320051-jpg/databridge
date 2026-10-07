# -*- coding: utf-8 -*-
"""页面运行配置。

切换后端只需改 BACKEND_MODE，或在页面左侧栏直接切换，不需要改动任何页面代码。
这是成员 3 与成员 1 / 成员 2 的解耦点：接口未就绪时用 mock，接口就绪后切 live。
"""

from __future__ import annotations

import os

#: "mock" = 本地模拟后端（接口未就绪时使用）
#: "live" = 真实调用成员 1 的查询服务
BACKEND_MODE = os.environ.get("DATABRIDGE_BACKEND", "mock")

#: 成员 1 的 FastAPI 服务地址
API_BASE_URL = os.environ.get("DATABRIDGE_API", "http://127.0.0.1:8000")

#: 单次请求超时（秒）。页面不得因为后端卡住而无限等待。
API_TIMEOUT = 20

#: 页面上最多保留多少轮对话
CHAT_HISTORY_LIMIT = 30

#: 结果表最多展示多少行（超出提示下载）
TABLE_PREVIEW_ROWS = 200
