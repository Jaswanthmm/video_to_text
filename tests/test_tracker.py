import unittest

from command_tracker import CommandTracker


def parse_prompts(text):
    return [line[1:].strip() for line in text.splitlines() if line.startswith('$')]


class TrackerTests(unittest.TestCase):
    def tracker(self, frames):
        tracker = CommandTracker(parser=parse_prompts)
        for seconds, text in frames:
            tracker.update(text, seconds)
        return tracker

    def test_late_first_command_is_retained_with_unknown_typing_time(self):
        tracker = self.tracker([(0, 'unreadable'), (5, '$ ls'), (6, '$ ls\n$')])
        self.assertEqual([event['command'] for event in tracker.events], ['ls'])
        self.assertEqual(tracker.events[0]['seconds'], 5)
        self.assertIn('typing time unknown', tracker.events[0]['status'])

    def test_late_baseline_retains_only_last_nonempty_command(self):
        tracker = self.tracker([(0, ''), (5, '$ old\n$ recent\n$')])
        self.assertEqual([event['command'] for event in tracker.events], ['recent'])

    def test_initial_history_and_historical_ocr_jitter_do_not_create_events(self):
        tracker = self.tracker([(0, '$ old\n$'), (1, '$ oId\n$'), (2, '$ old\n$')])
        self.assertEqual(tracker.events, [])

    def test_completed_command_ocr_variation_does_not_add_or_retime_event(self):
        tracker = self.tracker([(0, '$'), (1, '$ ls'), (2, '$ ls\n$'), (3, '$ 1s\n$')])
        self.assertEqual([event['command'] for event in tracker.events], ['ls'])
        self.assertEqual(tracker.events[0]['seconds'], 1)

    def test_partial_input_evolves_and_intentional_repeats_are_retained(self):
        tracker = self.tracker([(0, '$'), (1, '$ l'), (2, '$ ls'), (3, '$ ls\n$'),
                                (4, '$ ls\n$ ls'), (5, '$ ls\n$ ls\n$')])
        self.assertEqual([event['command'] for event in tracker.events], ['ls', 'ls'])
        self.assertEqual([event['seconds'] for event in tracker.events], [2, 4])

    def test_arbitrary_corrections_on_one_active_prompt_are_one_input(self):
        tracker = self.tracker([(0, '$'), (1, '$ ls'), (2, '$ ps'), (3, '$ id'),
                                (4, '$ cd'), (5, '$ whoami')])
        self.assertEqual([event['command'] for event in tracker.events], ['whoami'])

    def test_completed_command_is_not_overwritten_when_trailing_prompt_drops_out(self):
        tracker = self.tracker([(0, '$'), (1, '$ ls'), (2, '$ ls\n$'),
                                (3, '$ ls'), (4, '$ ls -lrt')])
        self.assertEqual([event['command'] for event in tracker.events], ['ls', 'ls -lrt'])

    def test_added_arguments_do_not_overwrite_completed_command(self):
        tracker = self.tracker([(0, '$'), (1, '$ Get-Process'), (2, '$ Get-Process\n$'),
                                (3, '$ Get-Process -Name'), (4, '$ Get-Process -Name explorer')])
        self.assertEqual([event['command'] for event in tracker.events],
                         ['Get-Process', 'Get-Process -Name explorer'])

    def test_recovered_history_is_not_logged_twice(self):
        tracker = self.tracker([(0, '$'), (1, '$ ls'), (2, '$ ls\n$ whoami'),
                                (3, '$ whoami'), (4, '$ ls\n$ whoami\n$')])
        self.assertEqual([event['command'] for event in tracker.events], ['ls', 'whoami'])

    def test_clearing_active_prompt_allows_same_command_again(self):
        tracker = self.tracker([(0, '$'), (1, '$ ls'), (2, '$'), (3, '$ ls')])
        self.assertEqual([event['command'] for event in tracker.events], ['ls', 'ls'])

    def test_cursor_only_prompts_are_not_commands(self):
        tracker = self.tracker([(0, ''), (1, '$ █'), (2, '$ |'), (3, '$ _'), (4, '$  ')])
        self.assertEqual(tracker.events, [])

    def test_dropout_does_not_discard_current_prompt(self):
        tracker = self.tracker([(0, '$'), (1, '$ mk'), (2, 'unreadable'), (3, '$ mkdir test')])
        self.assertEqual([event['command'] for event in tracker.events], ['mkdir test'])

    def test_repeated_final_reading_keeps_earliest_observation_time(self):
        tracker = self.tracker([(0, '$'), (1.2, '$ ls'), (1.3, '$ 1s'),
                                (1.4, '$ ls'), (1.5, '$ ls'), (1.6, '$ ls\n$')])
        self.assertEqual(len(tracker.events), 1)
        self.assertEqual(tracker.events[0]['command'], 'ls')
        self.assertEqual(tracker.events[0]['seconds'], 1.2)
        self.assertEqual(tracker.events[0]['timestamp'], '00:00:01.200')

    def test_fractional_timestamp_rounds_without_float_noise(self):
        tracker = self.tracker([(0, '$'), (5.300000000000001, '$ ls')])
        self.assertEqual(tracker.events[0]['timestamp'], '00:00:05.300')

    def test_scrolled_input_is_followed_by_a_new_prompt(self):
        tracker = self.tracker([(0, '$'), (1, '$ ls'), (2, 'directory output'), (3, '$')])
        self.assertIn('Followed by another prompt', tracker.events[0]['status'])

    def test_typing_noise_and_scrolling_produce_four_final_commands(self):
        tracker = self.tracker([
            (0.1, '$'), (3.6, '$ cll'), (3.7, '$ cd'), (4.1, '$ cd .'),
            (4.2, '$ cd ..|/'), (4.4, '$ cd ..\n$'),
            (5.1, '$ cd ..\n$ Us'), (5.2, '$ cd ..\n$ Ls'), (5.3, '$ cd ..\n$ ls'),
            (5.4, 'directory output'), (5.5, '$'),
            (7.5, '$ cid'), (7.7, '$ cd'), (8.2, '$ cd .|'), (8.3, '$ cd ..|/'),
            (8.5, '$ cd ..\n$'),
            (9.6, '$ cd ..\n$ cH'), (9.7, '$ cd ..\n$ cd'), (9.8, '$ cd ..\n$ ed'),
            (10.3, '$ cd ..\n$ cd'), (10.8, '$ cd ..\n$ cd ||'), (10.9, '$ cd ..\n$ cd.'),
            (11.0, '$ cd ..\n$ cd ../'), (11.6, '$ cd ..\n$ cd ..'),
            (11.7, '$ cd ..\n$ cd ..//'), (12.5, '$ cd ..\n$ cd ..'),
            (13.0, '$ cd ..\n$ cd ..//'), (13.2, '$ cd ..\n$ cd ../p'),
            (13.9, '$ cd ..\n$ cd ../D|'), (14.2, '$ cd ..\n$ cd ../D'),
            (14.6, '$ cd ..\n$ cd ../D'), (14.7, '$ cd ..\n$ cd ../D\n$'),
        ])
        self.assertEqual([event['command'] for event in tracker.events], ['cd ..', 'ls', 'cd ..', 'cd ../D'])
        self.assertEqual([event['seconds'] for event in tracker.events], [4.4, 5.3, 8.5, 14.2])


if __name__ == '__main__':
    unittest.main()
