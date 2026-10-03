"""Read terminal-sized lines without mixing them with recording overlays."""
import hashlib
from collections import OrderedDict

import cv2
import numpy as np
import pytesseract


class ScreenOCR:
    def __init__(self, suppress_suggestions=True):
        self.cache = OrderedDict()
        self.suppress_suggestions = suppress_suggestions

    def read(self, gray):
        dark = np.median(gray) < 80
        ink = gray if dark else 255 - gray
        # Find horizontal text bands in the left half, away from camera overlays.
        rows = np.flatnonzero(np.sum(ink[:, :max(100, gray.shape[1] // 2)] > 70, axis=1) > 3)
        groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
        lines = []
        for group in groups:
            if len(group) < 3 or len(group) > 60:
                continue
            top, bottom = max(0, int(group[0]) - 2), min(gray.shape[0], int(group[-1]) + 3)
            band = ink[top:bottom].copy()
            cols = np.flatnonzero(np.any(band > 70, axis=0))
            if not len(cols):
                continue
            # A large empty gap separates a terminal line from the webcam/toolbar.
            gaps = np.flatnonzero(np.diff(cols) > max(80, 5 * len(group)))
            right = int(cols[gaps[0]]) + 3 if len(gaps) else int(cols[-1]) + 3
            left = max(0, int(cols[0]) - 3)
            band = band[:, left:min(right, band.shape[1])]
            if band.shape[1] < 45 and len(gaps):
                continue  # Directory attribute columns, not a terminal input line.
            if dark and self.suppress_suggestions:
                # Remove dim connected glyphs, preserving antialiasing of bright text.
                count, labels, stats, _ = cv2.connectedComponentsWithStats((band > 35).astype('uint8'))
                for label in range(1, count):
                    region = labels == label
                    if band[region].max() < 145:
                        band[region] = 0
                    elif stats[label, cv2.CC_STAT_WIDTH] == 1 and stats[label, cv2.CC_STAT_HEIGHT] >= 9:
                        band[region] = 0  # Thin, full-height terminal caret.
            key = hashlib.sha256(band.tobytes() + str(band.shape).encode()).digest()
            if key not in self.cache:
                image = cv2.resize(255 - band, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                image = cv2.copyMakeBorder(image, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
                self.cache[key] = pytesseract.image_to_string(
                    image, config='--psm 7 -c load_system_dawg=0 -c load_freq_dawg=0', timeout=30).strip()
                if len(self.cache) > 2000:
                    self.cache.popitem(last=False)
            line = self.cache[key]
            if line:
                lines.append(line)
        return '\n'.join(lines)
