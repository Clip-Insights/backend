from typing import Protocol


class TranscriptionProvider(Protocol):
    def transcribe_file(self, audio_path: str) -> str: ...
