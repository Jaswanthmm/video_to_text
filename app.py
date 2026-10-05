import csv
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
import tempfile
from datetime import datetime, timedelta

import pytesseract
import streamlit as st

from analyzer import Settings, analyze, timestamp, activity_log, calendar_timestamp
from screenshots import collect_screenshots
from video_io import UPLOAD_EXTENSIONS, upload_suffix, open_video, preview_frame

st.set_page_config(page_title="Session Lens", page_icon="▶", layout="wide")
st.title("Session Lens")
st.caption("Review Citrix recordings · Find visible commands · Locate idle screens")

with st.sidebar:
    st.header("Analysis settings")
    sample = st.select_slider("Sample a frame every (seconds)", [0.1, 0.25, 0.5, 1, 2, 3, 5, 10], value=0.1,
                              help="0.1 seconds helps capture commands that scroll away quickly. Longer recordings take more time.")
    idle_every = st.number_input("Repeat idle log entry every (seconds)", min_value=1, value=10,
                                 help="Controls report rows only, not when idle detection starts.")
    st.caption("Every detected unchanged interval is marked idle; no minimum idle duration.")
    recording_start = st.text_input("Recording start date/time (optional)", placeholder="03-10-2025 11:27:00", help="DD-MM-YYYY HH:MM:SS, in the recording's timezone. Enter the true recording start, not the idle start.")
    sensitivity = st.number_input("Screen change threshold (%)", min_value=0.01, max_value=10.0, value=0.15, step=0.05,
                                  help="Lower values detect smaller changes. Clocks and cursors may affect idle detection.")
    use_ocr = st.checkbox("Read visible text and detect commands", value=True,
                          help="Uses OCR to read text in the video and identify likely typed commands. Turn off to analyze idle screens without reading text. Screenshots work either way.")
    suggestions = st.checkbox("Ignore dim terminal suggestions", value=True,
                              help="For dark terminals with grey autocomplete suggestions. Disable if actual typed text is dim.")
    detected_tesseract = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not detected_tesseract:
        default_path = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        detected_tesseract = str(default_path) if default_path.is_file() else ""
    tesseract = st.text_input("Tesseract executable (optional)", value=detected_tesseract)
    st.caption("Local processing. Uploaded videos are temporarily saved during analysis and removed afterward. Results remain in this browser session.")

upload = st.file_uploader("Upload a Citrix session recording", type=list(UPLOAD_EXTENSIONS),
                          help="MP4 and AVI videos, plus VID files that contain a decodable video stream. Proprietary recordings must first be exported by their recording application.")
if upload is None:
    st.write("Upload an MP4, AVI, or compatible VID recording to create a timestamped review.")
    st.stop()

try:
    suffix = upload_suffix(upload.name)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
if suffix == '.vid':
    st.caption('VID compatibility depends on the recording format. Native session recordings may require an MP4 export from the original recording application.')

fingerprint = suffix + hashlib.sha256(upload.getbuffer()).hexdigest()
if st.session_state.get("video_id") != fingerprint:
    st.session_state.pop("result", None)
    st.session_state.pop("screenshots", None)
    st.session_state.video_id = fingerprint

st.caption('Screenshots: start, midpoint and last frame for every video, plus every 10 minutes for longer recordings. Overlapping interval captures are included only once. No video splitting or OCR is required.')
if st.button('Collect timestamped screenshots'):
    st.session_state.pop('screenshots', None)
    try:
        start_datetime = datetime.strptime(recording_start.strip(), '%d-%m-%Y %H:%M:%S') if recording_start.strip() else None
        with st.spinner('Collecting screenshots…'):
            with tempfile.TemporaryDirectory(prefix='session-screenshots-') as folder:
                path = Path(folder) / ('recording' + suffix)
                path.write_bytes(upload.getbuffer())
                st.session_state.screenshots = collect_screenshots(path, start_datetime)
    except Exception as exc:
        st.error(str(exc))

screenshots = st.session_state.get('screenshots')
if screenshots:
    with st.expander(f"Screenshots ({len(screenshots['rows'])})", expanded=True):
        st.download_button('Download screenshots and timestamps ZIP', screenshots['zip'],
                           'session-screenshots.zip', 'application/zip')
        st.dataframe(screenshots['rows'], hide_index=True, use_container_width=True)
        selected = st.selectbox('Preview screenshot', range(len(screenshots['rows'])),
                                format_func=lambda i: screenshots['rows'][i]['file'])
        st.image(screenshots['images'][selected], caption=screenshots['rows'][selected]['file'])

