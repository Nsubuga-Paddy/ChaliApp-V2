import json
import logging
import re
from typing import Any

from operations.services.text import get_openai_client

logger = logging.getLogger(__name__)

CUSTOMER_LABEL = 'You'
ASSISTANT_LABEL = 'ChaliAssistant'

_ROLE_ALIASES = {
    'customer': 'customer',
    'user': 'customer',
    'caller': 'customer',
    'assistant': 'assistant',
    'agent': 'assistant',
    'ai': 'assistant',
    'chaliassistant': 'assistant',
}


def _normalize_role(raw_role: Any) -> str:
    role = str(raw_role or 'unknown').strip().lower()
    return _ROLE_ALIASES.get(role, role)


def _clean_text(text: Any) -> str:
    cleaned = re.sub(r'\s+', ' ', str(text or '')).strip()
    if len(cleaned) < 2:
        return ''
    if cleaned.lower() in {'um', 'uh', 'hmm', 'ah', 'oh', '...'}:
        return ''
    return cleaned


def normalize_transcript(transcript: list[dict]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for entry in transcript or []:
        if not isinstance(entry, dict):
            continue
        role = _normalize_role(entry.get('role'))
        text = _clean_text(entry.get('text'))
        if role not in {'customer', 'assistant'} or not text:
            continue
        if normalized and normalized[-1]['role'] == role:
            normalized[-1]['text'] = f"{normalized[-1]['text']} {text}".strip()
        else:
            normalized.append({'role': role, 'text': text})
    return normalized


def format_transcript_lines(
    transcript: list[dict[str, str]],
    *,
    customer_label: str = CUSTOMER_LABEL,
    assistant_label: str = ASSISTANT_LABEL,
) -> str:
    lines: list[str] = []
    for entry in transcript:
        label = customer_label if entry['role'] == 'customer' else assistant_label
        lines.append(f'{label}: {entry["text"]}')
    return '\n\n'.join(lines)


def _fallback_summary(transcript: list[dict[str, str]], duration_seconds: int | None) -> dict[str, str]:
    customer_lines = [entry['text'] for entry in transcript if entry['role'] == 'customer']
    assistant_lines = [entry['text'] for entry in transcript if entry['role'] == 'assistant']
    issue = customer_lines[0] if customer_lines else 'Issue discussed during the call'
    solution = assistant_lines[-1] if assistant_lines else 'No advice captured from the assistant.'
    duration_note = f'Call duration: {duration_seconds} seconds.' if duration_seconds else ''
    summary = ' '.join(part for part in [issue, solution, duration_note] if part).strip()
    return {
        'customer_issue': issue,
        'solution': solution,
        'summary': summary or 'Voice call completed.',
        'formatted_transcript': format_transcript_lines(transcript),
    }


def process_call_transcript(
    transcript: list[dict],
    *,
    company_name: str = 'Support',
    duration_seconds: int | None = None,
) -> dict[str, Any]:
    normalized = normalize_transcript(transcript)
    if not normalized:
        return {
            'customer_issue': '',
            'solution': '',
            'summary': 'Voice call completed with no captured conversation.',
            'formatted_transcript': '',
            'transcript': [],
        }

    fallback = _fallback_summary(normalized, duration_seconds)
    if len(normalized) < 2:
        return {**fallback, 'transcript': normalized}

    raw_lines = format_transcript_lines(normalized, customer_label='Customer', assistant_label='Assistant')
    duration_text = f'{duration_seconds} seconds' if duration_seconds else 'unknown'

    prompt = (
        'You clean up a customer support voice call transcript.\n'
        'Fix obvious speech-to-text mistakes, remove filler-only lines, and produce a clear summary.\n'
        'Keep factual content only. Do not invent details that are not supported by the transcript.\n'
        'Return JSON with keys:\n'
        '- customer_issue: one concise sentence describing what the customer needed\n'
        '- solution: one concise sentence describing what the assistant advised or resolved\n'
        '- summary: 2-3 sentence plain-language recap of the call\n'
        '- formatted_transcript: multi-line transcript using exactly these speaker labels: '
        f'"{CUSTOMER_LABEL}:" and "{ASSISTANT_LABEL}:" with a blank line between turns\n'
    )

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            temperature=0.2,
            response_format={'type': 'json_object'},
            messages=[
                {
                    'role': 'system',
                    'content': (
                        f'Company: {company_name}. Call duration: {duration_text}. '
                        'Respond with valid JSON only.'
                    ),
                },
                {
                    'role': 'user',
                    'content': f'{prompt}\n\nRaw transcript:\n{raw_lines}',
                },
            ],
        )
        content = response.choices[0].message.content or '{}'
        parsed = json.loads(content)
        formatted = _clean_text(parsed.get('formatted_transcript')) or fallback['formatted_transcript']
        return {
            'customer_issue': _clean_text(parsed.get('customer_issue')) or fallback['customer_issue'],
            'solution': _clean_text(parsed.get('solution')) or fallback['solution'],
            'summary': _clean_text(parsed.get('summary')) or fallback['summary'],
            'formatted_transcript': formatted,
            'transcript': normalized,
        }
    except Exception:
        logger.exception('Call transcript summarization failed; using fallback formatting.')
        return {**fallback, 'transcript': normalized}


def build_chat_call_summary_message(processed: dict[str, Any], *, duration_seconds: int | None) -> str:
    duration_text = ''
    if duration_seconds is not None:
        minutes, seconds = divmod(max(duration_seconds, 0), 60)
        duration_text = f'{minutes}m {seconds}s'

    parts = ['Voice Call Summary']
    if duration_text:
        parts.append(f'Duration: {duration_text}')
    if processed.get('customer_issue'):
        parts.append(f"What you needed help with:\n{processed['customer_issue']}")
    if processed.get('solution'):
        parts.append(f"What you were advised:\n{processed['solution']}")
    if processed.get('summary'):
        parts.append(f'Recap:\n{processed["summary"]}')
    if processed.get('formatted_transcript'):
        parts.append(f'Transcript:\n{processed["formatted_transcript"]}')
    return '\n\n'.join(parts)
