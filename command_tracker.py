"""Track observations of terminal prompts without treating old output as new input."""

from dataclasses import dataclass, field
from difflib import SequenceMatcher


def _timestamp(seconds):
    milliseconds = round(float(seconds) * 1000)
    seconds, fraction = divmod(milliseconds, 1000)
    label = f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
    return f"{label}.{fraction:03}" if fraction else label


def _clean(command):
    command = command.strip()
    # A block or caret on an otherwise empty prompt is not a command.
    return "" if command and all(char in "|_▏▎▍▌▋▊▉█▐▕▖▗▘▙▚▛▜▝▞▟▯▮▭▰" for char in command) else command


def _similar(left, right):
    """Conservative character similarity; never rewrite characters by guesswork."""
    if not left or not right:
        return False
    ratio = SequenceMatcher(a=left, b=right, autojunk=False).ratio()
    # A single OCR error in a two-character command still has a low ratio.
    if max(len(left), len(right)) <= 4:
        if len(left) == len(right):
            return sum(a != b for a, b in zip(left, right)) <= 1
        shorter, longer = sorted((left, right), key=len)
        return len(longer) - len(shorter) == 1 and any(
            longer[:i] + longer[i + 1:] == shorter for i in range(len(longer))
        )
    return ratio >= 0.75


@dataclass
class _Prompt:
    command: str
    ordinal: int
    event: dict | None = None
    completed: bool = False
    unknown_time: bool = False
    readings: dict = field(default_factory=dict)
    first_seen: dict = field(default_factory=dict)


class CommandTracker:
    """Keep command instances, evolving input, and already visible history distinct.

    Timestamps are observation times. An initial command first recognized after the
    recording began is retained, but its actual typing time is explicitly unknown.
    """

    def __init__(self, parser=None):
        self.parser = parser
        self.previous = None
        self.references = []
        self.events = []
        self._history = []

    def _new(self, command, seconds, emit=True, unknown_time=False):
        row = _Prompt(command, len(self._history), unknown_time=unknown_time)
        if command:
            row.readings[command] = 1
            row.first_seen[command] = float(seconds)
        self._history.append(row)
        if command and emit:
            self._emit(row, seconds)
        return row

    def _emit(self, row, seconds):
        row.event = {
            "seconds": float(seconds), "timestamp": _timestamp(seconds),
            "command": row.command, "status": "Visible input; submission unverified",
        }
        self.events.append(row.event)
        self._status(row)

    @staticmethod
    def _status(row):
        if row.event is None:
            return
        if row.unknown_time:
            row.event["status"] = "First observed in recording; typing time unknown"
        elif row.completed:
            row.event["status"] = "Followed by another prompt; OCR candidate"
        else:
            row.event["status"] = "Visible input; submission unverified"

    def _historical_reading(self, row, command):
        # A corrected reading of old output cannot acquire a new typing timestamp.
        row.readings[command] = row.readings.get(command, 0) + 1
        best = max(row.readings, key=row.readings.get)
        row.command = best
        if row.event is not None:
            row.event["command"] = best
        return row

    def _evolve(self, row, command, seconds):
        row.command = command
        row.readings = {command: 1}
        first_seen = row.first_seen.setdefault(command, float(seconds))
        row.unknown_time = False
        if row.event is None:
            self._emit(row, first_seen)
        else:
            row.event.update(seconds=first_seen, timestamp=_timestamp(first_seen), command=command)
            self._status(row)
        return row

    def update(self, text, seconds):
        if self.parser is None:
            # analyzer imports this class, so resolve its parser only when called.
            from analyzer import prompt_lines
            parser = prompt_lines
        else:
            parser = self.parser
        current = [_clean(command) for command in parser(text)]
        if not current:
            # Missing OCR is not evidence that terminal history was cleared.
            return
        if self.previous is None:
            self.references = [self._new(command, seconds, emit=False) for command in current]
            if seconds > 0:
                for row in reversed(self.references):
                    if row.command:
                        row.unknown_time = True
                        self._emit(row, seconds)
                        break
            self._finish(current, self.references)
            return

        references = [None] * len(current)
        opcodes = SequenceMatcher(a=self.previous, b=current, autojunk=False).get_opcodes()
        # Establish exact anchors before assigning changed or recovered rows.
        for tag, a, b, c, d in opcodes:
            if tag == "equal":
                references[c:d] = self.references[a:b]
                for index in range(c, d):
                    if current[index]:
                        self._historical_reading(references[index], current[index])

        for tag, a, b, c, d in opcodes:
            if tag in ("equal", "delete"):
                continue
            for index in range(c, d):
                command = current[index]
                row = None
                old_index = a + index - c
                if tag == "replace" and old_index < b:
                    old = self.references[old_index]
                    old_command = self.previous[old_index]
                    if old.completed:
                        # Added or removed arguments on a completed command are
                        # another observation, not more typing on the old event.
                        prefix_edit = command.startswith(old_command) or old_command.startswith(command)
                        if command and not prefix_edit and _similar(old_command, command):
                            row = self._historical_reading(old, command)
                    elif command:
                        # Until another prompt is observed, this remains the
                        # same editable input line. OCR errors and arbitrary
                        # corrections must not become separate command events.
                        row = self._evolve(old, command, seconds)
                    elif not old_command:
                        row = old

                if row is None and command:
                    # OCR can temporarily omit an old row, then recover it. Reuse
                    # it only before an existing chronological anchor; never dedup
                    # a newly typed repeated command at the end of the terminal.
                    following = next((ref for ref in references[index + 1:] if ref is not None), None)
                    preceding = next((ref for ref in reversed(references[:index]) if ref is not None), None)
                    if following is not None:
                        lower = preceding.ordinal if preceding is not None else -1
                        already_used = {id(ref) for ref in references if ref is not None}
                        for candidate in reversed(self._history):
                            if (lower < candidate.ordinal < following.ordinal
                                    and id(candidate) not in already_used
                                    and command in candidate.readings):
                                row = self._historical_reading(candidate, command)
                                break
                if row is None:
                    row = self._new(command, seconds)
                references[index] = row
        if current[-1] == "" and self.previous[-1]:
            old_active = self.references[-1]
            if not any(row is old_active for row in references):
                # Output may scroll the submitted input off screen completely.
                old_active.completed = True
                self._status(old_active)
        self._finish(current, references)

    def _finish(self, current, references):
        for index, row in enumerate(references):
            if index < len(current) - 1:
                row.completed = True
            self._status(row)
        self.previous, self.references = current, references
