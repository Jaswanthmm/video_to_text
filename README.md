# Session Lens

A local Python web app for reviewing exported Citrix MP4 recordings. Upload a video, detect visually idle intervals, read visible text, review likely terminal commands, and export JSON/CSV reports.

## Run on Windows

Install Python 3.11 or newer, then run in this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run app.py
```

Open http://localhost:8501. For screen text recognition, install the separate [Tesseract OCR engine](https://tesseract-ocr.github.io/tessdoc/Installation.html). The app finds installations on PATH or at `C:\Program Files\Tesseract-OCR\tesseract.exe`; you can enter another path in the sidebar. You can disable OCR to use idle detection without Tesseract.

## Behavior and limitations

- Use **Collect timestamped screenshots** to download PNG images and a `timestamps.csv` manifest together in a ZIP, without running command analysis. Every video produces start, midpoint, and last-frame screenshots, regardless of duration or file size. Longer videos also include captures at 10:00, 20:00, etc., while the timestamp is within the video. An interval that coincides with a required frame is captured only once, keeping the start/mid/end label. The images have an added timestamp footer; original screen pixels remain intact. Enter the recording start time for calendar timestamps as well. These are point-in-time screenshots, not three exported video clips. Single-frame videos produce three labeled copies. Screenshots remain in session memory until the upload changes or the session ends.

- Defaults: sample every 0.1 seconds; mark every detected unchanged interval as estimated idle, without a minimum duration. Sampling is adjustable. Optionally enter the actual recording start date/time to export calendar timestamps for idle starts and ends.
- Idle detection compares resized grayscale samples with a pixel-difference threshold. Compression, blinking cursors, clocks, animations, and small edits can affect results. It does not establish whether a person is working.
- OCR reads text bands in every sampled frame, caches unchanged bands, and enlarges lines for recognition. It is optimized for left-aligned terminal text; centered windows, wrapped commands, and multiline input can still be missed. Short-lived commands between samples may be missed. Prompt recognition supports clipped PowerShell prefixes, Windows Command Prompt, Unix user@host prompts, and bracketed Linux prompts.
- Prompt history is aligned across frames to combine evolving input and retain repeated commands. Edits on the same active prompt are one input until a new prompt is observed. OCR errors, cleared screens, identical repeated history, and scrolling can cause misses or duplicates. Baseline history at time zero is excluded; a late first observed command is retained with an unknown typing-time label. A following prompt is evidence of a new input boundary, not proof of successful execution.
- Dim autocomplete suggestions in dark terminals are suppressed by default. Disable this setting when genuine typed text is dim. Very thin full-height carets are removed before recognition. This visual heuristic may affect unusually styled glyphs; verify the result in the video.
- Activity descriptions are rules based on visible text, not semantic understanding of arbitrary user actions. No external AI service, audio transcription, or Citrix event logs are used.
- Timestamps preserve milliseconds and identify when the final OCR reading was first observed, not the exact keypress time. OCR uncertainty may delay recognition beyond the sampling interval. Video seeking depends on decoder behavior. Idle ends at the last confirmed unchanged sample. Unsampled trailing time is not classified as idle.
- Review command candidates against the recording. OCR assumes English by default.
- Upload limit: 10 GB (10,240 MB). Streamlit holds uploaded files in memory, so very large files require substantial available RAM and temporary disk space; raising the limit does not guarantee that every 10 GB file can be processed. OCR of long recordings can be slow. This prototype runs analysis synchronously and has no accounts, durable job queue, or report database. Restart the app after changing the upload limit.
- Binds to localhost. Do not expose the prototype as a shared service without adding authentication, upload controls, isolated workers, and an appropriate retention policy. Reports can contain sensitive screen text.
- Temporary video files are removed after analysis, including errors. Uploaded bytes and reports remain in Streamlit session memory; disconnect or restart to clear the session. No disk report history is retained automatically.

## Tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Implementation references: [Streamlit uploads](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader), [pytesseract](https://github.com/madmaze/pytesseract).
