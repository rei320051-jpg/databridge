"""Add natural-neural narration variants without changing existing artifacts.

Uses the edge-tts skill's CLI with the project's selected Python interpreter.
Original storyboards, subtitle texts, video packets and tracked files are read-only.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import wave

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = HERE / "_work" / "natural_voice"
WORK.mkdir(parents=True, exist_ok=True)
EXPECTED_PYTHON = ROOT / "赛题二/.venv/Scripts/python.exe"
TOOLS = Path(os.environ["LOCALAPPDATA"]) / (
    "Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/"
    "ffmpeg-9.0.2-full_build/bin"
)
FFMPEG = TOOLS / "ffmpeg.exe"
FFPROBE = TOOLS / "ffprobe.exe"
GIT = Path("C:/Program Files/Git/cmd/git.exe")
VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "-8%"
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
SKILL_URL = "https://github.com/aahl/skills/tree/main/skills/edge-tts"


def log(text):
    print(text, flush=True)


def run(args, timeout=90, cwd=None):
    result = subprocess.run([str(x) for x in args], capture_output=True,
                            creationflags=FLAGS, timeout=timeout, cwd=cwd)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-2500:])
    return result.stdout


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe(path):
    return json.loads(run([FFPROBE, "-v", "error", "-show_streams", "-show_format",
                           "-of", "json", path]))


def duration(path):
    return float(probe(path)["format"]["duration"])


def packet_hash(path, kind):
    # Hash compressed packets, not container headers, to prove visuals/subtitles unchanged.
    return run([FFMPEG, "-v", "error", "-i", path, "-map", f"0:{kind}:0",
                "-c", "copy", "-f", "hash", "-hash", "sha256", "-"]).decode().strip()


def synthesize(scene):
    scene_id = scene["scene_id"]
    text = scene["subtitle_text"]
    raw = WORK / f"{scene_id}_{VOICE}.mp3"
    metadata = WORK / f"{scene_id}_tts.json"
    config = {"text": text, "voice": VOICE, "rate": RATE, "engine": "edge-tts"}
    cached = (raw.exists() and raw.stat().st_size > 1000 and metadata.exists()
              and json.loads(metadata.read_text(encoding="utf-8")) == config)
    if not cached:
        failures = []
        for attempt in range(2):
            try:
                run([sys.executable, "-m", "edge_tts", "--voice", VOICE,
                     f"--rate={RATE}", "--text", text, "--write-media", raw], timeout=45)
                if raw.stat().st_size <= 1000:
                    raise RuntimeError("empty TTS output")
                duration(raw)
                save_json(metadata, config)
                break
            except Exception as exc:
                failures.append(str(exc))
                if attempt == 1:
                    raise RuntimeError(f"{scene_id}: neural TTS failed; no SAPI fallback; "
                                       + " | ".join(failures)) from exc
                time.sleep(1)
    raw_duration = duration(raw)
    available = float(scene["duration_sec"]) - 1.0
    tempo = max(1.0, raw_duration / available)
    if tempo > 1.15:
        raise RuntimeError(f"{scene_id}: excessive tempo compression {tempo:.3f}; stop for review")
    pcm = WORK / f"{scene_id}_pcm.wav"
    filters = f"atempo={tempo:.7f},loudnorm=I=-18:TP=-1.5:LRA=11"
    run([FFMPEG, "-y", "-v", "error", "-i", raw, "-af", filters,
         "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", pcm])
    with wave.open(str(pcm), "rb") as wav:
        samples = wav.readframes(wav.getnframes())
        pcm_duration = wav.getnframes() / wav.getframerate()
    if pcm_duration > available + .04:
        raise RuntimeError(f"{scene_id}: narration exceeds its approved scene")
    return samples, {"scene_id": scene_id, "text": text,
                     "voice": VOICE, "rate": RATE, "raw_duration_sec": raw_duration,
                     "duration_sec": pcm_duration, "tempo": tempo, "raw_sha256": sha(raw)}


def replace(name, manifest):
    board_path = HERE / f"storyboard_{name}.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    old_subs = HERE / f"{name}_演示视频.srt"
    expected_duration = sum(scene["duration_sec"] for scene in board["scenes"])
    total_samples = round(expected_duration * 48000)
    audio = bytearray(total_samples * 2)
    cue_log = []
    scene_start = 0.0
    for index, scene in enumerate(board["scenes"], 1):
        samples, info = synthesize(scene)
        start = scene_start + .6
        offset = round(start * 48000) * 2
        audio[offset:offset + len(samples)] = samples
        info.update(start_sec=start, end_sec=start + info["duration_sec"],
                    scene_start_sec=scene_start, scene_end_sec=scene_start + scene["duration_sec"])
        cue_log.append(info)
        scene_start += scene["duration_sec"]
        log(f"[VOICE] {name} {index}/{len(board['scenes'])} {scene['scene_id']} "
            f"{info['duration_sec']:.2f}s tempo={info['tempo']:.3f}")
    audio_path = WORK / f"{name}_自然配音.wav"
    with wave.open(str(audio_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(audio)
    log(f"[MILESTONE] {name} 自然神经配音生成 完成")
    outputs = []
    for variant in ("软字幕", "硬字幕"):
        original = HERE / f"{name}_演示视频_{variant}.mp4"
        target = HERE / f"{name}_演示视频_自然配音_{variant}.mp4"
        command = [FFMPEG, "-y", "-v", "error", "-i", original, "-i", audio_path,
                   "-map", "0:v:0", "-map", "1:a:0"]
        if variant == "软字幕":
            command += ["-map", "0:s:0", "-c:s", "copy", "-metadata:s:s:0", "language=zho",
                        "-disposition:s:0", "default"]
        command += ["-map_metadata", "0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-t", str(expected_duration), "-movflags", "+faststart", target]
        run(command, timeout=120)
        details = probe(target)
        streams = details["streams"]
        video = next(s for s in streams if s["codec_type"] == "video")
        sound = next(s for s in streams if s["codec_type"] == "audio")
        checks = {
            "duration_within_limit": abs(float(details["format"]["duration"]) - expected_duration) < .1
                                     and expected_duration <= 300,
            "h264_and_aac": video["codec_name"] == "h264" and sound["codec_name"] == "aac",
            "resolution_1080p": video["width"] == 1920 and video["height"] == 1080,
            "visual_packets_unchanged": packet_hash(original, "v") == packet_hash(target, "v"),
        }
        if variant == "软字幕":
            subtitle = next(s for s in streams if s["codec_type"] == "subtitle")
            checks["soft_subtitle_preserved"] = subtitle["codec_name"] == "mov_text" and (
                packet_hash(original, "s") == packet_hash(target, "s"))
        result = subprocess.run([str(FFMPEG), "-hide_banner", "-i", str(target), "-vn",
                                 "-sn", "-af", "volumedetect", "-f", "null", "NUL"],
                                capture_output=True, creationflags=FLAGS, timeout=60)
        volume_log = result.stderr.decode("utf-8", errors="replace")
        found = re.search(r"mean_volume: ([-\d.]+) dB", volume_log)
        mean_db = float(found.group(1)) if found else None
        checks["audio_non_silent"] = result.returncode == 0 and mean_db is not None and mean_db > -45
        for check, passed in checks.items():
            log(f"[{'PASS' if passed else 'FAIL'}] {name} {variant}: {check}")
        if not all(checks.values()):
            raise RuntimeError(f"{target.name}: validation failed")
        outputs.append({"file": target.name, "sha256": sha(target), "duration_sec": expected_duration,
                        "mean_volume_db": mean_db, "checks": checks})
    new_subs = HERE / f"{name}_演示视频_自然配音.srt"
    shutil.copyfile(old_subs, new_subs)
    if sha(old_subs) != sha(new_subs):
        raise RuntimeError("Subtitle content changed")
    sample_cues = [cue_log[0], cue_log[len(cue_log) // 2], cue_log[-1]]
    time_ok = all(cue["scene_start_sec"] <= cue["start_sec"] < cue["end_sec"] <=
                  cue["scene_end_sec"] for cue in cue_log)
    if not time_ok:
        raise RuntimeError("Narration outside approved scene")
    record = {"mode": board.get("mode", "not_applicable"), "duration_sec": expected_duration,
              "storyboard_sha256": sha(board_path), "srt_sha256": sha(new_subs),
              "subtitle_text_and_timeline_unchanged": True, "all_voice_cues_within_scenes": time_ok,
              "sample_cues": sample_cues, "cues": cue_log, "outputs": outputs}
    manifest["videos"][name] = record
    save_json(HERE / "自然配音_验收报告.json", manifest)
    log(f"[MILESTONE] {name} 自然配音软硬字幕视频合成与自检 完成")


def main():
    if Path(sys.executable).resolve() != EXPECTED_PYTHON.resolve():
        raise RuntimeError("Use the originally selected interpreter only")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    log("[ENV] python=" + sys.executable)
    baseline = run([GIT, "diff", "--name-only", "HEAD"], timeout=20)
    if baseline.strip():
        raise RuntimeError("Existing tracked modifications: stop to preserve user files")
    tracked = run([GIT, "ls-files", "-z"], timeout=20).decode("utf-8").split("\0")
    original_hashes = {name: sha(ROOT / name) for name in tracked if name and (ROOT / name).is_file()}
    manifest = {"engine": "Microsoft Edge neural TTS", "voice": VOICE, "rate": RATE,
                "skill": SKILL_URL, "ai_generated_voice": True, "sapi_fallback": False,
                "python": sys.executable, "videos": {}}
    for name in ("赛题二", "赛题一"):
        replace(name, manifest)
    unchanged = all((ROOT / name).is_file() and sha(ROOT / name) == original_hash
                    for name, original_hash in original_hashes.items())
    manifest["all_preexisting_tracked_files_unchanged"] = unchanged
    save_json(HERE / "自然配音_验收报告.json", manifest)
    if not unchanged:
        raise RuntimeError("A preexisting tracked file changed")
    log("[PASS] 原有被跟踪文件、视频、分镜、字幕与 ZIP 均未修改")
    log("[MILESTONE] 两支自然配音替换视频 完成")


def audit():
    report_path = HERE / "自然配音_验收报告.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    allowed = {"2", "3,492", "2,000", "9", "17,198,835.91", "37/37", "67/67", "0", "96.8"}
    checks = {}
    for name in ("赛题二", "赛题一"):
        board = json.loads((HERE / f"storyboard_{name}.json").read_text(encoding="utf-8"))
        subtitles = (HERE / f"{name}_演示视频_自然配音.srt").read_text(encoding="utf-8")
        original_subtitles = (HERE / f"{name}_演示视频.srt").read_text(encoding="utf-8")
        text = "\n".join(scene["subtitle_text"] for scene in board["scenes"])
        numbers = set(re.findall(r"\d[\d,.]*(?:/\d+)?", text))
        checks[f"{name}_factual_numbers_whitelisted"] = numbers <= allowed
        checks[f"{name}_prohibited_word_scan"] = not any(word in text + subtitles for word in
                                                        ("中国数联物流", "央企"))
        checks[f"{name}_subtitles_identical"] = subtitles == original_subtitles
        checks[f"{name}_all_narration_text_verbatim"] = (
            [cue["text"] for cue in report["videos"][name]["cues"]] ==
            [scene["subtitle_text"] for scene in board["scenes"]])
        checks[f"{name}_three_subtitle_samples_in_scene"] = all(
            cue["scene_start_sec"] <= cue["start_sec"] < cue["end_sec"] <= cue["scene_end_sec"]
            for cue in report["videos"][name]["sample_cues"])
        if name == "赛题二":
            checks["赛题二_rules_mode_preserved"] = board["mode"] == "rules" and all(
                scene.get("mode") == "rules" for scene in board["scenes"])
        for variant in ("软字幕", "硬字幕"):
            original = HERE / f"{name}_演示视频_{variant}.mp4"
            target = HERE / f"{name}_演示视频_自然配音_{variant}.mp4"
            checks[f"{name}_{variant}_narration_actually_replaced"] = (
                packet_hash(original, "a") != packet_hash(target, "a"))
    for check, passed in checks.items():
        log(f"[{'PASS' if passed else 'FAIL'}] {check}")
    report["acceptance_checks"] = checks
    save_json(report_path, report)
    if not all(checks.values()):
        raise RuntimeError("Natural voice acceptance failed")


def render_v2(preview_only=False):
    """Compose only: never call synthesize(), record(), or rewrite a storyboard.

    Use the existing soft MP4 as the unburned video/AAC/subtitle source. This also
    works after obsolete SAPI MP4s were deleted. Copy AAC packets instead of
    regenerating or re-encoding narration. Stage both works before publication.
    """
    from video_pipeline import (SUBTITLE_STYLE_V2, parse_srt, subtitle_filter_v2,
                                subtitle_highlights_v2, write_subtitles_ass_v2)
    if Path(sys.executable).resolve() != EXPECTED_PYTHON.resolve():
        raise RuntimeError("Use the originally selected interpreter only")
    log("[ENV] python=" + sys.executable)
    render_work = HERE / "_work" / "subtitle_v2"
    render_work.mkdir(parents=True, exist_ok=True)
    report_path = HERE / "自然配音_验收报告.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    baseline_commit = run([GIT, "rev-parse", "HEAD"]).decode().strip()
    original_report_sha = sha(report_path)
    protected_paths = [HERE / f"storyboard_{name}.json" for name in ("赛题二", "赛题一")]
    protected_paths += [HERE / f"{name}_演示视频{suffix}.srt"
                        for name in ("赛题二", "赛题一") for suffix in ("", "_自然配音")]
    protected_paths += [HERE / f"capture_manifest_{name}.json" for name in ("赛题二", "赛题一")]
    protected_paths += list(WORK.glob("*.wav")) + list(WORK.glob("*.mp3"))
    protected_paths += [HERE / "自然配音_晓晓试听.mp3"]
    for name in ("赛题二", "赛题一"):
        protected_paths += [HERE / "_work" / name / "visual.mp4"]
        protected_paths += sorted((HERE / "_work" / name / "frames").glob("*.jpg"))
    protected_before = {path.relative_to(HERE).as_posix(): sha(path) for path in protected_paths}
    allowed = {"2", "3,492", "2,000", "9", "17,198,835.91", "37/37", "67/67", "0", "96.8"}
    samples = {"赛题二": {"B06": 67.5, "B09": 106.0, "B12": 145.0},
               "赛题一": {"A03": 29.0, "A14": 161.25, "A20": 231.25}}
    staged = []
    acceptance = {}
    for name in ("赛题二", "赛题一"):
        board = json.loads((HERE / f"storyboard_{name}.json").read_text(encoding="utf-8"))
        srt = HERE / f"{name}_演示视频_自然配音.srt"
        raw_srt = srt.read_text(encoding="utf-8-sig")
        cues = parse_srt(raw_srt)
        cursor = 0
        if len(cues) != len(board["scenes"]):
            raise RuntimeError("Subtitle count differs from storyboard")
        for scene, cue in zip(board["scenes"], cues):
            if cue != {"start": cursor, "end": cursor + scene["duration_sec"],
                       "text": scene["subtitle_text"]}:
                raise RuntimeError(f"{name}: subtitle text/time changed")
            cursor += scene["duration_sec"]
        text = "\n".join(cue["text"] for cue in cues)
        number_tokens = set(re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:/\d+|\.\d+)?", text))
        if not number_tokens <= allowed:
            raise RuntimeError(f"{name}: nonwhitelisted factual numbers")
        if any(word in raw_srt for word in ("中国数联物流", "央企")) or re.search(
                r"github\s*\.\s*com|github\s*地址|https?://", raw_srt, re.I):
            raise RuntimeError(f"{name}: prohibited word or URL in SRT")
        if name == "赛题二":
            capture = json.loads((HERE / f"capture_manifest_{name}.json").read_text(encoding="utf-8"))
            if not (board["mode"] == capture["mode"] == "rules" and
                    all(scene["mode"] == "rules" for scene in board["scenes"]) and
                    all(scene["mode"] == "rules" for scene in capture["scenes"])):
                raise RuntimeError("Recorded Agent mode differs from rules")
        ass = render_work / f"{name}_字幕_v2.ass"
        write_subtitles_ass_v2(srt, ass)
        ass_events = [line for line in ass.read_text(encoding="utf-8").splitlines()
                      if line.startswith("Dialogue:")]
        restored_text = [re.sub(r"\{[^}]*\}", "", line.split(",", 9)[9]).replace(r"\N", "\n")
                         for line in ass_events]
        if restored_text != [cue["text"] for cue in cues]:
            raise RuntimeError("ASS markup changed visible wording")
        soft = HERE / f"{name}_演示视频_自然配音_软字幕.mp4"
        hard = HERE / f"{name}_演示视频_自然配音_硬字幕.mp4"
        video_hash = packet_hash(soft, "v")
        audio_hash = packet_hash(soft, "a")
        subtitle_hash = packet_hash(soft, "s")
        visual_source = HERE / "_work" / name / "visual.mp4"
        if packet_hash(visual_source, "v") != video_hash:
            raise RuntimeError("Soft source does not match archived unburned footage")
        if preview_only:
            scene_id = "B09" if name == "赛题二" else "A03"
            stamp = samples[name][scene_id]
            preview = render_work / f"{name}_{scene_id}_样式预览.jpg"
            run([FFMPEG, "-y", "-v", "error", "-i", soft,
                 "-vf", subtitle_filter_v2(ass), "-ss", str(stamp),
                 "-frames:v", "1", "-q:v", "2", preview], cwd=render_work, timeout=90)
            log("[PREVIEW] " + str(preview))
            continue
        staged_soft = render_work / soft.name
        staged_hard = render_work / hard.name
        staged_srt = render_work / srt.name
        # Soft subtitles stay removable; mov_text cannot guarantee ASS backgrounds,
        # outlines or per-word colour across players. Keep their packets/timeline exact.
        run([FFMPEG, "-y", "-v", "error", "-i", soft,
             "-map", "0:v:0", "-map", "0:a:0", "-map", "0:s:0", "-c", "copy",
             "-map_metadata", "0", "-metadata", "comment=Subtitle rendering v2; original soft subtitle timeline",
             "-metadata:s:s:0", "language=zho", "-disposition:s:0", "default",
             "-movflags", "+faststart", staged_soft])
        shutil.copyfile(srt, staged_srt)
        # Render from UNBURNED soft footage, never burn a second caption over old captions.
        run([FFMPEG, "-y", "-v", "error", "-i", soft,
             "-map", "0:v:0", "-map", "0:a:0", "-vf", subtitle_filter_v2(ass),
             "-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "19",
             "-maxrate", "3500k", "-bufsize", "7000k", "-pix_fmt", "yuv420p",
             "-c:a", "copy", "-t", str(cursor),
             "-metadata", "comment=Subtitle rendering v2; 40px white, gold emphasis, 70 percent black bar",
             "-movflags", "+faststart", staged_hard], cwd=render_work, timeout=300)
        log(f"[MILESTONE] {name} v2 字幕重合成 完成")
        outputs = []
        for variant, path in (("软字幕", staged_soft), ("硬字幕", staged_hard)):
            details = probe(path)
            streams = details["streams"]
            video = next(stream for stream in streams if stream["codec_type"] == "video")
            sound = next(stream for stream in streams if stream["codec_type"] == "audio")
            checks = {"duration_within_limit": abs(float(details["format"]["duration"]) - cursor) < .1
                                               and cursor <= 300,
                      "h264_and_aac": video["codec_name"] == "h264" and sound["codec_name"] == "aac",
                      "resolution_1080p": video["width"] == 1920 and video["height"] == 1080,
                      "narration_aac_packets_unchanged": packet_hash(path, "a") == audio_hash,
                      "github_file_size_limit": path.stat().st_size < 100 * 1024 * 1024}
            if variant == "软字幕":
                checks["visual_packets_unchanged"] = packet_hash(path, "v") == video_hash
                checks["soft_subtitle_packets_unchanged"] = packet_hash(path, "s") == subtitle_hash
                extracted = render_work / f"{name}_内嵌字幕复核.srt"
                run([FFMPEG, "-y", "-v", "error", "-i", path, "-map", "0:s:0", extracted])
                checks["embedded_srt_text_and_timeline_unchanged"] = (
                    parse_srt(extracted.read_text(encoding="utf-8-sig")) == cues)
                checks["mov_text_track_exists"] = any(s.get("codec_name") == "mov_text" for s in streams)
            result = subprocess.run([str(FFMPEG), "-hide_banner", "-i", str(path), "-vn", "-sn",
                                     "-af", "volumedetect", "-f", "null", "NUL"],
                                    capture_output=True, creationflags=FLAGS, timeout=60)
            found = re.search(r"mean_volume: ([-\d.]+) dB", result.stderr.decode("utf-8", errors="replace"))
            mean_db = float(found.group(1)) if found else None
            checks["audio_non_silent"] = result.returncode == 0 and mean_db is not None and mean_db > -45
            if not all(checks.values()):
                raise RuntimeError(f"{path.name}: validation failed {checks}")
            outputs.append({"file": path.name, "sha256": sha(path), "bytes": path.stat().st_size,
                            "duration_sec": float(details["format"]["duration"]), "mean_volume_db": mean_db,
                            "width": video["width"], "height": video["height"],
                            "video_codec": video["codec_name"], "audio_codec": sound["codec_name"],
                            "subtitle_track": variant == "软字幕", "checks": checks,
                            "audio_packet_sha256": audio_hash})
            for key in checks:
                log(f"[PASS] {name} {variant}: {key}")
        # Lossy H.264 encoding may alter pixels slightly outside the changed subtitle band.
        ssim = subprocess.run([str(FFMPEG), "-hide_banner", "-i", str(soft), "-i", str(staged_hard),
                               "-filter_complex", "[0:v]crop=1920:980:0:0[a];[1:v]crop=1920:980:0:0[b];[a][b]ssim",
                               "-an", "-f", "null", "NUL"], capture_output=True,
                              creationflags=FLAGS, timeout=120)
        matched = re.search(r"All:([\d.]+)", ssim.stderr.decode("utf-8", errors="replace"))
        outside_ssim = float(matched.group(1)) if matched else None
        if ssim.returncode or outside_ssim is None or outside_ssim < .99:
            raise RuntimeError(f"{name}: footage changed outside subtitle strip")
        qa = []
        for scene_id, stamp in samples[name].items():
            scene_index = next(index for index, scene in enumerate(board["scenes"]) if scene["scene_id"] == scene_id)
            cue = cues[scene_index]
            if not cue["start"] <= stamp < cue["end"]:
                raise RuntimeError("QA frame is outside its subtitle cue")
            image_name = f"{name}_{scene_id}_硬字幕.jpg"
            qa_stage = render_work / image_name
            run([FFMPEG, "-y", "-v", "error", "-ss", str(stamp), "-i", staged_hard,
                 "-frames:v", "1", "-q:v", "2", qa_stage])
            qa.append({"scene_id": scene_id, "time_sec": stamp, "cue_start": cue["start"],
                       "cue_end": cue["end"], "text": cue["text"], "image": "qa/" + image_name,
                       "image_sha256": sha(qa_stage), "timing_check": "PASS"})
            staged.append((qa_stage, HERE / "qa" / image_name))
        record = report["videos"][name]
        record.update(render_version="v2", outputs=outputs, qa_samples=qa,
                      source_video_packet_sha256=video_hash, source_audio_packet_sha256=audio_hash,
                      source_soft_subtitle_packet_sha256=subtitle_hash,
                      outside_subtitle_band_ssim=outside_ssim,
                      ass_markup_preserves_text=True, srt_sha256=sha(srt),
                      subtitle_text_and_timeline_unchanged=True,
                      emphasis_spans=[{"scene_id": scene["scene_id"], "text": cue["text"],
                                       "highlighted": subtitle_highlights_v2(cue["text"])}
                                      for scene, cue in zip(board["scenes"], cues)
                                      if subtitle_highlights_v2(cue["text"])])
        acceptance.update({f"{name}_factual_numbers_whitelisted": True,
                           f"{name}_prohibited_word_and_url_scan": True,
                           f"{name}_srt_text_and_timeline_unchanged": True,
                           f"{name}_narration_not_regenerated": True,
                           f"{name}_three_qa_frames_in_cues": True})
        staged.extend([(staged_soft, soft), (staged_hard, hard), (staged_srt, srt)])
        log(f"[MILESTONE] {name} v2 字幕、响度、时间轴与抽帧自检 完成")
    if any(sha(HERE / name) != checksum for name, checksum in protected_before.items()):
        raise RuntimeError("Protected footage, storyboard, SRT or narration changed")
    if preview_only:
        log("[PASS] 样式预览完成；分镜、素材、配音和 SRT 均未改动")
        return
    report["render_version"] = "v2"
    report["visual_review"] = {"status": "pending", "frame_count": 6,
                               "note": "Inspect the six newly exported QA images before marking PASS."}
    report["subtitle_style"] = SUBTITLE_STYLE_V2
    report["render_scope"] = "compose/burn-in only; reuse existing frames, unburned footage, AAC voice and subtitle timeline"
    report["style_applies_to"] = "hard-subtitle MP4; soft MP4 preserves original removable mov_text packets"
    report["soft_subtitle_style_note"] = "mov_text/SRT appearance is player-dependent; colour, outline and strip are guaranteed only in hard-subtitle MP4"
    report["baseline_commit"] = baseline_commit
    report["baseline_report_sha256"] = original_report_sha
    report["previous_generation_invariance_note"] = "Historical original-voice generation protected tracked files; this authorized v2 changes rendering artifacts only."
    report.pop("all_preexisting_tracked_files_unchanged", None)
    report["acceptance_checks"] = acceptance | {"赛题二_rules_mode_preserved": True,
                                               "all_storyboards_footage_voice_and_srt_unchanged": True}
    report["protected_input_summary"] = {
        "file_count": len(protected_before), "frame_count": sum("/frames/" in name for name in protected_before),
        "aggregate_sha256": hashlib.sha256(json.dumps(protected_before, sort_keys=True,
                                                     ensure_ascii=False).encode()).hexdigest(),
        "all_unchanged_after_render": True,
        "storyboard_srt_and_full_voice_sha256": {name: checksum for name, checksum in protected_before.items()
                                                if "storyboard_" in name or name.endswith(".srt") or
                                                name.endswith("_自然配音.wav")},
    }
    for source, target in staged:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
    save_json(report_path, report)
    log("[PASS] 不重录、不生成配音、不改文案、不改 SRT 或软字幕时间轴")
    log("[MILESTONE] 两支视频 v2 字幕增强与六张 QA 更新 完成")


if __name__ == "__main__":
    try:
        if "--compose-v2" in sys.argv or "--preview-v2" in sys.argv:
            render_v2(preview_only="--preview-v2" in sys.argv)
        elif "--audit" in sys.argv:
            audit()
        else:
            main()
            audit()
    except Exception as error:
        log(f"[BLOCKED] {error}")
        sys.exit(1)
