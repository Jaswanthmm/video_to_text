"""Collect timestamped video frames without running OCR."""
import csv
import io
import math
import zipfile

import cv2

from analyzer import timestamp, calendar_timestamp


def capture_targets(frame_count, fps):
    if frame_count < 1 or not math.isfinite(fps) or fps <= 0:
        raise ValueError('Video has invalid frame count or frame rate.')
    duration = frame_count / fps
    targets = [('start', 0), ('mid', min(frame_count - 1, frame_count // 2)),
               ('end', frame_count - 1)]
    required_frames = {frame for _, frame in targets}
    for seconds in range(600, math.ceil(duration), 600):
        frame = min(frame_count - 1, round(seconds * fps))
        if frame not in required_frames:
            targets.append(('interval', frame))
    return sorted(targets, key=lambda target: target[1])


def collect_screenshots(path, recording_start=None):
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or not math.isfinite(count) or count < 1:
            raise ValueError('Cannot read this recording for screenshots.')
        rows, images = [], []
        for index, (label, frame_index) in enumerate(capture_targets(int(count), fps)):
            if not cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index):
                raise ValueError(f'Cannot seek to the {label} screenshot.')
            ok, frame = cap.read()
            if not ok:
                raise ValueError(f'Cannot decode the {label} screenshot at frame {frame_index}.')
            seconds = frame_index / fps
            elapsed = timestamp(seconds)
            calendar = calendar_timestamp(recording_start, seconds) if recording_start else ''
            caption = f'{label.title()} | Video {elapsed}' + (f' | {calendar}' if calendar else '')
            # Put the timestamp in an added footer; preserve every source pixel.
            width = frame.shape[1]
            scale = min(0.65, max(0.15, (width - 12) / max(1, cv2.getTextSize(caption, cv2.FONT_HERSHEY_SIMPLEX, 1, 1)[0][0])))
            footer = max(28, int(40 * scale))
            annotated = cv2.copyMakeBorder(frame, 0, footer, 0, 0, cv2.BORDER_CONSTANT, value=(24, 24, 24))
            cv2.putText(annotated, caption, (6, frame.shape[0] + footer - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
            ok, encoded = cv2.imencode('.png', annotated)
            if not ok:
                raise ValueError('Could not encode screenshot.')
            name = f'{index + 1:03}_{label}_{elapsed.replace(":", "-")}.png'
            rows.append({'file': name, 'position': label, 'video_timestamp': elapsed,
                         'recording_timestamp': calendar, 'seconds': seconds, 'frame_index': frame_index})
            images.append(encoded.tobytes())
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for row, data in zip(rows, images):
                archive.writestr(row['file'], data)
            manifest = io.StringIO()
            writer = csv.DictWriter(manifest, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr('timestamps.csv', manifest.getvalue())
        return {'rows': rows, 'images': images, 'zip': buffer.getvalue()}
    finally:
        cap.release()
