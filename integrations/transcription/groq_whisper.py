import os

from groq import Groq

from integrations.keys import APIKeyManager, load_api_keys


class GroqWhisperTranscription:
    def __init__(self):
        self._key_manager = APIKeyManager(load_api_keys("GROQ_API_KEYS"))

    def transcribe_file(self, audio_path: str) -> str:
        client = Groq(api_key=self._key_manager.get_next_key())
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), audio_file),
                model="whisper-large-v3",
                prompt="Specify context or spelling",
                temperature=0.0,
            )
        if hasattr(transcription, "text"):
            return transcription.text
        return str(transcription)
