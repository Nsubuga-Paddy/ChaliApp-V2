import asyncio
import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from openai import OpenAI

from operations.models import CatalogImportJob, MenuCategory, MenuItem

logger = logging.getLogger(__name__)

PRICE_RE = re.compile(
    r'(?P<currency>UGX|USh|USH|USD|\$)?\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)',
    re.IGNORECASE,
)
MENU_TEXT_HINTS = (
    'menu',
    'order',
    'ugx',
    'ush',
    'price',
    'breakfast',
    'drinks',
    'mains',
    'dessert',
)


@dataclass
class RenderedCatalogPage:
    html: str
    final_url: str
    render_mode: str
    screenshot_bytes: bytes | None = None
    log: str = ''


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def normalize_currency(value: str | None) -> str:
    normalized = (value or '').strip().upper()
    if normalized in {'USH', 'USH.', 'USHILLINGS'}:
        return 'UGX'
    if normalized == '$':
        return 'USD'
    return normalized or 'UGX'


def parse_price(value: Any) -> Decimal | None:
    if value in (None, ''):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    text = str(value).replace(',', '').strip()
    match = PRICE_RE.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group('amount'))
    except InvalidOperation:
        return None


def compact_html_for_extraction(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html or '', 'lxml')
    for tag in soup(['style', 'noscript', 'svg']):
        tag.decompose()

    image_lines = []
    for img in soup.find_all('img')[:250]:
        src = (
            img.get('src')
            or img.get('data-src')
            or img.get('data-original')
            or img.get('data-lazy-src')
        )
        srcset = img.get('srcset') or img.get('data-srcset')
        if not src and srcset:
            src = srcset.split(',')[0].strip().split(' ')[0]
        if not src:
            continue
        image_lines.append(
            'IMAGE: '
            f"url={urljoin(base_url, src)} "
            f"alt={(img.get('alt') or '').strip()} "
            f"title={(img.get('title') or '').strip()}"
        )

    text = soup.get_text('\n', strip=True)
    script_snippets = []
    for script in soup.find_all('script')[:80]:
        content = (script.string or script.get_text() or '').strip()
        if not content:
            continue
        lowered = content.lower()
        if any(hint in lowered for hint in MENU_TEXT_HINTS):
            script_snippets.append(content[:6000])

    combined = '\n'.join(
        part
        for part in (
            text,
            '\n'.join(image_lines),
            '\n\nSCRIPT DATA:\n' + '\n---\n'.join(script_snippets) if script_snippets else '',
        )
        if part
    )
    return combined[: settings.CATALOG_IMPORT_MAX_HTML_CHARS]


def fetch_static_page(url: str) -> RenderedCatalogPage:
    response = requests.get(
        url,
        timeout=settings.CATALOG_IMPORT_TIMEOUT_SECONDS,
        headers={
            'User-Agent': 'ChaliCatalogImporter/1.0 (+restaurant-catalog-onboarding)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
    )
    response.raise_for_status()
    return RenderedCatalogPage(
        html=response.text,
        final_url=response.url,
        render_mode=CatalogImportJob.RenderMode.STATIC,
        log=f'Static fetch succeeded with {len(response.text)} HTML characters.',
    )


async def _render_headless_page(url: str) -> RenderedCatalogPage:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            'Playwright is not installed. Add it to the worker image and install Chromium.'
        ) from exc

    timeout_ms = settings.CATALOG_IMPORT_HEADLESS_TIMEOUT_SECONDS * 1000
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--no-sandbox'])
        page = await browser.new_page(
            viewport={'width': 1440, 'height': 2200},
            user_agent='ChaliCatalogImporter/1.0 (+restaurant-catalog-onboarding)',
        )
        await page.goto(url, wait_until='networkidle', timeout=timeout_ms)
        for _ in range(4):
            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(700)
        html = await page.content()
        screenshot = await page.screenshot(full_page=True, type='png')
        final_url = page.url
        await browser.close()

    return RenderedCatalogPage(
        html=html,
        final_url=final_url,
        render_mode=CatalogImportJob.RenderMode.HEADLESS,
        screenshot_bytes=screenshot,
        log=f'Headless render succeeded with {len(html)} HTML characters.',
    )


