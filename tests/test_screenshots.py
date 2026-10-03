import csv
import io
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from screenshots import capture_targets, collect_screenshots


class ScreenshotTests(unittest.TestCase):
    def test_under_ten_minutes(self):
        self.assertEqual(capture_targets(100, 10), [('start', 0), ('mid', 50), ('end', 99)])

    def test_ten_minute_boundary_and_long_video(self):
        self.assertEqual(capture_targets(6000, 10), [('start', 0), ('mid', 3000), ('end', 5999)])
        self.assertEqual(capture_targets(12001, 10), [('start', 0), ('mid', 6000), ('end', 12000)])

    def test_long_video_keeps_intervals_and_required_positions(self):
        self.assertEqual(capture_targets(18000, 10), [('start', 0), ('interval', 6000),
                         ('mid', 9000), ('interval', 12000), ('end', 17999)])

    def test_single_frame_keeps_three_labeled_positions(self):
        self.assertEqual(capture_targets(1, 25), [('start', 0), ('mid', 0), ('end', 0)])

    def test_frames_and_zip_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'short.mp4'
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 240))
            self.assertTrue(writer.isOpened())
            for value in range(20):
                writer.write(np.full((240, 320, 3), value * 10, dtype=np.uint8))
            writer.release()
            result = collect_screenshots(path, datetime(2026, 10, 3, 12, 0))
            self.assertEqual([r['frame_index'] for r in result['rows']], [0, 10, 19])
            self.assertEqual(result['rows'][-1]['recording_timestamp'], '03-10-2026 12:00:01.900')
            with zipfile.ZipFile(io.BytesIO(result['zip'])) as archive:
                self.assertEqual(len(archive.namelist()), 4)
                rows = list(csv.DictReader(io.StringIO(archive.read('timestamps.csv').decode())))
                self.assertEqual(len(rows), 3)
                means = []
                for row in rows:
                    image = cv2.imdecode(np.frombuffer(archive.read(row['file']), np.uint8), cv2.IMREAD_COLOR)
                    self.assertGreater(image.shape[0], 240)
                    means.append(image[:240].mean())
                self.assertTrue(means[0] < means[1] < means[2])

    def test_bad_video(self):
        with self.assertRaises(ValueError):
            collect_screenshots('not-a-real-recording.mp4')
