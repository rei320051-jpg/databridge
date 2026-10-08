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


def run(args, timeout=90):
    result = subprocess.run([str(x) for x in args], capture_output=True,
                            creationflags=FLAGS, timeout=timeout)
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


if __name__ == "__main__":
    try:
        if "--audit" in sys.argv:
            audit()
        else:
            main()
            audit()
    except Exception as error:
        log(f"[BLOCKED] {error}")
        sys.exit(1)
