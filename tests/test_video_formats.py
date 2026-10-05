import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from analyzer import Settings, analyze
from screenshots import collect_screenshots
from video_io import open_video, preview_frame, upload_suffix


class VideoFormatTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def make_video(self, extension):
        source = self.root / ('source.mp4' if extension == '.mp4' else 'source.avi')
        codec = 'mp4v' if extension == '.mp4' else 'MJPG'
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*codec), 10, (160, 120))
        self.assertTrue(writer.isOpened())
        for index in range(20):
            writer.write(np.full((120, 160, 3), 40 if index < 10 else 180, dtype=np.uint8))
        writer.release()
        path = self.root / ('recording' + extension)
        path.write_bytes(source.read_bytes())
        return path

    def test_all_decodable_formats_support_analysis_screenshots_and_preview(self):
        # VID here is explicitly a standard AVI stream under a VID extension,
        # not a claim of support for proprietary Citrix recording data.
        for extension in ('.mp4', '.avi', '.vid'):
            with self.subTest(extension=extension):
                path = self.make_video(extension)
                result = analyze(path, Settings(sample_seconds=0.5, ocr=False))
                self.assertAlmostEqual(result['duration_seconds'], 2)
                self.assertTrue(any(row['label'].startswith('Idle') for row in result['timeline']))
                shots = collect_screenshots(path)
                self.assertEqual([row['frame_index'] for row in shots['rows']], [0, 10, 19])
                first, _ = preview_frame(path, 0)
                last, time = preview_frame(path, 100)
                first_pixels = cv2.imdecode(np.frombuffer(first, np.uint8), cv2.IMREAD_COLOR)
                last_pixels = cv2.imdecode(np.frombuffer(last, np.uint8), cv2.IMREAD_COLOR)
                self.assertGreater(last_pixels.mean(), first_pixels.mean())
                self.assertAlmostEqual(time, 1.9)

    def test_avi_and_vid_use_command_tracking(self):
        for extension in ('.avi', '.vid'):
            with self.subTest(extension=extension):
                with patch('analyzer.ScreenOCR.read', side_effect=['$', '$ ls', '$ ls\n$', '$ ls\n$']):
                    result = analyze(self.make_video(extension), Settings(sample_seconds=0.5))
                self.assertEqual([row['command'] for row in result['commands']], ['ls'])

    def test_unreadable_vid_has_export_guidance_in_both_workflows(self):
        path = self.root / 'native.vid'
        path.write_bytes(b'undecodable proprietary recording test data')
        for action in (lambda: analyze(path, Settings(ocr=False)), lambda: collect_screenshots(path)):
            with self.assertRaisesRegex(ValueError, 'exported.*MP4 or AVI'):
                action()

    def test_corrupt_avi_rejected(self):
        path = self.root / 'broken.avi'
        path.write_bytes(b'not a video')
        with self.assertRaisesRegex(ValueError, 'unsupported codec'):
            with open_video(path):
                self.fail('Invalid video accepted')

    def test_suffix_validation(self):
        self.assertEqual(upload_suffix('SESSION.AVI'), '.avi')
        self.assertEqual(upload_suffix('capture.VID'), '.vid')
        with self.assertRaises(ValueError):
            upload_suffix('capture.exe')

    def test_invalid_preview_time(self):
        with self.assertRaises(ValueError):
            preview_frame(self.make_video('.avi'), float('nan'))
