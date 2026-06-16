import logging
import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from openai import OpenAI

logger = logging.getLogger(__name__)


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def transcribe_audio(audio_file, ai_config):
    client = get_openai_client()
    audio_file.seek(0)
    filename = Path(getattr(audio_file, 'name', '') or 'voice_message.m4a').name
    content_type = mimetypes.guess_type(filename)[0] or 'audio/mp4'
    file_bytes = audio_file.read()
    audio_file.seek(0)
    transcription = client.audio.transcriptions.create(
        model=ai_config.transcription_model,
        file=(filename, file_bytes, content_type),
    )
    return transcription.text


def synthesize_speech(text, ai_config):
    client = get_openai_client()
    response = client.audio.speech.create(
        model=ai_config.tts_model,
        voice=ai_config.tts_voice,
        input=text,
    )
    return response.content


def process_audio_message(conversation, audio_file):
    from .text import generate_text_reply

    ai_config = conversation.company.ai_config
    transcript = transcribe_audio(audio_file, ai_config)
    reply_text, metadata = generate_text_reply(conversation, transcript)
    reply_audio_bytes = synthesize_speech(reply_text, ai_config)
    return transcript, reply_text, reply_audio_bytes, metadata
