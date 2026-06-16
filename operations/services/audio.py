import logging
import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from openai import OpenAI

logger = logging.getLogger(__name__)


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _clean_text(text):
    cleaned = re.sub(r'\s+', ' ', str(text or '')).strip()
    if cleaned.lower() in {'um', 'uh', 'hmm', 'ah', 'oh', '...'}:
        return ''
    return cleaned


def _transcription_language(ai_config):
    language = str(getattr(ai_config, 'default_language', '') or '').strip()
    if not language or language.lower() in {'auto', 'detect'}:
        return None
    return language


def transcribe_audio(audio_file, ai_config):
    client = get_openai_client()
    audio_file.seek(0)
    filename = Path(getattr(audio_file, 'name', '') or 'voice_message.m4a').name
    content_type = mimetypes.guess_type(filename)[0] or 'audio/mp4'
    file_bytes = audio_file.read()
    audio_file.seek(0)
    kwargs = {
        'model': ai_config.transcription_model,
        'file': (filename, file_bytes, content_type),
        'prompt': (
            'Transcribe the customer exactly in the language they speak. '
            'Do not translate. If the speech is English, transcribe it as English.'
        ),
    }
    language = _transcription_language(ai_config)
    if language:
        kwargs['language'] = language

    transcription = client.audio.transcriptions.create(**kwargs)
    return transcription.text


def clean_audio_transcript(raw_transcript, conversation):
    """Clean STT output for storage/reply, without storing the raw transcript."""
    fallback = _clean_text(raw_transcript)
    if not fallback:
        return ''

    company = conversation.company
    ai_config = company.ai_config
    client = get_openai_client()
    language = _transcription_language(ai_config) or 'the customer language'

    prompt = (
        'Clean this customer voice-note transcript for a customer support chat.\n'
        'Rules:\n'
        '- Preserve the customer meaning exactly; do not invent details.\n'
        '- Do not translate. Keep the transcript in the language the customer spoke.\n'
        f'- If the text appears to be {language}, keep it in {language}.\n'
        '- Fix obvious speech-to-text mistakes, punctuation, casing, spacing, and filler words.\n'
        '- If the transcript appears to be the wrong language because of STT misdetection, correct it only when the intended wording is clear.\n'
        '- Return only the cleaned customer transcript, with no labels or commentary.'
    )

    try:
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            temperature=0.1,
            messages=[
                {
                    'role': 'system',
                    'content': (
                        f'Company: {company.name}. You clean one customer audio '
                        'message before it is saved and answered.'
                    ),
                },
                {
                    'role': 'user',
                    'content': f'{prompt}\n\nRaw transcript:\n{fallback}',
                },
            ],
        )
        cleaned = _clean_text(response.choices[0].message.content)
        return cleaned or fallback
    except Exception:
        logger.exception('Audio transcript cleanup failed; using normalized transcript.')
        return fallback


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
    raw_transcript = transcribe_audio(audio_file, ai_config)
    cleaned_transcript = clean_audio_transcript(raw_transcript, conversation)
    reply_text, metadata = generate_text_reply(conversation, cleaned_transcript)
    reply_audio_bytes = synthesize_speech(reply_text, ai_config)
    return cleaned_transcript, reply_text, reply_audio_bytes, metadata
