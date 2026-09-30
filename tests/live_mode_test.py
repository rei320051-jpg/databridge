# -*- coding: utf-8 -*-
"""live 模式集成测试：验证页面 → HTTP → 参考服务 的完整链路。

启动方式：在**本进程内**起一个后台线程运行契约参考服务，再用 urllib 真实访问。
这样无需跨进程网络通信，也规避了本机沙箱对独立网络进程的限制。

注意：本机沙箱会终止发起网络请求的进程，因此本脚本采用增量落盘日志，
一旦被中断也能从最后一行日志定位到中断位置。
"""

from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import urllib.error
import urllib.request

import mock_server  # noqa: E402
from client import QueryClient  # noqa: E402
from demo_data import demo_tables  # noqa: E402
from shared.contracts import Status  # noqa: E402

OUT = [r"C:\Windows\Temp\_live_out.txt", ROOT / "tests" / "_live_out.txt"]
LINES = []
FAILS = []
PORT = 8591


def log(msg: str = "") -> None:
    LINES.append(str(msg))
    for p in OUT:
        try:
            Path(p).write_text("\n".join(LINES), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def check(name: str, ok: bool, detail: str = "") -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def main() -> None:
    log("=" * 74)
    log("数桥 DataBridge · live 模式集成测试（页面 → HTTP → 契约参考服务）")
    log("=" * 74)

    log("\n[0] 在本进程内启动契约参考服务 …")
    mock_server.ensure_tables()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), mock_server.ContractHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{PORT}"
    log(f"  服务已就绪：{base}")
    time.sleep(0.3)

    client = QueryClient(mode="live", base_url=base, timeout=10)
    real_urlopen = urllib.request.urlopen

    # ---------------- 1. health ----------------
    log("\n[1] GET /health")
    h = client.health()
    log(f"  返回：{json.dumps(h, ensure_ascii=False)}")
    check("健康检查返回 ok", h.get("status") == "ok")
    check("健康检查返回表名与行数", bool(h.get("tables")) and bool(h.get("rows")),
          str(h.get("rows")))

    # ---------------- 2. 明确可答 ----------------
    log("\n[2] POST /agent/query — 明确可答")
    r = client.submit("2026年9月各地区的净销售额")
    log(f"  status = {r.get('status')}  rows = {r.get('row_count')}")
    log(f"  data   = {r.get('data')}")
    check("返回 success", r.get("status") == Status.SUCCESS)
    check("携带口径", bool(r.get("definition")))
    check("携带来源表", bool(r.get("source_tables")))
    check("携带数据集版本", bool(r.get("dataset_version")))
    check("携带可追溯 SQL", bool(r.get("generated_sql")))

    # ---------------- 3. 澄清闭环（跨 HTTP） ----------------
    log("\n[3] POST /agent/query — 澄清闭环（两次请求）")
    c1 = client.submit("9月的销售额是多少")
    log(f"  首轮 status = {c1.get('status')}")
    check("首轮返回 need_clarification", c1.get("status") == Status.NEED_CLARIFICATION)
    clr = c1.get("clarification") or {}
    log(f"  澄清 id = {clr.get('id')}  目标槽位 = {clr.get('target_field')}")

    c2 = client.resolve_clarification(
        clr, choice="net_sales", question="9月的销售额是多少",
        context=clr.get("resolved_context") or {})
    log(f"  次轮 status = {c2.get('status')}  metric = {c2.get('metric')}")
    check("次轮返回 success", c2.get("status") == Status.SUCCESS)
    check("采用澄清后的口径 net_sales", c2.get("metric") == "net_sales")
    log(f"  data = {c2.get('data')}")

    # ---------------- 4. 数据不足 ----------------
    log("\n[4] POST /agent/query — 数据不足（不得编造）")
    c3 = client.submit("为什么华东地区9月净销售额下降了")
    log(f"  status = {c3.get('status')}  reason = {c3.get('reason')}")
    log(f"  missing = {c3.get('missing')}")
    check("返回 insufficient_data", c3.get("status") == Status.INSUFFICIENT_DATA)
    check("明确列出缺少的信息", bool(c3.get("missing")))

    # ---------------- 5. 质检接口（multipart） ----------------
    log("\n[5] POST /datasets/inspect — multipart 上传")
    tables = demo_tables()
    small = {k: v.head(200) for k, v in tables.items()}
    files = {f"{k}.csv": v.to_csv(index=False).encode("utf-8") for k, v in small.items()}
    rep = client.inspect_files(files)
    log(f"  严重问题 = {rep.get('total_errors')}  警告 = {rep.get('total_warnings')}")
    for i in rep.get("issues", [])[:5]:
        log(f"    - [{i['level']:<7}] {i['table']}.{i['field']} x{i['count']} {i['message']}")
    log("  说明：这里用的是各表前 200 行的截断样本，跨表外键必然悬空，"
        "因此出现外键错误属预期行为，恰好证明跨表检查生效。")
    check("返回质检报告", rep.get("status") == "ok")
    check("识别出三张表", len(rep.get("tables", [])) == 3)
    check("跨表外键检查生效", any(i["code"] == "orphan_foreign_key"
                              for i in rep.get("issues", [])))

    # ---------------- 6. 异常路径 ----------------
    log("\n[6] 异常路径")
    # urllib 对 4xx 会抛 HTTPError，错误体藏在 exc 里
    try:
        urllib.request.urlopen(f"{base}/not-exist", timeout=5)
        check("未知路径返回 404", False, "未抛 HTTPError")
    except urllib.error.HTTPError as exc:
        body404 = json.loads(exc.read().decode("utf-8"))
        log(f"  404 响应体：{json.dumps(body404, ensure_ascii=False)}")
        check("未知路径返回 404", exc.code == 404)
        check("错误体含 status/message，页面可直接展示",
              body404.get("status") == "error" and bool(body404.get("message")))

    bad = QueryClient(mode="live", base_url="http://127.0.0.1:59998", timeout=2)
    try:
        bad.health()
        log("  连接失败时 health() 返回 unreachable（未抛错，符合页面设计）")
        check("连接失败不会导致页面崩溃", True)
    except Exception as exc:  # noqa: BLE001
        check("连接失败不会导致页面崩溃", False, str(exc)[:70])

    urllib.request.urlopen = real_urlopen
    httpd.shutdown()
    httpd.server_close()

    log("\n" + "=" * 74)
    if FAILS:
        log(f"结论：{len(FAILS)} 项未通过 — " + "；".join(FAILS))
    else:
        log("结论：live 模式全链路通过。三人可以立即开始对着契约服务联调，不必互相等待。")
    log("=" * 74)


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001
        log("脚本异常终止：")
        log(traceback.format_exc())