if st.button("Analyze recording", type="primary"):
    st.session_state.pop("result", None)
    try:
        start_datetime = datetime.strptime(recording_start, "%d-%m-%Y %H:%M:%S") if recording_start.strip() else None
        pytesseract.pytesseract.tesseract_cmd = tesseract or "tesseract"
        bar = st.progress(0, text="Analyzing recording…")
        with tempfile.TemporaryDirectory(prefix="session-lens-") as folder:
            path = Path(folder) / ('recording' + suffix)
            path.write_bytes(upload.getbuffer())
            with open_video(path):
                pass  # Validate the video before checking optional OCR dependencies.
            if use_ocr:
                try:
                    pytesseract.get_tesseract_version()
                except Exception as exc:
                    raise ValueError("Tesseract OCR is unavailable. Install it and enter its executable path, or disable text reading to analyze idle screens.") from exc
            result = analyze(path, Settings(sample, sensitivity, use_ocr, suggestions), bar.progress)
        result["recording_start"] = recording_start or None
        result["activity_log"] = activity_log(result["commands"],
            [(r['start_seconds'], r['end_seconds']) for r in result['timeline'] if r['label'].startswith('Idle')],
            start_datetime, idle_every)
        if start_datetime:
            for row in result["timeline"]:
                row["start_timestamp"] = calendar_timestamp(start_datetime, row["start_seconds"])
                row["end_timestamp"] = calendar_timestamp(start_datetime, row["end_seconds"])
            for row in result["commands"] + result["observations"]:
                row["session_timestamp"] = calendar_timestamp(start_datetime, row["seconds"])
        result["filename"] = upload.name
        st.session_state.result = result
        bar.empty()
    except Exception as exc:
        st.error(str(exc))

result = st.session_state.get("result")
if result:
    idle_total = sum(r["duration_seconds"] for r in result["timeline"] if r["label"].startswith("Idle"))
    a, b, c = st.columns(3)
    a.metric("Recording duration", timestamp(result["duration_seconds"]))
    b.metric("Estimated idle", timestamp(idle_total))
    c.metric("Command candidates", len(result["commands"]))
    st.caption(f"Report settings: {result['settings']}")
    seek = st.number_input("Review from second", min_value=0, max_value=max(0, int(result["duration_seconds"])), value=0)
    if suffix == '.mp4':
        st.video(upload, start_time=seek)
    else:
        st.caption('AVI and VID recordings use a frame preview because browser video playback may not support their format. Analysis and screenshot downloads remain available.')
        if st.button('Show frame at selected time'):
            try:
                with tempfile.TemporaryDirectory(prefix='session-preview-') as folder:
                    path = Path(folder) / ('recording' + suffix)
                    path.write_bytes(upload.getbuffer())
                    png, actual_seconds = preview_frame(path, float(seek))
                st.image(png, caption='Video time: ' + timestamp(actual_seconds))
            except Exception as exc:
                st.error(str(exc))
    log, timeline, commands, observations, exports = st.tabs(["User activity log", "Idle intervals", "Commands", "Screen observations", "Download reports"])
    with log:
        if 'activity_log' not in result:
            st.info('Analyze the recording again to generate the updated activity log.')
        else:
            st.caption('Commands show observed screen text, not keystroke telemetry. Review OCR evidence in the Commands tab. A command first seen after the recording begins may have an unknown typing time.')
            log_text = '\n'.join(f"{row['timestamp']}  -  {row['activity']}" for row in result['activity_log'])
            st.code(log_text or 'No commands or idle periods detected.', language=None)
            st.download_button('Download activity log', log_text, 'activity-log.txt', 'text/plain')
    with timeline:
        for row in result["timeline"]:
            if row["label"].startswith("Idle"):
                st.write(f"**{row.get('start_timestamp', row['start'])}** — Idle screen starts  \n"
                         f"**{row.get('end_timestamp', row['end'])}** — Idle screen ends")
        st.dataframe(result["timeline"], use_container_width=True, hide_index=True)
    with commands:
        if result["commands"]:
            st.dataframe(result["commands"], use_container_width=True, hide_index=True)
        else:
            st.write("No command candidates found." if result["settings"]["ocr"] else "Command detection was disabled.")
    with observations:
        st.dataframe(result["observations"], use_container_width=True, hide_index=True)
    with exports:
        st.download_button("Download full JSON report", json.dumps(result, indent=2), "session-report.json", "application/json")
        for key in ("activity_log", "timeline", "commands", "observations"):
            rows = result.get(key, [])
            if rows:
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
                writer.writeheader()
                # Protect spreadsheet users from formulas in untrusted screen text.
                writer.writerows({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
                                  for k, v in row.items()} for row in rows)
                st.download_button(f"Download {key} CSV", buffer.getvalue(), f"{key}.csv", "text/csv")
