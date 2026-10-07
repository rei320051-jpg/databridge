# -*- coding: utf-8 -*-
"""页面渲染冒烟测试。

背景：Streamlit 只在浏览器连接时才执行脚本，"服务器能启动"并不代表"页面能渲染"。
本测试用一个桩 streamlit 模块替换真实库，真实执行一遍 app.py 的全部渲染逻辑，
从而在没有浏览器的环境下捕获 NameError / KeyError / 类型错误等运行时问题。

注意：它验证的是「页面代码能跑完」，不验证视觉呈现。视觉验收仍需人工打开页面。
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT = [r"C:\Windows\Temp\_render_out.txt", ROOT / "tests" / "_render_out.txt"]
LINES = []
ERRORS = []


def log(msg: str = "") -> None:
    LINES.append(str(msg))
    for p in OUT:
        try:
            Path(p).write_text("\n".join(LINES), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# 桩 streamlit
# ---------------------------------------------------------------------------

class Ctx:
    """万能占位对象：可作为上下文管理器，任意属性调用都返回自身。"""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):
        def _f(*a, **k):
            return Ctx()
        return _f

    def __bool__(self):
        return True

    def __iter__(self):
        return iter([])


class Form(Ctx):
    def text_input(self, *a, **k):
        return k.get("value", "2026年9月各地区的净销售额")

    def form_submit_button(self, *a, **k):
        return True


class StubStreamlit:
    session_state = {}

    @staticmethod
    def set_page_config(**k):
        pass

    @staticmethod
    def cache_data(**k):
        def deco(f):
            return f
        return deco

    @staticmethod
    def cache_resource(**k):
        def deco(f):
            return f
        return deco

    @staticmethod
    def radio(label, options, index=0, **k):
        if isinstance(index, int) and 0 <= index < len(options):
            return options[index]
        return options[0]

    @staticmethod
    def text_input(label, value="", **k):
        return value or "2026年9月各地区的净销售额"

    @staticmethod
    def button(label, **k):
        return True

    @staticmethod
    def form_submit_button(label, **k):
        return True

    @staticmethod
    def checkbox(label, value=False, **k):
        return value

    @staticmethod
    def toggle(label, value=False, **k):
        return value

    @staticmethod
    def file_uploader(*a, **k):
        return None

    @staticmethod
    def tabs(labels):
        return [Ctx() for _ in labels]

    @staticmethod
    def columns(n):
        # Streamlit 的 columns 可以传整数，也可以传权重列表 [1, 3]
        count = n if isinstance(n, int) else len(n)
        return [Ctx() for _ in range(count)]

    @staticmethod
    def form(key, **k):
        return Form()

    @staticmethod
    def chat_message(role):
        return Ctx()

    @staticmethod
    def expander(label, **k):
        return Ctx()

    @staticmethod
    def spinner(text):
        return Ctx()

    sidebar = Ctx()

    @staticmethod
    def metric(*a, **k):
        pass

    @staticmethod
    def progress(value, text=None, **k):
        return Ctx()

    @staticmethod
    def dataframe(*a, **k):
        pass

    @staticmethod
    def table(*a, **k):
        pass

    @staticmethod
    def bar_chart(*a, **k):
        pass

    @staticmethod
    def line_chart(*a, **k):
        pass

    @staticmethod
    def json(*a, **k):
        pass

    @staticmethod
    def code(*a, **k):
        pass

    @staticmethod
    def markdown(*a, **k):
        pass

    @staticmethod
    def caption(*a, **k):
        pass

    @staticmethod
    def title(*a, **k):
        pass

    @staticmethod
    def subheader(*a, **k):
        pass

    @staticmethod
    def divider(*a, **k):
        pass

    @staticmethod
    def write(*a, **k):
        pass

    @staticmethod
    def success(*a, **k):
        pass

    @staticmethod
    def warning(*a, **k):
        pass

    @staticmethod
    def info(*a, **k):
        pass

    @staticmethod
    def error(*a, **k):
        pass

    @staticmethod
    def exception(*a, **k):
        pass

    @staticmethod
    def help(*a, **k):
        pass

    @staticmethod
    def download_button(*a, **k):
        pass

    @staticmethod
    def rerun():
        pass

    @staticmethod
    def stop():
        pass


# ---------------------------------------------------------------------------


def main() -> None:
    log("=" * 78)
    log("数桥 DataBridge · 页面渲染冒烟测试")
    log("=" * 78)

    sys.modules["streamlit"] = StubStreamlit
    log("已注入桩 streamlit 模块")

    src = (APP_DIR / "app.py").read_text(encoding="utf-8")
    code = compile(src, str(APP_DIR / "app.py"), "exec")
    log("app.py 编译通过")

    g = {"__name__": "__main__", "__file__": str(APP_DIR / "app.py")}
    try:
        exec(code, g)
        log("app.py 完整执行通过（五个区域全部渲染完毕）")
    except BaseException:  # noqa: BLE001
        ERRORS.append("app.py 执行异常")
        log("app.py 执行异常：\n" + traceback.format_exc())
        return

    ss = StubStreamlit.session_state
    log(f"\n会话状态键：{sorted(ss)}")
    log(f"对话轮数：{len(ss.get('chat_log', []))}")
    log(f"历史查询：{len(ss.get('history', []))}")
    log(f"Agent 结果：{'有' if ss.get('agent_result') else '无'}")

    turns = ss.get("chat_log", [])
    if turns:
        log("\n对话记录（前 12 条）：")
        for t in turns[:12]:
            log(f"  [{t['role']}] {t['text']}")

    last = ss.get("last_response") or {}
    log(f"\n最后一次响应状态：{last.get('status')}")
    log(f"最后一次响应指标：{last.get('metric')}")
    log(f"是否返回口径：{bool(last.get('definition'))}")
    log(f"是否返回来源表：{last.get('source_tables')}")
    log(f"是否返回数据集版本：{last.get('dataset_version')}")
    log(f"是否返回 SQL：{bool(last.get('generated_sql'))}")

    if len(turns) < 4:
        ERRORS.append("对话轮数过少，页面交互路径可能未完全执行")
    if not ss.get("agent_result"):
        ERRORS.append("Agent 调用回放未产生结果")

    log("\n" + "=" * 78)
    if ERRORS:
        log("结论：" + "；".join(ERRORS))
    else:
        log("结论：页面代码可在无浏览器环境下完整执行，五个功能区域均渲染成功。")
    log("=" * 78)


if __name__ == "__main__":
    main()
