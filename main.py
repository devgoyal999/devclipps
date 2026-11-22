# -*- coding: utf-8 -*-
"""
DEV AI CLIPPER PRO (v2.0)
An advanced AI-powered desktop tool for converting long videos into viral Shorts, Reels, and TikToks.
Features:
- YouTube and Local Video Import
- High-speed transcription with Faster-Whisper (Word-level timestamps)
- Intelligent Virality & Highlight Detection (Speech density, Hook words in Hindi & English, Questions, Pacing)
- Animated / Word-by-Word Highlighted Captions (.ass & .srt) in MrBeast, Hormozi, Neon, and Minimal styles
- Smart Reframing (9:16 Vertical with Blurred Background or Smart Crop, 1:1 Square, 16:9)
- Built-in Video Preview Player (QtMultimedia)
- Individual and Batch Clip Export (1080p / 4K)
"""

import sys
import os
import re
import json
import shutil
import subprocess
import tempfile
import threading
import math
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer, QSize
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QFileDialog, QComboBox, QProgressBar, QTextEdit,
    QListWidget, QListWidgetItem, QMessageBox, QDoubleSpinBox, QSpinBox,
    QGroupBox, QFormLayout, QSplitter, QFrame, QSlider, QScrollArea,
    QSizePolicy, QTabWidget
)
from PySide6.QtGui import QFont, QColor, QPalette, QCursor, QIcon
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

APP_NAME = "DEV AI CLIPPER PRO"
ROOT_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = ROOT_DIR / "projects"
EXPORTS_DIR = ROOT_DIR / "exports"
TEMP_DIR = ROOT_DIR / "temp"

for directory in (PROJECTS_DIR, EXPORTS_DIR, TEMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------
# Utilities & System Checks
# ---------------------------------------------------------

def get_ffmpeg():
    return shutil.which("ffmpeg")

def get_ffprobe():
    return shutil.which("ffprobe")

def run_command(cmd, log_callback=None):
    """Executes a command and raises RuntimeError with clear error if failed."""
    if log_callback:
        log_callback(f"[CMD] {' '.join(str(c) for c in cmd)}")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "Command failed").strip()
        raise RuntimeError(err[-2000:])
    return proc.stdout

def probe_video_info(video_path: Path) -> Dict[str, Any]:
    ffprobe = get_ffprobe()
    if not ffprobe:
        raise RuntimeError("FFprobe nahi mila! FFmpeg install karke PATH me add karein.")
    cmd = [
        ffprobe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path)
    ]
    out = run_command(cmd)
    data = json.loads(out)
    
    duration = 0.0
    if "format" in data and "duration" in data["format"]:
        duration = float(data["format"]["duration"])
    elif "streams" in data and len(data["streams"]) > 0 and "duration" in data["streams"][0]:
        duration = float(data["streams"][0]["duration"])
        
    width = 1920
    height = 1080
    if "streams" in data and len(data["streams"]) > 0:
        s = data["streams"][0]
        width = int(s.get("width", 1920))
        height = int(s.get("height", 1080))
        
    return {"duration": duration, "width": width, "height": height}

def format_timestamp_hms(seconds: float) -> str:
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    return f"{h:02d}:{m:02d}:{sec:02d}" if h > 0 else f"{m:02d}:{sec:02d}"