def render_catalog_page(job: CatalogImportJob) -> RenderedCatalogPage:
    if (
        job.render_mode == CatalogImportJob.RenderMode.HEADLESS
        or settings.CATALOG_IMPORT_HEADLESS_ENABLED
    ):
        try:
            return asyncio.run(_render_headless_page(job.source_url))
        except Exception as exc:
            logger.warning('Headless catalog render failed for %s: %s', job.source_url, exc)
            static_page = fetch_static_page(job.source_url)
            static_page.log = f'Headless render failed: {exc}\n{static_page.log}'
            return static_page

    return fetch_static_page(job.source_url)


def _json_schema() -> dict[str, Any]:
    return {
        'name': 'restaurant_catalog_import',
        'strict': True,
        'schema': {
            'type': 'object',
            'additionalProperties': False,
            'properties': {
                'items': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {
                            'name': {'type': 'string'},
                            'description': {'type': 'string'},
                            'category': {'type': 'string'},
                            'price': {'type': ['number', 'string', 'null']},
                            'currency': {'type': 'string'},
                            'image_url': {'type': ['string', 'null']},
                            'confidence': {'type': 'number'},
                        },
                        'required': [
                            'name',
                            'description',
                            'category',
                            'price',
                            'currency',
                            'image_url',
                            'confidence',
                        ],
                    },
                },
            },
            'required': ['items'],
        },
    }


def extract_catalog_with_openai(rendered: RenderedCatalogPage) -> list[dict[str, Any]]:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError('OPENAI_API_KEY is not configured.')

    extraction_input = compact_html_for_extraction(rendered.html, rendered.final_url)
    response = get_openai_client().chat.completions.create(
        model=settings.OPENAI_CATALOG_IMPORT_MODEL,
        messages=[
            {
                'role': 'system',
                'content': (
                    'Extract restaurant menu/catalog items from the provided rendered page. '
                    'Return only real customer-orderable items, not navigation labels, footer links, '
                    'marketing copy, or unrelated add-ons unless they are clearly menu items. '
                    'Preserve item names, descriptions, categories, prices, currency, and matching image URLs. '
                    'If a field is unknown, use an empty string or null. Prices must be numeric when possible.'
                ),
            },
            {'role': 'user', 'content': extraction_input},
        ],
        temperature=0,
        response_format={'type': 'json_schema', 'json_schema': _json_schema()},
    )
    content = response.choices[0].message.content or '{}'
    payload = json.loads(content)
    return payload.get('items') or []


def extract_catalog_heuristically(rendered: RenderedCatalogPage) -> list[dict[str, Any]]:
    """Cheap fallback for simple static pages with heading/description/price blocks."""
    soup = BeautifulSoup(rendered.html or '', 'lxml')
    items = []
    current_category = ''
    for heading in soup.find_all(['h2', 'h3', 'h4'])[:300]:
        name = heading.get_text(' ', strip=True)
        if not name:
            continue
        if heading.name == 'h2':
            current_category = name
            continue

        description = ''
        price = None
        for sibling in heading.find_next_siblings(limit=5):
            text = sibling.get_text(' ', strip=True)
            if not text:
                continue
            if sibling.name in {'h2', 'h3', 'h4'}:
                break
            match = PRICE_RE.search(text)
            if match:
                price = match.group('amount')
                break
            if not description:
                description = text
        if price:
            items.append({
                'name': name,
                'description': description,
                'category': current_category,
                'price': price,
                'currency': 'UGX',
                'image_url': None,
                'confidence': 0.55,
            })
    return items


def extract_catalog_items(rendered: RenderedCatalogPage) -> tuple[list[dict[str, Any]], str]:
    try:
        items = extract_catalog_with_openai(rendered)
        return items, 'openai'
    except Exception as exc:
        logger.exception('OpenAI catalog extraction failed')
        fallback = extract_catalog_heuristically(rendered)
        return fallback, f'heuristic fallback after OpenAI failure: {exc}'


def get_or_create_category(company, name: str) -> MenuCategory | None:
    cleaned = (name or '').strip()
    if not cleaned:
        return None
    category = (
        MenuCategory.objects.filter(company=company, name__iexact=cleaned)
        .order_by('id')
        .first()
    )
    if category:
        return category
    return MenuCategory.objects.create(company=company, name=cleaned)


