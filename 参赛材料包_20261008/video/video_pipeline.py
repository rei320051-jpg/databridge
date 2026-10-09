"""Reproducible capture/voice/render pipeline; all outputs stay beside this file.

Run with the interpreter recorded in the approved storyboards. Source files are
read-only; local server query logs are redirected to _work/query_records.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import wave

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROJECT = ROOT / "赛题二"
WORK = HERE / "_work"
WORK.mkdir(exist_ok=True)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
API = "http://127.0.0.1:8001"
APP = "http://127.0.0.1:8501"
FPS = 10
SIZE = (1920, 1080)
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
SUBTITLE_STYLE_V2 = {
    "version": "v2", "play_res_x": 1920, "play_res_y": 1080,
    "font_name": "Microsoft YaHei", "font_size_px": 40,
    # libass FontSize measures ascent+descent, not the raster EM size. This system
    # font at 40px has 43px ascent + 11px descent; use 54 ASS units for a 40px EM.
    "ass_font_size_units": 54,
    "text_color": "#FFFFFF", "outline_color": "#000000", "outline_px": 2.5,
    "alignment": "bottom_center", "margin_bottom_px": 28,
    "bar_height_px": 100, "bar_opacity": .70, "emphasis_color": "#F5B800",
    "emphasis_whitelist": ["17,198,835.91 元", "20,000 订单", "3,492", "2,000",
                           "96.8 万元", "37/37", "67/67", "0"],
}


def subtitle_highlights_v2(text):
    # Exact approved forms only: do not turn the existing "2 万订单" into "20,000".
    pattern = (r"(?<![\d.,/])(?:17,198,835\.91\s*元|20,000\s*订单|"
               r"3,492(?:\s*退款)?|2,000(?:\s*客户)?|96\.8\s*万元|37/37|67/67|0)(?![\d.,/])")
    return [match.group(0) for match in re.finditer(pattern, text)]


def write_subtitles_ass_v2(srt_path, ass_path):
    style = SUBTITLE_STYLE_V2
    cues = parse_srt(srt_path.read_text(encoding="utf-8-sig"))
    def stamp(seconds):
        centiseconds = round(seconds * 100)
        hours, remainder = divmod(centiseconds, 360000)
        minutes, remainder = divmod(remainder, 6000)
        secs, fraction = divmod(remainder, 100)
        return f"{hours}:{minutes:02}:{secs:02}.{fraction:02}"
    def markup(text):
        if any(char in text for char in "{}\\"):
            raise ValueError("Subtitle contains ASS control characters; stop rather than change text")
        # ASS uses BGR, so RGB #F5B800 is &H00B8F5&.
        pattern = (r"(?<![\d.,/])(?:17,198,835\.91\s*元|20,000\s*订单|"
                   r"3,492(?:\s*退款)?|2,000(?:\s*客户)?|96\.8\s*万元|37/37|67/67|0)(?![\d.,/])")
        return re.sub(pattern, lambda m: r"{\1c&H00B8F5&}" + m.group(0) +
                      r"{\1c&HFFFFFF&}", text).replace("\n", r"\N")
    header = (
        "[Script Info]\nTitle: Subtitle rendering v2\nScriptType: v4.00+\n"
        f"PlayResX: {style['play_res_x']}\nPlayResY: {style['play_res_y']}\n"
        "ScaledBorderAndShadow: yes\nWrapStyle: 2\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style['font_name']},{style['ass_font_size_units']},&H00FFFFFF,&H00FFFFFF,"
        f"&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{style['outline_px']},0,2,"
        f"80,80,{style['margin_bottom_px']},1\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(header + "".join(
        f"Dialogue: 0,{stamp(cue['start'])},{stamp(cue['end'])},Default,,0,0,0,,"
        + markup(cue["text"]) + "\n" for cue in cues), encoding="utf-8")
    return cues


def subtitle_filter_v2(ass_path):
    style = SUBTITLE_STYLE_V2
    # Call ffmpeg from ass_path.parent to avoid Windows drive-letter escaping.
    return (f"drawbox=x=0:y=ih-{style['bar_height_px']}:w=iw:h={style['bar_height_px']}:"
            f"color=black@{style['bar_opacity']:.2f}:t=fill,"
            f"ass=filename='{ass_path.name}'")


def log(message):
    print(message, flush=True)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run(args, timeout=240, **kwargs):
    result = subprocess.run([str(a) for a in args], capture_output=True,
                            creationflags=FLAGS, timeout=timeout, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-5000:])
    return result


def binary(name):
    direct = shutil.which(name)
    if direct:
        return Path(direct)
    locations = [Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages",
                 Path(os.environ.get("TEMP", ""))]
    for base in locations:
        for found in base.glob("**/" + name + ".exe"):
            if "ffmpeg" in str(found).lower():
                return found
    raise RuntimeError(name + " not found in PATH or system/temp installation")


def http_json(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def environment():
    expected = json.loads((HERE / "storyboard_赛题二.json").read_text(encoding="utf-8"))["recording"]["python"]
    if Path(expected).resolve() != Path(sys.executable).resolve():
        raise RuntimeError("Interpreter differs from approved detected environment")
    log("[ENV] python=" + sys.executable)
    return {"python": sys.executable, "ffmpeg": str(binary("ffmpeg")),
            "ffprobe": str(binary("ffprobe")), "mode": "rules"}


def start_services():
    env = os.environ.copy()
    env.update(DATABRIDGE_AGENT_MODE="rules", DATABRIDGE_BACKEND="live",
               DATABRIDGE_API=API, DATABRIDGE_DATABASE=str(PROJECT / "outputs/demo-v1.1.sqlite3"),
               DATABRIDGE_RECORDS=str(WORK / "query_records"), PYTHONDONTWRITEBYTECODE="1")
    configs = [
        ("api", [sys.executable, "-m", "uvicorn", "databridge.api:app", "--host", "127.0.0.1", "--port", "8001"]),
        ("streamlit", [sys.executable, "-m", "streamlit", "run", "app/app.py", "--server.address", "127.0.0.1", "--server.port", "8501", "--server.headless", "true", "--browser.gatherUsageStats", "false"]),
    ]
    state = {}
    for name, args in configs:
        output = (WORK / (name + ".log")).open("ab")
        process = subprocess.Popen(args, cwd=PROJECT, env=env, stdout=output,
                                   stderr=subprocess.STDOUT, creationflags=FLAGS)
        output.close()
        state[name] = process.pid
    save_json(WORK / "services.json", state)
    end = time.monotonic() + 60
    while time.monotonic() < end:
        try:
            health = http_json(API + "/health")
            with urllib.request.urlopen(APP + "/_stcore/health", timeout=3) as r:
                assert r.status == 200
            assert health["status"] == "ok" and health["dataset_version"] == "demo-v1.1"
            assert health["row_counts"] == {"orders": 20000, "refunds": 3492, "customers": 2000}
            save_json(HERE / "health_evidence.json", health)
            log("[MILESTONE] FastAPI 与 Streamlit 正式演示服务启动 完成")
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Services did not become healthy within one minute; inspect _work logs")


async def launch_browser(playwright):
    failures = []
    for channel in ("msedge", "chrome", None):
        try:
            options = {"headless": True}
            if channel:
                options["channel"] = channel
            browser = await playwright.chromium.launch(**options)
            chosen = channel or "chromium"
            log("[ENV] browser=" + chosen)
            return browser, chosen
        except Exception as exc:
            failures.append(str(exc))
            log("[ENV] browser fallback after " + (channel or "chromium"))
    raise RuntimeError("Browser launch failed: " + " | ".join(failures))


async def settle(page, seconds=0.9):
    await page.wait_for_timeout(seconds * 1000)
    running = page.get_by_test_id("stStatusWidget")
    if await running.count():
        try:
            await running.first.wait_for(state="hidden", timeout=15000)
        except Exception:
            pass


async def setup_app(browser):
    context = await browser.new_context(viewport={"width": 1600, "height": 900},
                                         device_scale_factor=1, locale="zh-CN")
    page = await context.new_page()
    await page.goto(APP, wait_until="domcontentloaded")
    await page.get_by_role("radio", name=re.compile("正式联调库 demo-v1.1")).wait_for(timeout=45000)
    await page.get_by_text("正式联调库 demo-v1.1（2 万单，2026 年 1–9 月，5 地区）", exact=True).click()
    await settle(page, 2)
    assert await page.get_by_role("radio", name=re.compile("正式联调库 demo-v1.1")).is_checked()
    return context, page


async def tab(page, name):
    await page.get_by_role("tab", name=name, exact=True).click()
    await settle(page)


async def ask(page, question):
    await tab(page, "③ 智能取数")
    field = page.get_by_role("textbox", name="用自然语言提问", exact=True)
    await field.fill("")
    await settle(page)
    await field.press_sequentially(question, delay=110)
    await settle(page)
    await page.get_by_role("button", name="提问", exact=True).click()
    await settle(page, 1.8)


async def preflight():
    from playwright.async_api import async_playwright
    env = environment()
    async with async_playwright() as p:
        browser, chosen = await launch_browser(p)
        context, page = await setup_app(browser)
        await page.screenshot(path=str(WORK / "preflight_app.png"))
        await ask(page, "9月销售额是多少")
        await page.screenshot(path=str(WORK / "preflight_clarification.png"))
        text = await page.locator("body").inner_text()
        save_json(WORK / "app_observation.json", {"text": text,
                  "radios": await page.get_by_role("radio").evaluate_all("els => els.map(e => ({label:e.getAttribute('aria-label'),text:e.parentElement.innerText}))")})
        await page.get_by_text("净销售额 —— 所选期间实付金额减去同期成功退款金额", exact=True).click()
        await settle(page)
        await page.get_by_role("button", name="提交选择", exact=True).click()
        await settle(page, 1.5)
        exact = page.get_by_text("净销售额 = 17,198,835.91", exact=True)
        await exact.wait_for(timeout=15000)
        await exact.scroll_into_view_if_needed()
        await settle(page)
        await page.screenshot(path=str(WORK / "preflight_result.png"))
        await tab(page, "④ 结果依据")
        await page.get_by_text("查看结构化查询计划（成员 2 生成）", exact=True).click()
        await settle(page)
        save_json(WORK / "success_observation.json", {"text": await page.locator("body").inner_text()})
        await ask(page, "为什么9月净销售额下降了")
        await tab(page, "④ 结果依据")
        cause = page.get_by_role("tabpanel", name="④ 结果依据").get_by_text("causal_reasoning_unsupported", exact=True)
        await cause.wait_for(timeout=10000)
        await cause.scroll_into_view_if_needed()
        await page.screenshot(path=str(WORK / "preflight_refusal.png"))
        save_json(WORK / "refusal_observation.json", {"text": await page.locator("body").inner_text()})
        await context.close()
        # Read current online pages and discover section headings from actual DOM.
        online = await browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN")
        web = await online.new_page()
        pages = {}
        for key, url in online_urls().items():
            response = await web.goto(url, wait_until="domcontentloaded", timeout=40000)
            await web.wait_for_timeout(1200)
            body = await web.locator("body").inner_text()
            assert response.status == 200
            assert not any(w in body for w in ("中国数联物流", "央企"))
            pages[key] = {"url": url, "status": response.status,
                          "sha256": hashlib.sha256((await web.content()).encode()).hexdigest()}
            await web.screenshot(path=str(WORK / ("preflight_" + key + ".png")))
        await online.close()
        await browser.close()
        env["browser"] = chosen
        env["online_pages"] = pages
        save_json(HERE / "environment_evidence.json", env)
    log("[MILESTONE] 浏览器、正式数据与线上物料预检 完成")


def online_urls():
    text = (ROOT / "赛题一/D1执行记录_20261008.md").read_text(encoding="utf-8")
    section = text.split("## 二、", 1)[1].split("## 三、", 1)[0]
    landing = re.search(r"https://[^\s`]+\.github\.io/databridge/", section).group(0)
    # The record abbreviates poster URL as /poster.html in this section.
    stamp = str(time.time_ns())
    return {"landing": landing + "?capture_ts=" + stamp,
            "poster": landing + "poster.html?capture_ts=" + stamp}


def srt_timestamp(seconds):
    milliseconds = round(seconds * 1000)
    h, remainder = divmod(milliseconds, 3600000)
    m, remainder = divmod(remainder, 60000)
    s, ms = divmod(remainder, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def story(name):
    return json.loads((HERE / ("storyboard_" + name + ".json")).read_text(encoding="utf-8"))


def make_subtitles():
    for name in ("赛题二", "赛题一"):
        chunks = []
        cursor = 0
        for i, scene in enumerate(story(name)["scenes"], 1):
            end = cursor + scene["duration_sec"]
            chunks.append(f"{i}\n{srt_timestamp(cursor)} --> {srt_timestamp(end)}\n{scene['subtitle_text']}\n")
            cursor = end
        (HERE / (name + "_演示视频.srt")).write_text("\n".join(chunks), encoding="utf-8")
    log("[MILESTONE] 两片外挂字幕与分镜累计时间轴生成 完成")


def audio_duration(path):
    result = run([binary("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(result.stdout)


async def narrate():
    import edge_tts
    directory = WORK / "voice"
    directory.mkdir(exist_ok=True)
    first = story("赛题二")["scenes"][0]
    try:
        await asyncio.wait_for(edge_tts.Communicate(first["subtitle_text"], "zh-CN-YunxiNeural").save(str(directory / "B01.mp3")), timeout=25)
        engine = "edge-tts / zh-CN-YunxiNeural"
    except Exception as exc:
        engine = "Windows SAPI / Chinese system voice"
        log("[ENV] edge-tts unavailable; using SAPI: " + type(exc).__name__)
    all_scenes = [s for n in ("赛题二", "赛题一") for s in story(n)["scenes"]]
    if engine.startswith("edge"):
        semaphore = asyncio.Semaphore(3)
        async def synth(scene):
            target = directory / (scene["scene_id"] + ".mp3")
            if target.exists() and target.stat().st_size > 0:
                return
            async with semaphore:
                await asyncio.wait_for(edge_tts.Communicate(scene["subtitle_text"], "zh-CN-YunxiNeural").save(str(target)), timeout=35)
            log("[VOICE] " + scene["scene_id"] + " generated")
        try:
            await asyncio.gather(*(synth(s) for s in all_scenes))
        except Exception as exc:
            log("[ENV] online voice failed mid-batch; use consistent SAPI for all cues: " + type(exc).__name__)
            engine = "Windows SAPI / Chinese system voice"
    if engine.startswith("Windows"):
        for name in ("赛题二", "赛题一"):
            result = run(["C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoProfile", "-File", HERE / "sapi_voice.ps1",
                          "-Storyboard", HERE / ("storyboard_" + name + ".json"),
                          "-OutputDir", directory], timeout=180)
            log(result.stdout.decode("utf-8", errors="replace"))
    manifest = {"engine": engine, "cues": []}
    for name in ("赛题二", "赛题一"):
        cursor = 0
        with wave.open(str(HERE / (name + "_配音.wav")), "wb") as master:
            master.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            for scene in story(name)["scenes"]:
                sid = scene["scene_id"]
                source = directory / (sid + (".mp3" if engine.startswith("edge") else "_sapi.wav"))
                duration = audio_duration(source)
                available = scene["duration_sec"] - 1.2
                tempo = max(1.0, duration / available)
                normalized = directory / (sid + "_pcm.wav")
                run([binary("ffmpeg"), "-y", "-i", source, "-af", f"atempo={tempo:.6f},loudnorm=I=-18:TP=-2:LRA=7",
                     "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", normalized])
                with wave.open(str(normalized), "rb") as segment:
                    raw = segment.readframes(segment.getnframes())
                lead_frames = int(0.6 * 48000)
                total_frames = int(scene["duration_sec"] * 48000)
                speech_frames = len(raw) // 2
                if lead_frames + speech_frames > total_frames:
                    raise RuntimeError(sid + " voice exceeds scene duration")
                master.writeframes(b"\0" * (lead_frames * 2))
                master.writeframes(raw)
                master.writeframes(b"\0" * ((total_frames - lead_frames - speech_frames) * 2))
                manifest["cues"].append({"scene_id": sid, "start_sec": cursor + .6,
                                         "end_sec": cursor + .6 + speech_frames / 48000,
                                         "scene_start_sec": cursor, "scene_end_sec": cursor + scene["duration_sec"],
                                         "text": scene["subtitle_text"], "tempo": tempo})
                cursor += scene["duration_sec"]
        log("[MILESTONE] " + name + " 配音与时间轴对齐 完成")
    save_json(HERE / "voice_manifest.json", manifest)


def card_html(title, body, *, black=False, source=""):
    bg, fg = ("#000", "#fff") if black else ("#f7f9fc", "#14263f")
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
    <style>*{{box-sizing:border-box}}body{{margin:0;background:{bg};color:{fg};font-family:"Microsoft YaHei",sans-serif}}
    main{{width:100%;min-height:900px;padding:72px 84px;display:flex;flex-direction:column;justify-content:center}}
    h1{{font-size:48px;line-height:1.45;margin:0 0 32px}}p{{font-size:32px;line-height:1.8;margin:16px 0}}
    .big{{font-size:52px;font-weight:700}}.tag{{font-size:24px;color:{'#b9bdc5' if black else '#426992'};margin-bottom:24px}}
    pre{{font:24px/1.5 Consolas,"Microsoft YaHei",monospace;white-space:pre-wrap;margin:0;padding:28px;background:#eaf0f8;border-radius:18px;color:#15334f}}
    .source{{font-size:21px;color:#7890a6;margin-top:28px}}table{{border-collapse:collapse;font-size:23px;line-height:1.6}}
    th,td{{border:1px solid #d8e1ed;padding:15px 20px;min-width:180px;text-align:left}}th{{background:#e8eef7}}
    .tablewrap{{overflow:auto;max-height:640px}}img{{max-width:100%;display:block;margin:auto}}</style>
    <main><div class="tag">{'参赛作品' if black else '证据与状态说明'}</div><h1>{html.escape(title)}</h1>{body}
    <div class="source">{html.escape(source)}</div></main></html>'''


async def open_generated(page, sid, content):
    target = WORK / "pages" / (sid + ".html")
    target.parent.mkdir(exist_ok=True)
    target.write_text(content, encoding="utf-8")
    await page.goto(target.as_uri(), wait_until="domcontentloaded")
    await settle(page)


def evidence_card(scene):
    sid, action = scene["scene_id"], scene["action"]
    if action["type"] == "title_card":
        lines = action["lines"]
        return card_html(lines[0], "".join("<p>" + html.escape(t) + "</p>" for t in lines[1:]), black=True)
    if sid == "B02":
        response = http_json(API + "/health")
        save_json(HERE / "health_evidence.json", response)
        return card_html("正式演示库健康检查", "<pre>" + html.escape(json.dumps(response, ensure_ascii=False, indent=2)) + "</pre>", source="来源：本机 FastAPI /health 实际响应 · 模拟数据")
    report = (PROJECT / "docs/测试报告.md").read_text(encoding="utf-8")
    texts = {
        "B15": ("归档测试证据", ["现场演示：rules 模式", "以下结论来自仓库中已归档的测试报告。", "本片不触发真实模型调用。"]),
        "B16": ("业务题验收", ["37/37 业务题验收通过", "判定范围包含正确作答、澄清与拒答。", "数据来源为正式模拟演示库。"]),
        "B17": ("真实模型归档复测", ["67/67 与 rules 结果逐字段一致", "真实模型只解析结构化槽位，不直接生成 SQL。", "这是归档复测，不是当前录屏中的实时模型调用。"]),
        "B18": ("无依据编造记录", ["0 无依据编造", "仅限归档复测范围。", "不把测试结论扩大为无限场景保证。"]),
        "B19": ("确定性行为基线对照", ["Text-to-SQL 基线曾虚高 96.8 万元", "归档对照采用确定性行为基线，未调用真实模型。", "SQL 可以执行，不等于业务口径正确。"]),
        "B20": ("可信取数链路", ["澄清 → 结构化计划 → 只读执行 → 结果追溯", "指标、来源、版本和限制随答案保留。", "已演示接口的流程总结，非额外测试成绩。"]),
    }
    assert "37/37" in report and "67/67" in report and "967,893.21" in report
    title, lines = texts[sid]
    return card_html(title, "".join("<p>" + html.escape(t) + "</p>" for t in lines), source="来源：赛题二归档测试报告；金额按允许口径取近似值" if sid == "B19" else "来源：赛题二归档测试报告与已演示接口")


def csv_card(scene):
    path = ROOT / scene["action"]["source"]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    table = "<div class='tablewrap'><table>"
    for i, row in enumerate(rows):
        cell = "th" if i == 0 else "td"
        table += "<tr>" + "".join(f"<{cell}>{html.escape(value) if value else '—'}</{cell}>" for value in row) + "</tr>"
    table += "</table></div><p>未发生的事项与数据保持空白；横线仅表示空单元格。</p>"
    return card_html("执行台账模板" if scene["scene_id"] == "A20" else "数据复盘模板", table, source="来源：" + path.name + " · 原始 CSV 只读渲染")


class Recorder:
    def __init__(self, browser, name):
        self.browser, self.name = browser, name
        self.frames = WORK / name / "frames"
        self.frames.mkdir(parents=True, exist_ok=True)
        self.previews = HERE / "qa"
        self.previews.mkdir(exist_ok=True)
        self.manifest = {"video": name, "capture": "Playwright screenshots at 100ms", "mode": "rules" if name == "赛题二" else "not_applicable", "scenes": []}
        self.contexts = []
        self.frame_index = 0
        self.current = None
        self.start_time = 0

    async def new_page(self, width=1600, height=900):
        context = await self.browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1, locale="zh-CN")
        self.contexts.append(context)
        return await context.new_page()

    async def initialize(self):
        self.cards = await self.new_page()
        if self.name == "赛题二":
            context, self.app = await setup_app(self.browser)
            self.contexts.append(context)
        else:
            self.roadshow = await self.new_page(1280, 900)
            await self.roadshow.goto((ROOT / "赛题一/赛题一_运营方案路演.html").as_uri(), wait_until="domcontentloaded")
            await settle(self.roadshow, 1.5)
            self.desktop = await self.new_page(1280, 900)
            self.mobile = await self.new_page(390, 844)
            self.urls = online_urls()

    async def scroll_to(self, page, locator):
        await locator.scroll_into_view_if_needed(timeout=12000)
        await settle(page)

    async def position_at_top(self, page, locator):
        await locator.evaluate('''el => {
            el.scrollIntoView({block:'start',behavior:'instant'});
            let p=el.parentElement;
            while(p && !(p.scrollHeight>p.clientHeight+10 && /auto|scroll/.test(getComputedStyle(p).overflowY))) p=p.parentElement;
            (p || document.scrollingElement).scrollBy({top:-85,behavior:'smooth'});
        }''')
        await settle(page)

    async def action_b(self, scene):
        sid = scene["scene_id"]
        page = self.app
        if sid == "B03":
            await tab(page, "① 数据接入")
            await self.scroll_to(page, page.get_by_text("未上传文件时使用的内置数据集", exact=True))
        elif sid == "B04":
            history = page.get_by_text(re.compile(r"^数据集上传历史"))
            await history.click()
            await settle(page)
            await self.scroll_to(page, page.get_by_text("当前数据集（第 1 步·注册结果）", exact=True))
        elif sid == "B05":
            await ask(page, scene["action"]["question"])
        elif sid == "B06":
            await self.scroll_to(page, page.get_by_text("请选择：", exact=True))
        elif sid == "B07":
            await page.get_by_text("净销售额 —— 所选期间实付金额减去同期成功退款金额", exact=True).click()
            await settle(page)
            await page.get_by_role("button", name="提交选择", exact=True).click()
            await settle(page, 1.5)
            await page.get_by_text("净销售额 = 17,198,835.91", exact=True).wait_for(timeout=12000)
        elif sid == "B08":
            await tab(page, "④ 结果依据")
            plan = page.get_by_text("查看结构化查询计划（成员 2 生成）", exact=True)
            await plan.click()
            await settle(page)
            await self.position_at_top(page, plan)
            text = await page.locator("body").inner_text()
            ids = re.findall(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", text)
            if ids:
                save_json(HERE / "query_trace_evidence.json", http_json(API + "/v1/query-records/" + ids[0]))
        elif sid == "B09":
            await tab(page, "③ 智能取数")
            exact = page.get_by_text("净销售额 = 17,198,835.91", exact=True)
            await exact.wait_for(timeout=10000)
            await self.scroll_to(page, exact)
            await self.position_at_top(page, page.get_by_role("tabpanel", name="③ 智能取数").get_by_text("查询结果", exact=True))
        elif sid == "B10":
            await tab(page, "④ 结果依据")
            await self.scroll_to(page, page.get_by_text("所用指标口径", exact=True))
            await page.wait_for_timeout(4200)
            await self.scroll_to(page, page.get_by_text("查询记录（SQL）", exact=True))
        elif sid == "B11":
            await ask(page, scene["action"]["question"])
            await self.scroll_to(page, page.get_by_test_id("stAlert").filter(has_text="订单数据不能证明变化原因").last)
        elif sid == "B12":
            await tab(page, "④ 结果依据")
            cause = page.get_by_role("tabpanel", name="④ 结果依据").get_by_text("causal_reasoning_unsupported", exact=True)
            await cause.wait_for(timeout=10000)
            await self.scroll_to(page, cause)
            save_json(HERE / "refusal_evidence.json", {"mode": "rules", "question": "为什么9月净销售额下降了", "reason": "causal_reasoning_unsupported", "status": "insufficient_data", "visible_text": await page.locator("body").inner_text()})
        elif sid == "B13":
            await self.scroll_to(page, page.get_by_text("缺少的信息/数据", exact=True))
        elif sid == "B14":
            await settle(page)

    async def action_a(self, scene):
        sid, action = scene["scene_id"], scene["action"]
        if action["type"] == "scroll_to_heading":
            await self.position_at_top(self.roadshow, self.roadshow.get_by_role("heading", name=action["heading"], exact=True))
        elif sid == "A11":
            await self.position_at_top(self.roadshow, self.roadshow.get_by_role("heading", name=re.compile("做了什么 → 带来了什么 → 怎么放大")))
        elif sid == "A12":
            await self.scroll_to(self.roadshow, self.roadshow.get_by_role("heading", name="提交前自检", exact=True))
        elif sid in ("A13", "A14", "A15", "A16"):
            page = self.desktop if sid in ("A13", "A15") else self.mobile
            response = await page.goto(self.urls[action["url_key"]], wait_until="domcontentloaded", timeout=30000)
            assert response.status == 200
            await settle(page, 1.2)
            await page.wait_for_timeout(3800)
            # Observe actual page height and scroll slowly through the available content.
            height = await page.locator("body").evaluate("e => e.scrollHeight")
            viewport = page.viewport_size["height"]
            offset = min(height - viewport, 620 if sid in ("A13", "A15") else 900)
            if offset > 0:
                await page.mouse.wheel(0, offset / 2)
                await settle(page, 1.4)
                await page.mouse.wheel(0, offset / 2)
                await settle(page, 1.4)
        elif sid == "A19":
            await self.cards.wait_for_timeout(3500)
            await self.cards.mouse.wheel(0, 660)
            await settle(self.cards, 1.2)
            await self.cards.mouse.wheel(0, 450)
            await settle(self.cards, 1.2)
        elif sid == "A20":
            await self.cards.wait_for_timeout(3800)
            await self.cards.locator(".tablewrap").evaluate("e => e.scrollTo({left:650,behavior:'smooth'})")
            await settle(self.cards, 2.5)
            await self.cards.locator(".tablewrap").evaluate("e => e.scrollTo({left:e.scrollWidth,behavior:'smooth'})")
            await settle(self.cards, 1.2)

    async def choose_page(self, scene):
        sid, action = scene["scene_id"], scene["action"]
        if self.name == "赛题二":
            if sid in ("B01", "B02", "B15", "B16", "B17", "B18", "B19", "B20", "B21"):
                await open_generated(self.cards, sid, evidence_card(scene))
                return self.cards
            return self.app
        if action["type"] == "title_card":
            await open_generated(self.cards, sid, evidence_card(scene))
            return self.cards
        if sid in ("A13", "A15"):
            return self.desktop
        if sid in ("A14", "A16"):
            return self.mobile
        if action["type"] == "show_archived_image":
            image_path = ROOT / action["source"]
            content = card_html("归档线上物料实拍", f'<img src="{image_path.as_uri()}" style="width:{"750px" if sid == "A19" else "auto"};max-height:{"none" if sid == "A19" else "650px"}">', source="归档证据，不等同于当前实录或传播成绩")
            await open_generated(self.cards, sid, content)
            return self.cards
        if sid in ("A20", "A21"):
            await open_generated(self.cards, sid, csv_card(scene))
            return self.cards
        if sid in ("A22", "A23"):
            lines = ["试水首发 → 收集基线 → 调整渠道 → 留证归档 → 收口复盘", "每天依据真实发布和后台证据填写 CSV。", "轮值人名与固定填表时间仍待全队确认。"] if sid == "A22" else ["领取专属邀请码与链接", "完成制品上架", "真实走通注册到 fork 的全链路", "待办不写成已完成成果。"]
            await open_generated(self.cards, sid, card_html("后续真实执行计划" if sid == "A22" else "当前外部依赖", "".join("<p>" + html.escape(t) + "</p>" for t in lines), source="来源：D1 执行记录中的后续计划与待办"))
            return self.cards
        return self.roadshow

    def composite(self, raw, scene, local_frame):
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 28)
        bold = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 35)
        canvas = Image.new("RGB", SIZE, "#0a1526")
        draw = ImageDraw.Draw(canvas)
        accent = "#5aa5ff" if self.name == "赛题二" else "#ee8b61"
        draw.text((52, 20), "数桥 DataBridge" if self.name == "赛题二" else "DataClawHub · 运营方案", font=bold, fill="#ffffff")
        label = "现场规则模式 · 模拟数据" if self.name == "赛题二" else "模拟数据制品 · 运营方案展示"
        if scene["scene_id"] in ("B15", "B16", "B17", "B18", "B19", "B20"):
            label = "归档证据 · 非现场模型调用"
        draw.text((1320, 25), label, font=font, fill="#b8cce5")
        source = Image.open(io.BytesIO(raw)).convert("RGB")
        scale = min(1800 / source.width, 856 / source.height)
        source = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS)
        x, y = (SIZE[0] - source.width) // 2, 83 + (856 - source.height) // 2
        canvas.paste(source, (x, y))
        overlay = scene["action"].get("overlay_text", "")
        if overlay:
            bounds = draw.textbbox((0, 0), overlay, font=font)
            draw.text(((SIZE[0] - bounds[2]) // 2, 947), overlay, font=font, fill="#b8cce5")
        total = story(self.name)["total_duration_sec"]
        elapsed = self.frame_index / FPS
        draw.rectangle((0, 1068, int(SIZE[0] * elapsed / total), 1074), fill=accent)
        return canvas

    async def record(self, pickup=False):
        await self.initialize()
        all_scenes = story(self.name)["scenes"]
        scenes = all_scenes
        if pickup:
            assert self.name == "赛题二"
            self.manifest = json.loads((HERE / "capture_manifest_赛题二.json").read_text(encoding="utf-8"))
            self.manifest["pickup_note"] = "查询计划完整入画，结果明细局部放大；查询、计划、SQL 同次查询留证。"
            await ask(self.app, "9月销售额是多少")
            await self.app.get_by_text("净销售额 —— 所选期间实付金额减去同期成功退款金额", exact=True).click()
            await settle(self.app)
            await self.app.get_by_role("button", name="提交选择", exact=True).click()
            await settle(self.app, 1.5)
            scenes = [s for s in all_scenes if s["scene_id"] in ("B08", "B09", "B10")]
            self.frame_index = sum(s["duration_sec"] * FPS for s in all_scenes[:7])
        for scene in scenes:
            sid, duration = scene["scene_id"], scene["duration_sec"]
            page = await self.choose_page(scene)
            start = time.monotonic()
            action = asyncio.create_task(self.action_b(scene) if self.name == "赛题二" and page == self.app else self.action_a(scene) if self.name == "赛题一" else settle(page))
            count = duration * FPS
            first = self.frame_index
            for local_frame in range(count):
                if action.done() and action.exception():
                    raise action.exception()
                await asyncio.sleep(max(0, start + local_frame / FPS - time.monotonic()))
                screenshot_options = {"type": "jpeg", "quality": 88, "animations": "allow"}
                if sid == "B09" and action.done() and not action.exception():
                    panel = page.get_by_role("tabpanel", name="③ 智能取数")
                    table_box = await panel.get_by_test_id("stDataFrame").first.bounding_box()
                    caption_box = await page.get_by_text("净销售额 = 17,198,835.91", exact=True).bounding_box()
                    assert table_box and caption_box
                    y0 = max(0, table_box["y"] - 50)
                    screenshot_options["clip"] = {"x": table_box["x"], "y": y0,
                        "width": table_box["width"], "height": caption_box["y"] + caption_box["height"] + 20 - y0}
                raw = await page.screenshot(**screenshot_options)
                canvas = self.composite(raw, scene, local_frame)
                canvas.save(self.frames / f"frame_{self.frame_index:06d}.jpg", quality=90)
                if local_frame == max(0, count - 10):
                    canvas.save(self.previews / (sid + ".jpg"), quality=94)
                self.frame_index += 1
            await asyncio.wait_for(action, timeout=15)
            observed = await page.locator("body").inner_text()
            entry = {"scene_id": sid, "start_sec": first / FPS,
                "end_sec": self.frame_index / FPS, "frame_count": count, "page_url": page.url,
                "observed_text_sha256": hashlib.sha256(observed.encode()).hexdigest(),
                "mode": "rules" if self.name == "赛题二" else "not_applicable"}
            if pickup:
                index = next(i for i, s in enumerate(self.manifest["scenes"]) if s["scene_id"] == sid)
                self.manifest["scenes"][index] = entry
            else:
                self.manifest["scenes"].append(entry)
            save_json(HERE / ("capture_manifest_" + self.name + ".json"), self.manifest)
            log("[SCENE] " + self.name + " " + sid + " 完成")
        for context in self.contexts:
            await context.close()
        log("[MILESTONE] " + self.name + " 全部分镜录屏 完成")


async def record(name, pickup=False):
    from playwright.async_api import async_playwright
    environment()
    async with async_playwright() as p:
        browser, channel = await launch_browser(p)
        recorder = Recorder(browser, name)
        recorder.manifest["browser"] = channel
        await recorder.record(pickup=pickup)
        await browser.close()


def compose(name):
    environment()
    directory = WORK / name
    frames = directory / "frames"
    clips = directory / "clips"
    clips.mkdir(exist_ok=True)
    doc = story(name)
    ffmpeg = binary("ffmpeg")
    start_frame = 0
    for scene in doc["scenes"]:
        sid, count = scene["scene_id"], scene["duration_sec"] * FPS
        target = clips / ("scene_" + sid + ".mp4")
        video_filter = ["-vf", "fps=30"]
        if name == "赛题一":
            video_filter = ["-vf", "fps=30,drawbox=x=1280:y=15:w=620:h=58:color=0x0a1526:t=fill,drawtext=fontfile='C\\:/Windows/Fonts/msyh.ttc':text='模拟数据制品 · 运营方案展示':x=1280:y=25:fontcolor=0xb8cce5:fontsize=28"]
        run([ffmpeg, "-y", "-framerate", str(FPS), "-start_number", str(start_frame),
             "-i", frames / "frame_%06d.jpg", "-frames:v", str(count * 3), *video_filter,
             "-an", "-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "22",
             "-maxrate", "2200k", "-bufsize", "4400k", "-pix_fmt", "yuv420p", target], timeout=180)
        start_frame += count
        log("[ENCODE] " + sid + " scene encoded")
    concat = clips / "concat.txt"
    concat.write_text("".join("file 'scene_" + s["scene_id"] + ".mp4'\n" for s in doc["scenes"]), encoding="utf-8")
    visual = directory / "visual.mp4"
    run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat, "-c", "copy", visual])
    duration = doc["total_duration_sec"]
    audio = HERE / (name + "_配音.wav")
    srt = HERE / (name + "_演示视频.srt")
    soft = HERE / (name + "_演示视频_软字幕.mp4")
    hard = HERE / (name + "_演示视频_硬字幕.mp4")
    run([ffmpeg, "-y", "-i", visual, "-i", audio, "-i", srt,
         "-map", "0:v:0", "-map", "1:a:0", "-map", "2:0", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "128k", "-c:s", "mov_text", "-metadata:s:s:0", "language=zho",
         "-metadata:s:s:0", "title=中文", "-disposition:s:0", "default", "-t", str(duration),
         "-movflags", "+faststart", soft])
    # Relative filename avoids Windows drive-letter escaping in the subtitle filter.
    ass = directory / (name + "_字幕_v2.ass")
    write_subtitles_ass_v2(srt, ass)
    subtitle_filter = subtitle_filter_v2(ass)
    run([ffmpeg, "-y", "-i", visual, "-i", audio, "-map", "0:v:0", "-map", "1:a:0",
         "-vf", subtitle_filter, "-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "21",
         "-maxrate", "2200k", "-bufsize", "4400k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
         "-t", str(duration), "-movflags", "+faststart", hard], cwd=ass.parent, timeout=240)
    log("[MILESTONE] " + name + " 软字幕与硬字幕视频合成 完成")


def probe(path):
    return json.loads(run([binary("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", path]).stdout)


def parse_srt(text):
    parsed = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        start, end = lines[1].split(" --> ")
        def seconds(value):
            h, m, sec = value.replace(",", ".").split(":")
            return int(h) * 3600 + int(m) * 60 + float(sec)
        parsed.append({"start": seconds(start), "end": seconds(end), "text": "\n".join(lines[2:])})
    return parsed


def check():
    ffmpeg = binary("ffmpeg")
    report = {"user_approved_storyboards": True, "approval_message": "那你继续",
              "checks": [], "videos": [], "visual_review": "pending"}
    allowed = {"2", "3,492", "2,000", "9", "17,198,835.91", "37/37", "67/67", "0", "96.8"}
    for name in ("赛题二", "赛题一"):
        doc = story(name)
        raw = (HERE / ("storyboard_" + name + ".json")).read_text(encoding="utf-8")
        subtitle = (HERE / (name + "_演示视频.srt")).read_text(encoding="utf-8")
        assert not any(w in raw + subtitle for w in ("中国数联物流", "央企"))
        cues = parse_srt(subtitle)
        assert len(cues) == len(doc["scenes"])
        cursor = 0
        for scene, cue in zip(doc["scenes"], cues):
            assert cue == {"start": cursor, "end": cursor + scene["duration_sec"], "text": scene["subtitle_text"]}
            assert len(cue["text"]) <= 40
            hits = re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:/\d+|\.\d+)?", cue["text"])
            assert set(hits) <= allowed
            cursor += scene["duration_sec"]
        log("[PASS] " + name + " SRT 与分镜完全同轴；数字在白名单内；无禁用表述")
        for kind in ("软字幕", "硬字幕"):
            path = HERE / (name + "_演示视频_" + kind + ".mp4")
            info = probe(path)
            duration = float(info["format"]["duration"])
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
            assert duration <= 300 and abs(duration - cursor) < .2
            assert video["codec_name"] == "h264" and video["width"] >= 1280 and video["height"] >= 720
            assert audio["codec_name"] == "aac"
            assert path.stat().st_size < 100 * 1024 * 1024, "GitHub individual file limit"
            volume = run([ffmpeg, "-i", path, "-vn", "-af", "volumedetect", "-f", "null", "NUL"], timeout=90).stderr.decode("utf-8", errors="replace")
            mean = float(re.search(r"mean_volume: ([\-\d.]+) dB", volume).group(1))
            assert mean > -55
            if kind == "软字幕":
                assert any(s.get("codec_name") == "mov_text" for s in info["streams"])
                extracted = WORK / (name + "_embedded.srt")
                run([ffmpeg, "-y", "-i", path, "-map", "0:s:0", extracted])
                embedded = parse_srt(extracted.read_text(encoding="utf-8"))
                assert len(embedded) == len(cues)
                for expected, actual in zip(cues, embedded):
                    assert actual["text"] == expected["text"]
                    assert abs(actual["start"] - expected["start"]) < .05
                    assert abs(actual["end"] - expected["end"]) < .05
            report["videos"].append({"file": path.name, "duration_sec": duration,
                "width": video["width"], "height": video["height"], "video_codec": video["codec_name"],
                "audio_codec": audio["codec_name"], "mean_volume_db": mean,
                "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "subtitle_track": kind == "软字幕"})
            log(f"[PASS] {path.name}: {duration:.2f}s, {video['width']}x{video['height']}, H.264/AAC, mean={mean}dB")
        selected = ("B06", "B09", "B12") if name == "赛题二" else ("A03", "A14", "A20")
        cursor = 0
        samples = []
        for i, scene in enumerate(doc["scenes"]):
            if scene["scene_id"] in selected:
                stamp = cursor + scene["duration_sec"] * .75
                assert cues[i]["start"] <= stamp < cues[i]["end"]
                target = HERE / "qa" / (name + "_" + scene["scene_id"] + "_硬字幕.jpg")
                run([ffmpeg, "-y", "-ss", str(stamp), "-i", HERE / (name + "_演示视频_硬字幕.mp4"), "-frames:v", "1", "-q:v", "2", target])
                samples.append({"scene_id": scene["scene_id"], "time_sec": stamp, "cue_start": cues[i]["start"], "cue_end": cues[i]["end"], "image": "qa/" + target.name})
            cursor += scene["duration_sec"]
        report["checks"].append({"video": name, "three_subtitle_samples": samples, "timing": "PASS"})
        log("[PASS] " + name + " 抽查分镜字幕时间均在对应分镜内")
    capture = json.loads((HERE / "capture_manifest_赛题二.json").read_text(encoding="utf-8"))
    assert capture["mode"] == "rules" and all(s["mode"] == "rules" for s in capture["scenes"])
    log("[PASS] 赛题二实际录屏记录及分镜 JSON 均为 rules 模式")
    save_json(HERE / "验收报告.json", report)
    log("[MILESTONE] 视频编码、声音、字幕轨与时间轴自动验收 完成")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "preflight", "subtitles", "narrate", "record", "compose", "check"])
    parser.add_argument("--video", choices=["赛题二", "赛题一"], default="赛题二")
    parser.add_argument("--pickup", action="store_true", help="Replace the query-plan/detail/trace shots only")
    args = parser.parse_args()
    if args.command == "start":
        start_services()
    elif args.command == "preflight":
        asyncio.run(preflight())
    elif args.command == "subtitles":
        make_subtitles()
    elif args.command == "narrate":
        asyncio.run(narrate())
    elif args.command == "record":
        asyncio.run(record(args.video, pickup=args.pickup))
    elif args.command == "compose":
        compose(args.video)
    else:
        check()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("[ERROR] " + str(exc))
        raise