def format_timestamp_ass(seconds: float) -> str:
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    cs = int(round((s - int(s)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h:01d}:{m:02d}:{sec:02d}.{cs:02d}"

def format_timestamp_srt(seconds: float) -> str:
    s = max(0.0, float(seconds))
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def escape_ffmpeg_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")

# ---------------------------------------------------------
# YouTube Importer
# ---------------------------------------------------------

def download_youtube_video(url: str, output_dir: Path, progress_cb, status_cb) -> str:
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp install nahi hai. Pip se install karein.")

    status_cb("Connecting to YouTube...")
    progress_cb(5)

    cookie_file = ROOT_DIR / "cookies.txt.txt"
    if not cookie_file.exists():
        cookie_file = ROOT_DIR / "cookies.txt"

    def ytdl_hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                pct = int(min(98, 5 + (downloaded / total) * 90))
                progress_cb(pct)
            speed = d.get("speed")
            speed_str = f" ({speed/1024/1024:.1f} MB/s)" if speed else ""
            status_cb(f"Downloading video...{speed_str}")
        elif d.get("status") == "finished":
            status_cb("Merging video & audio streams...")

    ydl_opts = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(output_dir / "%(title).80s [%(id)s].%(ext)s"),
        "progress_hooks": [ytdl_hook],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if cookie_file.exists():
        ydl_opts["cookiefile"] = str(cookie_file)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        target_path = Path(filename)
        if not target_path.exists():
            candidates = list(output_dir.glob(target_path.stem + ".*"))
            if candidates:
                target_path = candidates[0]
            else:
                raise RuntimeError("Downloaded file locate nahi hui.")

    progress_cb(100)
    status_cb("YouTube download complete!")
    return str(target_path)

# ---------------------------------------------------------
# Transcription Engine (Faster-Whisper)
# ---------------------------------------------------------

def extract_audio_wav(video_path: Path, output_wav: Path):
    ffmpeg = get_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg nahi mila!")
    cmd = [
        ffmpeg, "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(output_wav)
    ]
    run_command(cmd)

def transcribe_audio(video_path: Path, language: str, model_size: str, progress_cb, status_cb) -> Dict[str, Any]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper install nahi hai.")

    status_cb("Extracting clean 16kHz audio with FFmpeg...")
    progress_cb(5)
    temp_wav = TEMP_DIR / f"{video_path.stem}_audio.wav"
    try:
        extract_audio_wav(video_path, temp_wav)
        status_cb(f"Loading Whisper model ({model_size}) on CPU...")
        progress_cb(15)

        # CPU int8 quantization gives great speed without GPU
        model = WhisperModel(model_size, device="cpu", compute_type="int8")

        lang = None
        if language == "Hindi":
            lang = "hi"
        elif language == "English":
            lang = "en"
        elif language != "Auto Detect":
            lang = language.lower()[:2]

        status_cb("Transcribing audio & generating word timestamps...")
        progress_cb(25)

        # First try with standard VAD
        segments_generator, info = model.transcribe(
            str(temp_wav),
            language=lang,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=600)
        )
        segments_list = []
        for i, s in enumerate(segments_generator):
            words = []
            if s.words:
                for w in s.words:
                    words.append({"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()})
            segments_list.append({
                "id": i,
                "start": round(s.start, 2),
                "end": round(s.end, 2),
                "text": s.text.strip(),
                "words": words
            })
            progress_cb(min(90, 25 + (i * 2)))

        # Fallback if VAD dropped everything (e.g. mobile/quiet audio)
        if len(segments_list) == 0:
            status_cb("Retrying without VAD filter to capture soft audio...")
            segments_generator, info = model.transcribe(
                str(temp_wav),
                language=lang,
                word_timestamps=True,
                vad_filter=False
            )
            for i, s in enumerate(segments_generator):
                words = []
                if s.words:
                    for w in s.words:
                        words.append({"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()})
                segments_list.append({
                    "id": i,
                    "start": round(s.start, 2),
                    "end": round(s.end, 2),
                    "text": s.text.strip(),
                    "words": words
                })

        progress_cb(95)
        status_cb("Transcription complete!")
        return {"language": info.language, "segments": segments_list}
    finally:
        if temp_wav.exists():
            try:
                temp_wav.unlink()
            except Exception:
                pass

# ---------------------------------------------------------
# Virality & Highlight Detection Algorithm
# ---------------------------------------------------------

HOOK_KEYWORDS_EN = [
    "secret", "never", "always", "how to", "why", "truth", "crazy", "insane",
    "stop", "mistake", "warning", "reveal", "check this out", "watch this",
    "unbelievable", "huge", "best", "worst", "gameplay", "challenge", "wait",
    "omg", "shocking", "hacks", "trick", "win", "lose", "died", "money"
]

HOOK_KEYWORDS_HI = [
    "लेकिन", "क्योंकि", "अगर", "सच", "रहस्य", "सीक्रेट", "देखो", "सुनो",
    "सबसे बड़ा", "गलती", "हैरान", "जानते हो", "खतरनाक", "ध्यान से", "कभी मत",
    "ये क्या हुआ", "चलो देखते हैं", "भाई साहब", "विश्वास नहीं", "खतरा", "रुपये"
]

def generate_clip_title(text: str) -> str:
    clean = re.sub(r"[^\w\s\u0900-\u097F]", "", text).strip()
    words = clean.split()
    if not words:
        return "🔥 Viral Highlight"
    snippet = " ".join(words[:6])
    if len(words) > 6:
        snippet += "..."
    return snippet

def score_segment_window(text: str, duration: float, words_count: int, is_opening: bool = False) -> float:
    score = 65.0  # Base score
    lower = text.lower()
    
    # 1. Pacing & Speech Density (words per second)
    wps = words_count / max(1.0, duration)
    if 2.2 <= wps <= 4.5:
        score += 15.0
    elif wps > 4.5:
        score += 8.0
    else:
        score += 5.0
        
    # 2. Hook Keywords
    matched_hooks = 0
    for kw in HOOK_KEYWORDS_EN:
        if kw in lower:
            matched_hooks += 1
    for kw in HOOK_KEYWORDS_HI:
        if kw in text:
            matched_hooks += 1
    score += min(18.0, matched_hooks * 6.0)

    # 3. Questions / Curiosity Punctuation
    q_count = text.count("?")
    ex_count = text.count("!")
    score += min(10.0, q_count * 5.0 + ex_count * 3.0)

    # 4. Opening bonus
    if is_opening:
        score += 4.0

    return min(99.0, max(68.0, round(score, 1)))

def find_optimal_clips(segments: List[Dict[str, Any]], total_duration: float, target_duration: int, max_clips: int) -> List[Dict[str, Any]]:
    """
    Sliding window & sentence aggregation clipper.
    Aggregates consecutive transcription segments to reach target_duration cleanly.
    """
    if not segments:
        # Fallback if no speech: split total duration into highlights
        interval = max(15.0, min(total_duration / max(1, max_clips), float(target_duration)))
        clips = []
        cur = 0.0
        idx = 1
        while cur + interval <= total_duration and idx <= max_clips:
            clips.append({
                "id": idx,
                "title": f"Highlight {idx} (Gameplay/Visual)",
                "start": round(cur, 1),
                "end": round(cur + interval, 1),
                "duration": round(interval, 1),
                "score": 85.0,
                "text": "Visual highlight moment"
            })
            cur += interval * 1.5
            idx += 1
        return clips

    # Combine consecutive segments into candidate windows
    candidates = []
    n = len(segments)
    
    for i in range(n):
        start_time = segments[i]["start"]
        collected_text = []
        collected_words = 0
        end_time = start_time
        
        for j in range(i, n):
            seg = segments[j]
            collected_text.append(seg["text"])
            collected_words += len(seg.get("words", []) or seg["text"].split())
            end_time = seg["end"]
            dur = end_time - start_time
            
            # Check if duration meets target threshold
            if dur >= target_duration * 0.85:
                full_text = " ".join(collected_text)
                score = score_segment_window(full_text, dur, collected_words, is_opening=(i == 0))
                title = generate_clip_title(full_text)
                candidates.append({
                    "start": round(start_time, 1),
                    "end": round(end_time, 1),
                    "duration": round(dur, 1),
                    "score": score,
                    "title": title,
                    "text": full_text
                })
                break
            elif dur > target_duration * 1.3:
                break

    # Sort candidates by score descending
    candidates.sort(key=lambda c: c["score"], reverse=True)

    # Greedy non-overlapping selection
    selected = []
    for c in candidates:
        overlap = False
        for s in selected:
            # If overlap > 30% of clip duration, skip
            latest_start = max(c["start"], s["start"])
            earliest_end = min(c["end"], s["end"])
            overlap_time = max(0.0, earliest_end - latest_start)
            if overlap_time > 8.0:
                overlap = True
                break
        if not overlap:
            selected.append(c)
        if len(selected) >= max_clips:
            break

    # Sort selected clips chronologically
    selected.sort(key=lambda c: c["start"])
    for idx, c in enumerate(selected, 1):
        c["id"] = idx

    return selected

# ---------------------------------------------------------
# Subtitles Engine (SRT & Animated ASS)
# ---------------------------------------------------------

def generate_clip_srt(segments: List[Dict[str, Any]], clip_start: float, clip_end: float, out_path: Path):
    """Generates standard SRT with timestamps shifted by -clip_start."""
    lines = []
    counter = 1
    for seg in segments:
        s_start = seg["start"]
        s_end = seg["end"]
        if s_end <= clip_start or s_start >= clip_end:
            continue
        rel_start = max(0.0, s_start - clip_start)
        rel_end = min(clip_end - clip_start, s_end - clip_start)
        if rel_end - rel_start < 0.2:
            continue
        lines.append(f"{counter}\n{format_timestamp_srt(rel_start)} --> {format_timestamp_srt(rel_end)}\n{seg['text']}\n")
        counter += 1

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def generate_clip_ass(segments: List[Dict[str, Any]], clip_start: float, clip_end: float, out_path: Path, style_name: str = "MrBeast"):
    """
    Generates rich ASS subtitles with word-by-word active highlight (Alex Hormozi / MrBeast style).
    All timestamps are shifted by -clip_start so they align with the exported clip!
    """
    # ASS Header
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""

    if style_name == "MrBeast":
        # Big punchy yellow highlight, heavy black outline
        # &H0000FFFF is pure Yellow in ASS BGR, &H00FFFFFF is White
        header += "Style: Default,Arial Black,58,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,2,50,50,280,1\n"
        highlight_color = r"{\c&H0000FFFF&}"  # Vibrant Yellow
        base_color = r"{\c&H00FFFFFF&}"
    elif style_name == "Hormozi":
        # Alex Hormozi Neon Green active word highlight
        # &H0033FF55 is Neon Lime/Green
        header += "Style: Default,Impact,64,&H00FFFFFF,&H0033FF55,&H00000000,&HB0000000,-1,0,0,0,105,105,0,0,1,7,2,2,40,40,320,1\n"
        highlight_color = r"{\c&H0033FF55&}"  # Neon Green
        base_color = r"{\c&H00FFFFFF&}"
    elif style_name == "Cyberpunk":
        # Cyan text with Magenta/Purple outline
        header += "Style: Default,Arial Black,56,&H00FFFF00,&H00FF00FF,&H00500050,&H80000000,-1,0,0,0,100,100,0,0,1,5,3,2,50,50,280,1\n"
        highlight_color = r"{\c&H00FF00FF&}"  # Magenta
        base_color = r"{\c&H00FFFF00&}"       # Cyan
    else:  # Minimal Clean
        header += "Style: Default,Arial,48,&H00FFFFFF,&H00AAAAAA,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,50,50,240,1\n"
        highlight_color = r"{\c&H00FFFFFF&}"
        base_color = r"{\c&H00CCCCCC&}"

    header += "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"

    events = []
    # Collect all words inside clip boundary
    clip_words = []
    for seg in segments:
        for w in seg.get("words", []):
            if w["end"] > clip_start and w["start"] < clip_end:
                clip_words.append({
                    "start": max(0.0, w["start"] - clip_start),
                    "end": min(clip_end - clip_start, w["end"] - clip_start),
                    "word": w["word"]
                })

    if clip_words:
        # Group words into 3-4 word phrases for punchy dynamic captions
        chunk_size = 3
        for idx in range(0, len(clip_words), chunk_size):
            chunk = clip_words[idx:idx + chunk_size]
            chunk_start = chunk[0]["start"]
            chunk_end = chunk[-1]["end"]
            if chunk_end <= chunk_start:
                continue

            # Produce word-highlight lines for each active word in this chunk
            for active_i, active_w in enumerate(chunk):
                w_start = active_w["start"]
                w_end = active_w["end"]
                if w_end <= w_start:
                    continue
                # Construct formatted text
                parts = []
                for p_i, pw in enumerate(chunk):
                    if p_i == active_i:
                        parts.append(f"{highlight_color}{pw['word'].upper()}{base_color}")
                    else:
                        parts.append(pw["word"].upper())
                formatted_text = " ".join(parts)
                events.append(f"Dialogue: 0,{format_timestamp_ass(w_start)},{format_timestamp_ass(w_end)},Default,,0,0,0,,{formatted_text}")
    else:
        # Fallback to segment-level lines if words were unavailable
        for seg in segments:
            if seg["end"] <= clip_start or seg["start"] >= clip_end:
                continue
            r_s = max(0.0, seg["start"] - clip_start)
            r_e = min(clip_end - clip_start, seg["end"] - clip_start)
            if r_e > r_s:
                txt = seg["text"].upper()
                events.append(f"Dialogue: 0,{format_timestamp_ass(r_s)},{format_timestamp_ass(r_e)},Default,,0,0,0,,{txt}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")

# ---------------------------------------------------------
# FFmpeg Render Engine (Reframing & Video Export)
# ---------------------------------------------------------

def render_video_clip(
    source_video: Path,
    start_sec: float,
    end_sec: float,
    output_path: Path,
    aspect_ratio: str = "9:16",
    framing_mode: str = "Blurred Background",
    resolution_label: str = "1080p",
    ass_subtitle_file: Optional[Path] = None,
    progress_cb = None,
    status_cb = None
) -> str:
    ffmpeg = get_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg nahi mila!")

    if status_cb:
        status_cb("Preparing render parameters...")

    # Dimensions
    if aspect_ratio == "9:16":
        out_w, out_h = (1080, 1920) if resolution_label == "1080p" else (2160, 3840)
    elif aspect_ratio == "1:1":
        out_w, out_h = (1080, 1080) if resolution_label == "1080p" else (2160, 2160)
    else:  # 16:9
        out_w, out_h = (1920, 1080) if resolution_label == "1080p" else (3840, 2160)

    # Build video filter graph
    duration = end_sec - start_sec

    if aspect_ratio == "9:16":
        if framing_mode == "Blurred Background":
            # Best TikTok / Shorts framing: Zoomed blurred background + centered crisp video
            vf = (
                f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                f"crop={out_w}:{out_h},boxblur=25:5[bg];"
                f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vbase]"
            )
        elif framing_mode == "Left Crop":
            vf = f"[0:v]scale=-1:{out_h},crop={out_w}:{out_h}:0:0,setsar=1[vbase]"
        elif framing_mode == "Right Crop":
            vf = f"[0:v]scale=-1:{out_h},crop={out_w}:{out_h}:(in_w-{out_w}):0,setsar=1[vbase]"
        else:  # Center Crop
            vf = f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setsar=1[vbase]"
    elif aspect_ratio == "1:1":
        vf = f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setsar=1[vbase]"
    else:  # 16:9
        vf = f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[vbase]"

    # Subtitles burning
    final_v_label = "[vbase]"
    if ass_subtitle_file and ass_subtitle_file.exists():
        sub_esc = escape_ffmpeg_path(ass_subtitle_file)
        vf += f";{final_v_label}ass='{sub_esc}'[vout]"
        final_v_label = "[vout]"

    cmd = [
        ffmpeg, "-y",
        "-ss", str(start_sec),
        "-i", str(source_video),
        "-t", str(duration),
        "-filter_complex", vf,
        "-map", final_v_label,
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path)
    ]

    if status_cb:
        status_cb(f"Rendering clip to {output_path.name}...")

    run_command(cmd)

    if progress_cb:
        progress_cb(100)
    if status_cb:
        status_cb(f"Rendered: {output_path.name}")

    return str(output_path)

# ---------------------------------------------------------
# Background Worker Threads
# ---------------------------------------------------------

class AppWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, task_fn, *args, **kwargs):
        super().__init__()
        self.task_fn = task_fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.task_fn(self.progress.emit, self.status.emit, *self.args, **self.kwargs)
            self.done.emit(res)
        except Exception as e:
            self.failed.emit(str(e))

# ---------------------------------------------------------
# UI Custom Clip Card Item Widget
# ---------------------------------------------------------

class ClipCardWidget(QWidget):
    def __init__(self, clip_data: Dict[str, Any], on_preview_clicked=None, on_export_clicked=None):
        super().__init__()
        self.clip = clip_data

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Top row: Virality badge + ID + Time
        top_row = QHBoxLayout()
        
        badge_color = "#10b981" if clip_data["score"] >= 90 else ("#f59e0b" if clip_data["score"] >= 80 else "#6366f1")
        badge = QLabel(f"🔥 {clip_data['score']}% VIRALITY")
        badge.setStyleSheet(f"background:{badge_color};color:white;font-weight:bold;font-size:11px;border-radius:5px;padding:3px 8px;")
        
        title_lbl = QLabel(f"Clip #{clip_data['id']}: {clip_data['title']}")
        title_lbl.setStyleSheet("color:#ffffff;font-size:14px;font-weight:bold;")

        dur_lbl = QLabel(f"⏱️ {clip_data['duration']}s  ({format_timestamp_hms(clip_data['start'])} - {format_timestamp_hms(clip_data['end'])})")
        dur_lbl.setStyleSheet("color:#94a3b8;font-size:12px;font-weight:500;")

        top_row.addWidget(badge)
        top_row.addWidget(title_lbl, 1)
        top_row.addWidget(dur_lbl)
        layout.addLayout(top_row)

        # Transcript text preview
        text_preview = QLabel(f"\"{clip_data['text'][:140]}...\"")
        text_preview.setStyleSheet("color:#cbd5e1;font-size:12px;font-style:italic;")
        text_preview.setWordWrap(True)
        layout.addWidget(text_preview)

        self.setStyleSheet("""
            ClipCardWidget {
                background: #1e1e2d;
                border: 1px solid #323248;
                border-radius: 9px;
            }
            ClipCardWidget:hover {
                border: 1px solid #7c3aed;
                background: #252538;
            }
        """)

# ---------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - AI Viral Shorts & Reels Studio")
        self.resize(1340, 880)
        self.setMinimumSize(1100, 720)

        self.video_path: Optional[Path] = None
        self.video_info: Dict[str, Any] = {}
        self.transcript_data: Optional[Dict[str, Any]] = None
        self.project_dir: Optional[Path] = None
        self.clips: List[Dict[str, Any]] = []
        self.worker: Optional[AppWorker] = None

        self.setup_media_player()
        self.init_ui()
        self.apply_theme()

    def setup_media_player(self):
        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.positionChanged.connect(self.on_player_position_changed)
        self.media_player.durationChanged.connect(self.on_player_duration_changed)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(12)

        # 1. Header Bar
        header = QHBoxLayout()
        logo_layout = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size:24px;font-weight:900;color:#a855f7;letter-spacing:1px;")
        subtitle = QLabel("AI Long Video to Viral Shorts, Reels & TikToks • Word-by-Word Captions • 4K Export")
        subtitle.setStyleSheet("color:#94a3b8;font-size:12px;")
        logo_layout.addWidget(title)
        logo_layout.addWidget(subtitle)
        header.addLayout(logo_layout)
        header.addStretch()

        self.btn_open_exports = QPushButton("📁 Open Exports Folder")
        self.btn_open_exports.clicked.connect(self.open_exports_folder)
        header.addWidget(self.btn_open_exports)
        main_layout.addLayout(header)

        # 2. Main Content Splitter (Left: Controls & Player | Right: Clips & Export)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(8)

        # Left Column Widget
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)

        # Source Video Box
        source_group = QGroupBox("1. Video Source")
        source_form = QVBoxLayout(source_group)

        # YouTube URL row
        yt_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste YouTube Video URL (e.g. https://www.youtube.com/watch?v=...)")
        self.btn_yt_import = QPushButton("📥 Import YouTube")
        self.btn_yt_import.clicked.connect(self.on_import_youtube)
        yt_row.addWidget(self.url_input, 1)
        yt_row.addWidget(self.btn_yt_import)
        source_form.addLayout(yt_row)

        # Local File row
        file_row = QHBoxLayout()
        self.lbl_file_name = QLabel("No local file selected")
        self.lbl_file_name.setStyleSheet("color:#94a3b8;padding-left:4px;")
        self.btn_browse = QPushButton("📁 Browse Local Video")
        self.btn_browse.clicked.connect(self.on_browse_video)
        file_row.addWidget(self.btn_browse)
        file_row.addWidget(self.lbl_file_name, 1)
        source_form.addLayout(file_row)

        left_layout.addWidget(source_group)

        # Video Preview Player
        player_group = QGroupBox("Video Preview Player")
        player_layout = QVBoxLayout(player_group)
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(240)
        self.media_player.setVideoOutput(self.video_widget)
        player_layout.addWidget(self.video_widget)

        # Player controls
        ctrl_layout = QHBoxLayout()
        self.btn_play = QPushButton("▶ Play")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.clicked.connect(self.stop_playback)

        self.timeline_slider = QSlider(Qt.Horizontal)
        self.timeline_slider.sliderMoved.connect(self.on_slider_seek)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("color:#cbd5e1;font-size:11px;min-width:85px;")

        ctrl_layout.addWidget(self.btn_play)
        ctrl_layout.addWidget(self.btn_stop)
        ctrl_layout.addWidget(self.timeline_slider, 1)
        ctrl_layout.addWidget(self.lbl_time)
        player_layout.addLayout(ctrl_layout)
        left_layout.addWidget(player_group)

        # AI Clipper Settings Box
        settings_group = QGroupBox("2. AI Clipping Settings")
        settings_form = QFormLayout(settings_group)
        settings_form.setLabelAlignment(Qt.AlignLeft)
        settings_form.setSpacing(10)

        self.combo_model = QComboBox()
        self.combo_model.addItems(["base (Fast & Balanced)", "small (High Accuracy)", "tiny (Ultra Fast)"])
        settings_form.addRow("AI Whisper Model:", self.combo_model)

        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["Auto Detect", "Hindi", "English", "Spanish", "French", "German"])
        settings_form.addRow("Audio Language:", self.combo_lang)

        self.combo_duration = QComboBox()
        self.combo_duration.addItems(["30", "15", "45", "60", "90"])
        settings_form.addRow("Target Duration (s):", self.combo_duration)

        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 25)
        self.spin_count.setValue(8)
        settings_form.addRow("Max Highlight Clips:", self.spin_count)

        self.combo_caption_style = QComboBox()
        self.combo_caption_style.addItems([
            "MrBeast (Yellow Active Highlight)",
            "Hormozi (Neon Green Active Highlight)",
            "Cyberpunk (Cyan & Magenta)",
            "Minimal Clean (White Subtitle)",
            "None (No Captions)"
        ])
        settings_form.addRow("Caption Preset:", self.combo_caption_style)

        self.combo_framing = QComboBox()
        self.combo_framing.addItems([
            "Blurred Background (Recommended)",
            "Center Crop",
            "Left Crop",
            "Right Crop"
        ])
        settings_form.addRow("Reframe Mode:", self.combo_framing)

        self.combo_aspect = QComboBox()
        self.combo_aspect.addItems(["9:16 (Vertical Shorts/Reels)", "1:1 (Square)", "16:9 (Landscape)"])
        settings_form.addRow("Aspect Ratio:", self.combo_aspect)

        self.combo_res = QComboBox()
        self.combo_res.addItems(["1080p Full HD", "4K Ultra HD"])
        settings_form.addRow("Export Resolution:", self.combo_res)

        left_layout.addWidget(settings_group)

        # Big Action Button
        self.btn_generate = QPushButton("✨ Generate Viral Clips with AI")
        self.btn_generate.setStyleSheet("background:#7c3aed;color:white;font-weight:900;font-size:15px;padding:14px;border-radius:9px;")
        self.btn_generate.setEnabled(False)
        self.btn_generate.clicked.connect(self.on_start_generate)
        left_layout.addWidget(self.btn_generate)

        splitter.addWidget(left_widget)

        # Right Column Widget (Clips List & Export Inspector)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(12)

        # Clips Header
        clips_head = QHBoxLayout()
        self.lbl_clips_count = QLabel("Generated Clips (0)")
        self.lbl_clips_count.setStyleSheet("font-size:16px;font-weight:bold;color:#f8fafc;")
        clips_head.addWidget(self.lbl_clips_count)
        clips_head.addStretch()

        self.btn_export_all = QPushButton("🚀 Export ALL Clips (Batch)")
        self.btn_export_all.setStyleSheet("background:#059669;color:white;font-weight:bold;padding:8px 14px;")
        self.btn_export_all.setEnabled(False)
        self.btn_export_all.clicked.connect(self.on_export_all)
        clips_head.addWidget(self.btn_export_all)
        right_layout.addLayout(clips_head)

        # Clips List Widget
        self.clips_list = QListWidget()
        self.clips_list.setSpacing(6)
        self.clips_list.itemClicked.connect(self.on_clip_selected)
        right_layout.addWidget(self.clips_list, 1)

        # Selected Clip Inspector & Actions Box
        self.inspector_group = QGroupBox("Selected Clip Inspector & Export")
        insp_layout = QVBoxLayout(self.inspector_group)
        
        # Clip Time adjustment
        time_adjust_row = QHBoxLayout()
        time_adjust_row.addWidget(QLabel("Start (s):"))
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setRange(0.0, 99999.0)
        self.spin_start.setSingleStep(0.5)
        time_adjust_row.addWidget(self.spin_start)

        time_adjust_row.addWidget(QLabel("End (s):"))
        self.spin_end = QDoubleSpinBox()
        self.spin_end.setRange(0.0, 99999.0)
        self.spin_end.setSingleStep(0.5)
        time_adjust_row.addWidget(self.spin_end)

        self.btn_preview_clip = QPushButton("▶ Preview Clip")
        self.btn_preview_clip.clicked.connect(self.preview_selected_clip)
        time_adjust_row.addWidget(self.btn_preview_clip)
        insp_layout.addLayout(time_adjust_row)

        # Export buttons
        export_btn_row = QHBoxLayout()
        self.btn_export_single = QPushButton("💾 Export Selected Clip")
        self.btn_export_single.setStyleSheet("background:#2563eb;color:white;font-weight:bold;padding:11px;")
        self.btn_export_single.setEnabled(False)
        self.btn_export_single.clicked.connect(self.on_export_single)

        self.btn_export_srt = QPushButton("📄 Save Subtitles (.SRT / .ASS)")
        self.btn_export_srt.setEnabled(False)
        self.btn_export_srt.clicked.connect(self.on_export_captions)

        export_btn_row.addWidget(self.btn_export_single, 1)
        export_btn_row.addWidget(self.btn_export_srt)
        insp_layout.addLayout(export_btn_row)

        right_layout.addWidget(self.inspector_group)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)
        main_layout.addWidget(splitter, 1)

        # 3. Bottom Progress Bar & Activity Log Status
        bottom_box = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        bottom_box.addWidget(self.progress_bar)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Ready • Import a video or paste a YouTube URL to get started.")
        self.status_label.setStyleSheet("color:#a1a1aa;font-size:12px;")
        status_row.addWidget(self.status_label, 1)

        self.btn_toggle_log = QPushButton("📜 View Log Console")
        self.btn_toggle_log.clicked.connect(self.toggle_log_console)
        status_row.addWidget(self.btn_toggle_log)
        bottom_box.addLayout(status_row)

        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumHeight(140)
        self.log_console.hide()
        bottom_box.addWidget(self.log_console)

        main_layout.addLayout(bottom_box)

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0f0f17;
                color: #e2e8f0;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #27273a;
                border-radius: 10px;
                margin-top: 10px;
                padding: 12px;
                font-weight: bold;
                color: #c084fc;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
                background-color: #1a1a27;
                border: 1px solid #33334d;
                border-radius: 7px;
                padding: 7px 10px;
                color: #ffffff;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #9333ea;
            }
            QPushButton {
                background-color: #27273a;
                color: #ffffff;
                border: 1px solid #3e3e58;
                border-radius: 7px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #35354e;
                border: 1px solid #7c3aed;
            }
            QPushButton:disabled {
                background-color: #1a1a24;
                color: #64748b;
                border: 1px solid #232330;
            }
            QProgressBar {
                background-color: #1a1a27;
                border: 1px solid #2d2d42;
                border-radius: 5px;
                height: 12px;
                text-align: center;
                color: white;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #9333ea;
                border-radius: 4px;
            }
            QListWidget {
                background-color: #14141f;
                border: 1px solid #27273a;
                border-radius: 9px;
                padding: 6px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #27273a;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #9333ea;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
        """)

    def log(self, message: str):
        self.log_console.append(message)

    def toggle_log_console(self):
        if self.log_console.isVisible():
            self.log_console.hide()
            self.btn_toggle_log.setText("📜 View Log Console")
        else:
            self.log_console.show()
            self.btn_toggle_log.setText("❌ Hide Log Console")

    def open_exports_folder(self):
        if os.name == "nt":
            os.startfile(str(EXPORTS_DIR))
        else:
            subprocess.Popen(["xdg-open", str(EXPORTS_DIR)])

    # ---------------------------------------------------------
    # Media Player Handling
    # ---------------------------------------------------------

    def load_video_into_player(self, path: Path):
        self.video_path = path
        self.lbl_file_name.setText(path.name)
        self.btn_generate.setEnabled(True)
        self.media_player.setSource(QUrl.fromLocalFile(str(path)))
        self.log(f"Loaded video: {path.name}")

        try:
            self.video_info = probe_video_info(path)
            self.status_label.setText(
                f"Video ready: {path.name} • Duration: {format_timestamp_hms(self.video_info['duration'])} • Resolution: {self.video_info['width']}x{self.video_info['height']}"
            )
        except Exception as e:
            self.log(f"Could not probe video info: {e}")

    def toggle_play(self):
        if self.media_player.playbackState() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.btn_play.setText("▶ Play")
        else:
            self.media_player.play()
            self.btn_play.setText("⏸ Pause")

    def stop_playback(self):
        self.media_player.stop()
        self.btn_play.setText("▶ Play")

    def on_slider_seek(self, position):
        self.media_player.setPosition(position)

    def on_player_position_changed(self, pos):
        self.timeline_slider.setValue(pos)
        dur = self.media_player.duration()
        self.lbl_time.setText(f"{format_timestamp_hms(pos/1000)} / {format_timestamp_hms(dur/1000)}")

    def on_player_duration_changed(self, dur):
        self.timeline_slider.setRange(0, dur)

    # ---------------------------------------------------------
    # Video Ingestion (YouTube & Local)
    # ---------------------------------------------------------

    def on_browse_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mov *.mkv *.webm *.avi *.flv *.ts)"
        )
        if file_path:
            self.load_video_into_player(Path(file_path))

    def on_import_youtube(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "URL Missing", "Pehle YouTube video URL dalein!")
            return

        self.btn_yt_import.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.btn_generate.setEnabled(False)

        def task(progress_cb, status_cb):
            return download_youtube_video(url, TEMP_DIR, progress_cb, status_cb)

        self.worker = AppWorker(task)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self.status_label.setText)
        self.worker.done.connect(self.on_youtube_done)
        self.worker.failed.connect(self.on_task_failed)
        self.worker.start()

    def on_youtube_done(self, video_path_str: str):
        self.btn_yt_import.setEnabled(True)
        self.btn_browse.setEnabled(True)
        path = Path(video_path_str)
        self.load_video_into_player(path)
        QMessageBox.information(self, "Download Complete", f"YouTube video successfully downloaded:\n{path.name}")

    # ---------------------------------------------------------
    # AI Generation Pipeline
    # ---------------------------------------------------------

    def on_start_generate(self):
        if not self.video_path or not self.video_path.exists():
            QMessageBox.warning(self, "No Video", "Pehle koi video import karein!")
            return

        self.btn_generate.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.btn_yt_import.setEnabled(False)

        model_name = self.combo_model.currentText().split()[0]
        language = self.combo_lang.currentText()
        target_duration = int(self.combo_duration.currentText())
        max_clips = self.spin_count.value()

        # Create project directory
        clean_stem = re.sub(r"[^\w\-]", "_", self.video_path.stem)[:50]
        self.project_dir = PROJECTS_DIR / clean_stem
        self.project_dir.mkdir(parents=True, exist_ok=True)

        video_file = self.video_path

        def pipeline_task(progress_cb, status_cb):
            status_cb("Probing video information...")
            info = probe_video_info(video_file)
            dur = info["duration"]

            status_cb("Starting AI transcription with Faster-Whisper...")
            transcript = transcribe_audio(video_file, language, model_name, progress_cb, status_cb)

            # Save full transcript
            transcript_file = self.project_dir / "transcript.json"
            with open(transcript_file, "w", encoding="utf-8") as f:
                json.dump(transcript, f, ensure_ascii=False, indent=2)

            status_cb("Analyzing speech density, hooks, and finding viral clips...")
            clips = find_optimal_clips(transcript["segments"], dur, target_duration, max_clips)

            # Save clips.json
            clips_file = self.project_dir / "clips.json"
            with open(clips_file, "w", encoding="utf-8") as f:
                json.dump(clips, f, ensure_ascii=False, indent=2)

            progress_cb(100)
            status_cb(f"Generated {len(clips)} viral highlight clips!")
            return {"transcript": transcript, "clips": clips, "info": info}

        self.worker = AppWorker(pipeline_task)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self.status_label.setText)
        self.worker.done.connect(self.on_generate_done)
        self.worker.failed.connect(self.on_task_failed)
        self.worker.start()

    def on_generate_done(self, result: Dict[str, Any]):
        self.btn_generate.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.btn_yt_import.setEnabled(True)

        self.transcript_data = result["transcript"]
        self.clips = result["clips"]
        self.lbl_clips_count.setText(f"Generated Clips ({len(self.clips)})")

        self.clips_list.clear()
        for clip in self.clips:
            item = QListWidgetItem(self.clips_list)
            card = ClipCardWidget(clip)
            item.setSizeHint(card.sizeHint())
            self.clips_list.addItem(item)
            self.clips_list.setItemWidget(item, card)

        self.btn_export_all.setEnabled(bool(self.clips))
        self.btn_export_single.setEnabled(bool(self.clips))
        self.btn_export_srt.setEnabled(bool(self.clips))

        if self.clips:
            self.clips_list.setCurrentRow(0)
            self.on_clip_selected(self.clips_list.item(0))

        QMessageBox.information(
            self, "Clips Generated",
            f"AI ne {len(self.clips)} highlight clips successfully identify kar liye hain!\n"
            "Aap kisi bhi clip ko select karke preview kar sakte hain ya export kar sakte hain."
        )

    # ---------------------------------------------------------
    # Clip Selection & Trimming
    # ---------------------------------------------------------

    def on_clip_selected(self, item: QListWidgetItem):
        row = self.clips_list.row(item)
        if 0 <= row < len(self.clips):
            clip = self.clips[row]
            self.spin_start.setValue(clip["start"])
            self.spin_end.setValue(clip["end"])
            # Seek player to clip start
            self.media_player.setPosition(int(clip["start"] * 1000))

    def preview_selected_clip(self):
        row = self.clips_list.currentRow()
        if 0 <= row < len(self.clips):
            start = self.spin_start.value()
            self.media_player.setPosition(int(start * 1000))
            self.media_player.play()
            self.btn_play.setText("⏸ Pause")

    # ---------------------------------------------------------
    # Export Engine (Single & Batch)
    # ---------------------------------------------------------

    def parse_export_settings(self):
        aspect_raw = self.combo_aspect.currentText()
        aspect = "9:16" if "9:16" in aspect_raw else ("1:1" if "1:1" in aspect_raw else "16:9")
        framing = self.combo_framing.currentText().split("(")[0].strip()
        res = "4K" if "4K" in self.combo_res.currentText() else "1080p"
        
        caption_raw = self.combo_caption_style.currentText()
        if "MrBeast" in caption_raw:
            cap_style = "MrBeast"
        elif "Hormozi" in caption_raw:
            cap_style = "Hormozi"
        elif "Cyberpunk" in caption_raw:
            cap_style = "Cyberpunk"
        elif "Minimal" in caption_raw:
            cap_style = "Minimal"
        else:
            cap_style = "None"
            
        return aspect, framing, res, cap_style

    def on_export_single(self):
        row = self.clips_list.currentRow()
        if row < 0 or row >= len(self.clips):
            QMessageBox.warning(self, "No Clip Selected", "Pehle list me se koi clip select karein!")
            return

        clip = self.clips[row]
        start = self.spin_start.value()
        end = self.spin_end.value()
        if end <= start:
            QMessageBox.warning(self, "Invalid Time", "End time start time se bada hona chahiye!")
            return

        aspect, framing, res, cap_style = self.parse_export_settings()
        out_name = f"{self.video_path.stem}_clip{clip['id']}_{aspect.replace(':','x')}_{res}.mp4"
        out_path = EXPORTS_DIR / out_name

        self.btn_export_single.setEnabled(False)
        self.btn_export_all.setEnabled(False)

        def export_task(progress_cb, status_cb):
            ass_path = None
            if cap_style != "None" and self.transcript_data:
                ass_path = self.project_dir / f"clip_{clip['id']}.ass"
                generate_clip_ass(self.transcript_data["segments"], start, end, ass_path, cap_style)

            return render_video_clip(
                self.video_path, start, end, out_path,
                aspect_ratio=aspect, framing_mode=framing,
                resolution_label=res, ass_subtitle_file=ass_path,
                progress_cb=progress_cb, status_cb=status_cb
            )

        self.worker = AppWorker(export_task)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self.status_label.setText)
        self.worker.done.connect(lambda p: self.on_single_export_done(p))
        self.worker.failed.connect(self.on_task_failed)
        self.worker.start()

    def on_single_export_done(self, out_path: str):
        self.btn_export_single.setEnabled(True)
        self.btn_export_all.setEnabled(True)
        QMessageBox.information(self, "Export Complete", f"Clip successfully export ho gayi hai:\n{out_path}")

    def on_export_all(self):
        if not self.clips:
            return

        aspect, framing, res, cap_style = self.parse_export_settings()
        reply = QMessageBox.question(
            self, "Confirm Batch Export",
            f"Kya aap sabhi {len(self.clips)} clips ko batch export karna chahte hain?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_export_single.setEnabled(False)
        self.btn_export_all.setEnabled(False)

        clips_to_export = list(self.clips)
        total = len(clips_to_export)

        def batch_task(progress_cb, status_cb):
            results = []
            for i, clip in enumerate(clips_to_export):
                status_cb(f"Exporting clip {i+1} of {total}...")
                s = clip["start"]
                e = clip["end"]
                out_name = f"{self.video_path.stem}_clip{clip['id']}_{aspect.replace(':','x')}_{res}.mp4"
                out_path = EXPORTS_DIR / out_name

                ass_path = None
                if cap_style != "None" and self.transcript_data:
                    ass_path = self.project_dir / f"clip_{clip['id']}.ass"
                    generate_clip_ass(self.transcript_data["segments"], s, e, ass_path, cap_style)

                render_video_clip(
                    self.video_path, s, e, out_path,
                    aspect_ratio=aspect, framing_mode=framing,
                    resolution_label=res, ass_subtitle_file=ass_path,
                    status_cb=status_cb
                )
                results.append(str(out_path))
                progress_cb(int((i + 1) * 100 / total))
            return results

        self.worker = AppWorker(batch_task)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self.status_label.setText)
        self.worker.done.connect(self.on_batch_done)
        self.worker.failed.connect(self.on_task_failed)
        self.worker.start()

    def on_batch_done(self, results: List[str]):
        self.btn_export_single.setEnabled(True)
        self.btn_export_all.setEnabled(True)
        QMessageBox.information(
            self, "Batch Export Complete",
            f"Sabhi {len(results)} clips exports folder me save ho gaye hain!\nLocation: {EXPORTS_DIR}"
        )

    def on_export_captions(self):
        row = self.clips_list.currentRow()
        if row < 0 or row >= len(self.clips):
            return
        clip = self.clips[row]

        dest_srt, _ = QFileDialog.getSaveFileName(
            self, "Save SRT Captions", f"{self.video_path.stem}_clip{clip['id']}.srt", "SubRip (*.srt)"
        )
        if dest_srt and self.transcript_data:
            generate_clip_srt(self.transcript_data["segments"], clip["start"], clip["end"], Path(dest_srt))
            QMessageBox.information(self, "Saved", f"SRT Captions saved to:\n{dest_srt}")

    def on_task_failed(self, err_msg: str):
        self.btn_generate.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.btn_yt_import.setEnabled(True)
        self.btn_export_single.setEnabled(bool(self.clips))
        self.btn_export_all.setEnabled(bool(self.clips))
        self.status_label.setText("Error occurred!")
        self.log(f"ERROR: {err_msg}")
        QMessageBox.critical(self, "Process Error", f"Ek error aaya:\n{err_msg}")

# ---------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------

def main():
    if not get_ffmpeg() or not get_ffprobe():
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None, "FFmpeg Missing",
            "FFmpeg aur FFprobe system PATH me nahi mile!\n"
            "Kripya FFmpeg install karke PATH me add karein aur app ko restart karein."
        )
        return

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
