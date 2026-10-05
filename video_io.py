"""Shared upload validation and decoder handling for supported extensions."""
from contextlib import contextmanager
from pathlib import Path
import math

import cv2

UPLOAD_EXTENSIONS = ('mp4', 'avi', 'vid')


def upload_suffix(filename):
    suffix = Path(filename).suffix.lower()
    if suffix.lstrip('.') not in UPLOAD_EXTENSIONS:
        raise ValueError('Choose an MP4, AVI, or VID recording.')
    return suffix


def unreadable_message(path):
    if Path(path).suffix.lower() == '.vid':
        return ('This .vid file cannot be decoded as a standard video. VID is not a single '
                'video format; native or proprietary session recordings need to be exported '
                'from the recording application to MP4 or AVI first. Renaming the extension '
                'does not convert the recording.')
    return ('Cannot decode this recording. It may be damaged or use an unsupported codec. '
            'Export it as a playable MP4 (H.264) or AVI and upload it again.')


@contextmanager
def open_video(path):
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if (not cap.isOpened() or not math.isfinite(fps) or fps <= 0
                or not math.isfinite(count) or count < 1):
            raise ValueError(unreadable_message(path))
        ok, frame = cap.read()
        if not ok or frame is None or not cap.set(cv2.CAP_PROP_POS_FRAMES, 0):
            raise ValueError(unreadable_message(path))
        yield cap, fps, int(count)
    finally:
        cap.release()


def preview_frame(path, seconds):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Preview time must be a nonnegative number.')
    with open_video(path) as (cap, fps, count):
        index = min(round(seconds * fps), count - 1)
        if not cap.set(cv2.CAP_PROP_POS_FRAMES, index):
            raise ValueError('Cannot seek to the requested preview frame.')
        ok, frame = cap.read()
        if not ok:
            raise ValueError('Cannot decode the requested preview frame.')
        ok, png = cv2.imencode('.png', frame)
        if not ok:
            raise ValueError('Cannot create the preview image.')
        return png.tobytes(), index / fps
