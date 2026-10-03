"""Local, sampled visual analysis. Observations are not keyboard telemetry."""
import re
from command_tracker import CommandTracker
from datetime import timedelta
from dataclasses import dataclass, asdict
from screen_ocr import ScreenOCR

import cv2
import numpy as np
import pytesseract


def timestamp(seconds):
    milliseconds = round(float(seconds) * 1000)
    seconds, remainder = divmod(milliseconds, 1000)
    value = f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
    return value + (f'.{remainder:03}' if remainder else '')


def calendar_timestamp(start, seconds):
    value = start + timedelta(milliseconds=round(float(seconds) * 1000))
    base = value.strftime('%d-%m-%Y %H:%M:%S')
    return base + (f'.{value.microsecond // 1000:03}' if value.microsecond else '')


def commands_from_text(text):
    return [command for command in prompt_lines(text) if command]


def prompt_lines(text):
    # A clipped PS prefix may be read as S, 1S, 9S, etc. The drive path and >
    # remain mandatory, so arbitrary OCR prose is not accepted as a command.
    pattern = r"^\s*(?:(?:[^\s]{1,3}\s+)?[A-Za-z]:\s*\\[^>]*>|\[[^\]\n]+\]\s*[$#]|[\w.-]+@[\w.-]+[^\n]*?[$#]|[$#])\s*(.*)$"
    return [re.sub(r'\s+[|▏▎▌█]$', '', m.group(1)).strip() if m.group(1).strip() not in ('|', '_', '▏', '▎', '▌', '█') else '' for line in text.splitlines()
            if (m := re.match(pattern, line))]


def activity_log(commands, idle, recording_start=None, idle_every=10):
    if idle_every <= 0:
        raise ValueError('Idle log spacing must be positive.')
    rows = [{"seconds": e['seconds'], "activity": e['command'], "evidence": e['status']}
            for e in commands]
    for start, end in idle:
        for seconds in np.arange(start, end, idle_every):
            if not any(abs(e['seconds'] - seconds) < 0.001 for e in commands):
                rows.append({"seconds": float(seconds), "activity": "Idle screen", "evidence": "Visually unchanged (estimated)"})
    rows.sort(key=lambda row: row['seconds'])
    for row in rows:
        row['timestamp'] = (calendar_timestamp(recording_start, row['seconds'])
                            if recording_start else timestamp(row['seconds']))
    return rows


def describe(text, commands):
    if commands:
        return "Terminal command visible (execution unverified)"
    lower = text.lower()
    if any(term in lower for term in ("powershell", "command prompt", "terminal")):
        return "Terminal window visible"
    if any(term in lower for term in ("https://", "http://", "chrome", "firefox", "microsoft edge")):
        return "Browser content visible"
    if any(term in lower for term in ("file explorer", "quick access", "this pc")):
        return "File browser visible"
    return "Screen content visible" if text else "Screen observation (no readable text)"


@dataclass
class Settings:
    sample_seconds: float = 0.1
    change_percent: float = 0.15
    ocr: bool = True
    suppress_suggestions: bool = True


def idle_intervals(samples, duration):
    """Samples contain a time and change since the preceding sample."""
    if not samples:
        return []
    intervals = []
    start = samples[0][0]
    for i in range(1, len(samples)):
        time, changed = samples[i]
        if changed:
            # End at last unchanged observation, not at the new changed frame.
            end = samples[i - 1][0]
            if end > start:
                intervals.append((start, end))
            start = time
    end = samples[-1][0]
    if end > start:
        intervals.append((start, end))
    return intervals


def analyze(path, settings, progress=lambda value: None):
    if settings.sample_seconds <= 0:
        raise ValueError("Sample interval must be positive.")
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or fps <= 0 or count <= 0:
            raise ValueError("Cannot read this recording. Upload a valid, playable MP4.")
        duration = count / fps
        samples, observations = [], []
        previous = None
        tracker = CommandTracker()
        reader = ScreenOCR(settings.suppress_suggestions)
        previous_text = None
        for time in np.arange(0, duration, settings.sample_seconds):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(time * 1000))
            ok, frame = cap.read()
            if not ok:
                raise ValueError(f"Video decoding failed near {timestamp(time)}; analysis is incomplete.")
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (960, 540))
            difference = 100.0 if previous is None else float(np.mean(cv2.absdiff(previous, small) > 25) * 100)
            changed = difference >= settings.change_percent
            samples.append((float(time), changed))
            previous = small
            # OCR every sample: small text edits may be below the motion threshold.
            if settings.ocr:
                text = reader.read(gray)
                commands = commands_from_text(text)
                tracker.update(text, float(time))
                if previous_text is not None and text != previous_text:
                    samples[-1] = (float(time), True)
                if text != previous_text:
                    observations.append({"seconds": float(time), "timestamp": timestamp(time),
                                         "activity": describe(text, commands), "visible_text": text})
                    previous_text = text
            elif changed:
                observations.append({"seconds": float(time), "timestamp": timestamp(time),
                                     "activity": "Visual screen change", "visible_text": "OCR disabled"})
            progress(min(1.0, float((time + settings.sample_seconds) / duration)))
        idle = idle_intervals(samples, duration)
        timeline = []
        cursor = 0.0
        for start, end in idle:
            if start > cursor:
                timeline.append({"start_seconds": cursor, "end_seconds": start, "label": "Activity / unconfirmed idle"})
            timeline.append({"start_seconds": start, "end_seconds": end, "label": "Idle screen (estimated)"})
            cursor = end
        if cursor < duration:
            timeline.append({"start_seconds": cursor, "end_seconds": duration, "label": "Activity / unconfirmed idle"})
        for row in timeline:
            row.update(start=timestamp(row["start_seconds"]), end=timestamp(row["end_seconds"]),
                       duration_seconds=round(row["end_seconds"] - row["start_seconds"], 2))
        return {"duration_seconds": duration, "settings": asdict(settings), "timeline": timeline,
                "observations": observations, "commands": tracker.events,
                "limitations": "Sampled visual estimates; OCR may miss or misread commands. No proof of execution or human inactivity."}
    finally:
        cap.release()