def download_menu_item_image(item: MenuItem, image_url: str) -> bool:
    if not image_url or item.image:
        return False
    try:
        response = requests.get(
            image_url,
            timeout=settings.CATALOG_IMPORT_TIMEOUT_SECONDS,
            headers={'User-Agent': 'ChaliCatalogImporter/1.0'},
        )
        response.raise_for_status()
        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('image/'):
            return False
        ext = content_type.split('/')[-1].split(';')[0].lower()
        if ext == 'jpeg':
            ext = 'jpg'
        filename = f'menu_item_{item.id}.{ext or "jpg"}'
        item.image.save(filename, ContentFile(response.content), save=True)
        return True
    except Exception:
        logger.exception('Failed to download menu item image %s', image_url)
        return False


def persist_extracted_items(job: CatalogImportJob, extracted_items: list[dict[str, Any]]) -> int:
    created_or_updated = 0
    company = job.company

    for raw in extracted_items:
        name = (raw.get('name') or '').strip()
        if not name:
            continue

        category = get_or_create_category(company, raw.get('category') or '')
        price = parse_price(raw.get('price'))
        currency = normalize_currency(raw.get('currency'))
        image_url = (raw.get('image_url') or '').strip()
        if image_url:
            image_url = urljoin(job.source_url, image_url)

        item = MenuItem.objects.filter(company=company, name__iexact=name).order_by('id').first()
        if item is None:
            item = MenuItem(company=company, name=name)
        elif item.status == MenuItem.Status.PUBLISHED:
            item.metadata = {
                **(item.metadata or {}),
                'latest_import_suggestion': raw,
                'latest_import_job_id': job.id,
            }
            item.needs_review = True
            item.save(update_fields=['metadata', 'needs_review', 'updated_at'])
            created_or_updated += 1
            continue

        item.category = category
        item.description = (raw.get('description') or '').strip()
        item.price = price
        item.currency = currency
        item.source_image_url = image_url
        item.source_url = job.source_url
        try:
            item.extraction_confidence = float(raw.get('confidence') or 0)
        except (TypeError, ValueError):
            item.extraction_confidence = None
        item.status = MenuItem.Status.DRAFT
        item.needs_review = True
        item.metadata = {
            **(item.metadata or {}),
            'catalog_import_job_id': job.id,
            'raw_extraction': raw,
        }
        item.save()

        if settings.CATALOG_IMPORT_DOWNLOAD_IMAGES and image_url:
            download_menu_item_image(item, image_url)
        created_or_updated += 1

    return created_or_updated


def import_catalog(job: CatalogImportJob) -> CatalogImportJob:
    job.status = CatalogImportJob.Status.RENDERING
    job.log = ''
    job.save(update_fields=['status', 'log', 'updated_at'])

    try:
        rendered = render_catalog_page(job)
        job.render_mode = rendered.render_mode
        job.raw_html = rendered.html[: settings.CATALOG_IMPORT_MAX_HTML_CHARS]
        job.log = rendered.log
        if rendered.screenshot_bytes:
            job.screenshot.save(
                f'catalog_import_{job.id}.png',
                ContentFile(rendered.screenshot_bytes),
                save=False,
            )
        job.status = CatalogImportJob.Status.EXTRACTING
        job.save(update_fields=['status', 'render_mode', 'raw_html', 'screenshot', 'log', 'updated_at'])

        extracted_items, extractor = extract_catalog_items(rendered)
        with transaction.atomic():
            item_count = persist_extracted_items(job, extracted_items)
            job.items_found = item_count
            job.metadata = {
                **(job.metadata or {}),
                'extractor': extractor,
                'source_item_count': len(extracted_items),
                'final_url': rendered.final_url,
            }
            job.status = CatalogImportJob.Status.REVIEW if item_count else CatalogImportJob.Status.FAILED
            if not item_count:
                job.log = f'{job.log}\nNo menu items were extracted.'
            job.save(update_fields=['items_found', 'metadata', 'status', 'log', 'updated_at'])
    except Exception as exc:
        logger.exception('Catalog import failed for job %s', job.id)
        job.status = CatalogImportJob.Status.FAILED
        job.log = f'{job.log}\nCatalog import failed: {exc}'.strip()
        job.save(update_fields=['status', 'log', 'updated_at'])
        raise

    return job


def schedule_catalog_import(job: CatalogImportJob) -> None:
    from operations.tasks import import_catalog_job

    import_catalog_job.delay(job.id)
