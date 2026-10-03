import unittest
import tempfile
from pathlib import Path
import cv2
import numpy as np
from analyzer import idle_intervals, commands_from_text, timestamp, analyze, Settings, CommandTracker, activity_log
from datetime import datetime


class AnalysisTests(unittest.TestCase):
    def test_typing_and_repeated_commands(self):
        tracker = CommandTracker()
        tracker.update('[root@server ~]#', 0)
        tracker.update('[root@server ~]# l', 1)
        tracker.update('[root@server ~]# ls', 2)
        tracker.update('[root@server ~]# ls\n[root@server ~]#', 3)
        tracker.update('[root@server ~]# ls\n[root@server ~]# ls', 4)
        self.assertEqual([e['command'] for e in tracker.events], ['ls', 'ls'])
        self.assertEqual([e['seconds'] for e in tracker.events], [2, 4])

    def test_history_and_dropout(self):
        tracker = CommandTracker()
        tracker.update('$ old\n$', 0)
        tracker.update('', 1)
        tracker.update('$ old\n$', 2)
        self.assertEqual(tracker.events, [])
        tracker.update('$ old\n$ mkdir test', 3)
        tracker.update('$ mkdir test\n$', 4)
        self.assertEqual([e['command'] for e in tracker.events], ['mkdir test'])

    def test_combined_log(self):
        rows = activity_log([{'seconds': 0, 'command': 'ls', 'status': 'candidate'}],
                            [(10, 31)], datetime(2025, 10, 3, 11, 27))
        self.assertEqual([r['activity'] for r in rows], ['ls', 'Idle screen', 'Idle screen', 'Idle screen'])
        self.assertEqual(rows[-1]['timestamp'], '03-10-2025 11:27:30')

    def test_static_recording(self):
        self.assertEqual(idle_intervals([(0, True), (10, False), (20, False)], 30), [(0, 20)])

    def test_activity_splits_idle(self):
        self.assertEqual(idle_intervals([(0, True), (10, False), (20, False), (30, True), (40, False)], 50), [(0, 20), (30, 40)])

    def test_short_pause_is_idle(self):
        self.assertEqual(idle_intervals([(0, True), (5, False)], 9), [(0, 5)])

    def test_continuous_changes(self):
        self.assertEqual(idle_intervals([(0, True), (5, True)], 9), [])

    def test_shell_prompts(self):
        self.assertEqual(commands_from_text('PS C:\\Users\\Test> whoami\nC:\\>dir\nuser@host:~$ ls -la\nordinary text'), ['whoami', 'dir', 'ls -la'])

    def test_clipped_powershell_prompts(self):
        text = 'S C:\\Windows> cd ..\n1S C:\\> ls\n9S C:\\> cd ../D\n2S C:\\> |'
        self.assertEqual(commands_from_text(text), ['cd ..', 'ls', 'cd ../D'])

    def test_command_payload_is_preserved(self):
        self.assertEqual(commands_from_text('PS C:\\> Get-Content File1 | Select-Object Name'), ['Get-Content File1 | Select-Object Name'])

    def test_timestamp(self):
        self.assertEqual(timestamp(3661), '01:01:01')
        self.assertEqual(timestamp(4.4), '00:00:04.400')

    def test_video_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'test.mp4')
            writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 240))
            self.assertTrue(writer.isOpened())
            for i in range(60):
                writer.write(np.full((240, 320, 3), 0 if i < 30 else 255, dtype=np.uint8))
            writer.release()
            result = analyze(path, Settings(sample_seconds=1, ocr=False))
            idle = [r for r in result['timeline'] if r['label'].startswith('Idle')]
            self.assertEqual([(r['start_seconds'], r['end_seconds']) for r in idle], [(0, 2), (3, 5)])
            self.assertAlmostEqual(sum(r['duration_seconds'] for r in result['timeline']), 6)

    def test_invalid_video(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                analyze(Path(folder) / 'missing.mp4', Settings(ocr=False))


if __name__ == '__main__':
    unittest.main()
