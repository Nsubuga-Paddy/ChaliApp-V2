import hashlib
import logging
import mimetypes
import os
import re
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core.files import File
from django.db import IntegrityError, transaction
from django.utils import timezone

from .ingestion import ExtractedSection, build_chunks, embed_texts, index_source_document
from .models import KnowledgeChunk, KnowledgeSourceDocument, KnowledgeWebSource

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = 'ChaliKnowledgeCrawler/1.0 (+company-approved-knowledge-refresh)'

# Maximum size for a single crawled PDF (25 MB).  Larger files are skipped to
# avoid unexpected storage and processing costs.
PDF_CRAWL_MAX_BYTES = getattr(settings, 'KNOWLEDGE_PDF_CRAWL_MAX_BYTES', 25 * 1024 * 1024)

# Maximum number of PDFs ingested per web-source crawl run.
PDF_CRAWL_MAX_PER_SOURCE = getattr(settings, 'KNOWLEDGE_PDF_CRAWL_MAX_PER_SOURCE', 10)

# HTML-only extensions that should never be fetched as documents.
SKIP_EXTENSIONS = {
    '.jpg',
    '.jpeg',
    '.png',
    '.gif',
    '.webp',
    '.svg',
    '.zip',
    '.rar',
    '.mp4',
    '.mp3',
    '.css',
    '.js',
    '.ico',
}

# Extensions that identify a URL as a fetchable document (not an HTML page).
PDF_EXTENSIONS = {'.pdf'}
DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.pptx', '.txt'}
NOISE_SELECTORS = (
    'script',
    'style',
    'noscript',
    'iframe',
    'nav',
    'header',
    'footer',
    '.menu',
    '.navigation',
    '.breadcrumb',
    '.social',
    '.cookie',
    '.cookie-banner',
    '#cookie-notice',
)


@dataclass
class FetchedPage:
    url: str
    title: str
    text: str
    headings: list[str]
    links: list[str]
    status_code: int
    content_type: str


def normalize_url(url: str, base_url: str = '') -> str:
    if not url:
        return ''
    joined = urljoin(base_url or url, url)
    joined, _fragment = urldefrag(joined)
    parsed = urlparse(joined)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        return ''
    path = parsed.path or '/'
    if path != '/' and path.endswith('/'):
        path = path.rstrip('/')
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, '', parsed.query, ''))


def same_domain(url: str, base_url: str) -> bool:
    return urlparse(url).netloc.lower() == urlparse(base_url).netloc.lower()


def should_skip_url(url: str) -> bool:
    """Return True for non-text binary URLs that should never be fetched as HTML pages."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


def is_pdf_url(url: str) -> bool:
    """Heuristic: URL path ends with .pdf or another known document extension."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in PDF_EXTENSIONS)


def hash_text(text: str) -> str:
    normalized = re.sub(r'\s+', ' ', text or '').strip().lower()
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


class WebSourceCrawler:
    def __init__(self, source: KnowledgeWebSource):
        self.source = source
        self.start_url = normalize_url(source.url)
        self.timeout = getattr(settings, 'KNOWLEDGE_WEB_TIMEOUT_SECONDS', 20)
        self.request_delay = getattr(settings, 'KNOWLEDGE_WEB_REQUEST_DELAY_SECONDS', 0.5)
        self.user_agent = getattr(settings, 'KNOWLEDGE_WEB_USER_AGENT', DEFAULT_USER_AGENT)
        self.max_pages = min(source.max_pages or 1, getattr(settings, 'KNOWLEDGE_WEB_MAX_PAGES_CAP', 50))
        self.max_depth = min(source.crawl_depth or 0, getattr(settings, 'KNOWLEDGE_WEB_MAX_DEPTH_CAP', 2))
        if source.crawl_mode == KnowledgeWebSource.CrawlMode.SINGLE_PAGE:
            self.max_pages = 1
            self.max_depth = 0
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': self.user_agent})
        self.robot_parser = self._load_robots()

    def crawl(self) -> tuple[list[FetchedPage], list[str]]:
        """Crawl the web source.

        Returns:
            (html_pages, pdf_urls) — html_pages is the list of fetched text pages,
            pdf_urls is the ordered, deduplicated list of PDF links discovered during
            the crawl.  PDFs are NOT fetched here; they are ingested separately by
            ``index_web_source``.
        """
        if not self.start_url:
            raise ValueError('Knowledge web source URL is invalid.')

        frontier = deque([(self.start_url, 0)])
        visited = set()
        pdf_urls: list[str] = []
        seen_pdfs: set[str] = set()
        pages = []

        while frontier and len(pages) < self.max_pages:
            url, depth = frontier.popleft()
            url = normalize_url(url, self.start_url)
            if not url or url in visited:
                continue
            visited.add(url)

            if not self._can_fetch(url):
                logger.info('Robots.txt disallowed crawl for %s', url)
                continue

            # PDF links: collect for later ingestion, do not parse as HTML.
            if is_pdf_url(url) and same_domain(url, self.start_url):
                if url not in seen_pdfs and len(pdf_urls) < PDF_CRAWL_MAX_PER_SOURCE:
                    pdf_urls.append(url)
                    seen_pdfs.add(url)
                continue

            if should_skip_url(url) or not same_domain(url, self.start_url):
                continue
            if depth > self.max_depth:
                continue

            page = self._fetch_page(url)
            if page.text:
                pages.append(page)

            if depth >= self.max_depth:
                continue
            for link in page.links:
                next_url = normalize_url(link, url)
                if not next_url or next_url in visited:
                    continue
                if not same_domain(next_url, self.start_url):
                    continue
                if is_pdf_url(next_url):
                    if next_url not in seen_pdfs and len(pdf_urls) < PDF_CRAWL_MAX_PER_SOURCE:
                        pdf_urls.append(next_url)
                        seen_pdfs.add(next_url)
                elif not should_skip_url(next_url):
                    frontier.append((next_url, depth + 1))

        return pages, pdf_urls

    def fetch_pdf_bytes(self, url: str) -> bytes | None:
        """Download a PDF URL and return its raw bytes, or None if it should be skipped.

        Enforces the configured size limit and validates that the response is
        actually a PDF before returning.
        """
        if not self._can_fetch(url):
            logger.info('Robots.txt disallowed PDF fetch for %s', url)
            return None
        try:
            response = self.session.get(url, timeout=self.timeout, stream=True)
            response.raise_for_status()
        except Exception:
            logger.exception('Failed to fetch PDF: %s', url)
            return None

        content_type = response.headers.get('content-type', '').lower()
        content_length = response.headers.get('content-length')
        if content_length and int(content_length) > PDF_CRAWL_MAX_BYTES:
            logger.info('Skipping oversized PDF (%s bytes): %s', content_length, url)
            return None

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > PDF_CRAWL_MAX_BYTES:
                logger.info('Skipping PDF that exceeds size limit mid-download: %s', url)
                return None
            chunks.append(chunk)

        pdf_bytes = b''.join(chunks)

        # Validate magic bytes — real PDFs start with %PDF
        if not pdf_bytes.startswith(b'%PDF') and 'pdf' not in content_type:
            logger.info('URL does not appear to be a PDF (bad magic/content-type): %s', url)
            return None

        return pdf_bytes

    def _load_robots(self):
        parser = RobotFileParser()
        robots_url = urljoin(self.start_url, '/robots.txt')
        try:
            parser.set_url(robots_url)
            parser.read()
        except Exception:
            logger.info('Could not read robots.txt for %s', self.start_url)
        return parser

    def _can_fetch(self, url: str) -> bool:
        try:
            return self.robot_parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def _fetch_page(self, url: str) -> FetchedPage:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '')
        text = response.text
        return extract_html_page(text, url, response.status_code, content_type)


def extract_html_page(html_text: str, url: str, status_code: int, content_type: str) -> FetchedPage:
    soup = BeautifulSoup(html_text or '', 'lxml')
    for selector in NOISE_SELECTORS:
        for element in soup.select(selector):
            element.decompose()

    title = ''
    if soup.title and soup.title.string:
        title = clean_text(soup.title.string)
    if not title:
        h1 = soup.find('h1')
        title = clean_text(h1.get_text(' ')) if h1 else url

    main = (
        soup.find('main')
        or soup.find('article')
        or soup.find('div', class_=re.compile('content|main|body', re.I))
        or soup.body
        or soup
    )
    headings = [
        clean_text(node.get_text(' '))
        for node in main.find_all(['h1', 'h2', 'h3'])
        if clean_text(node.get_text(' '))
    ]
    parts = []
    for node in main.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'td', 'th'], recursive=True):
        value = clean_text(node.get_text(' '))
        if value and len(value) > 2:
            parts.append(value)
    text = clean_text(' '.join(parts) or main.get_text(' '))
    links = [
        href
        for href in (anchor.get('href') for anchor in soup.find_all('a'))
        if href
    ]
    return FetchedPage(
        url=url,
        title=title,
        text=text,
        headings=headings,
        links=links,
        status_code=status_code,
        content_type=content_type,
    )


def clean_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text or '')
    return text.strip()


def _infer_pdf_title(pdf_url: str, link_text: str = '') -> str:
    """Derive a human-readable title for a crawled PDF.

    Priority: link text → filename stem → URL path tail.
    """
    if link_text and link_text.strip():
        return link_text.strip()[:300]
    stem = Path(urlparse(pdf_url).path).stem
    if stem:
        return re.sub(r'[-_]+', ' ', stem).strip()[:300] or 'Document'
    return pdf_url[:300]


def _ingest_crawled_pdf(
    web_source: KnowledgeWebSource,
    pdf_url: str,
    pdf_bytes: bytes,
    title_hint: str = '',
) -> KnowledgeSourceDocument | None:
    """Persist a crawled PDF as a KnowledgeSourceDocument and index it.

    Deduplication logic:
      - If a record already exists for this (company, origin_url), compare content
        hashes.  Skip if unchanged; update the file and re-index if changed.
      - If no record exists, create a new one with is_shareable=False (review queue).

    Returns the saved KnowledgeSourceDocument, or None if skipped.
    """
    company = web_source.company
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()
    title = _infer_pdf_title(pdf_url, title_hint)
    file_name = Path(urlparse(pdf_url).path).name or 'document.pdf'
    if not file_name.lower().endswith('.pdf'):
        file_name = file_name + '.pdf'

    # --- Check for existing record by origin_url ---
    existing = KnowledgeSourceDocument.objects.filter(
        company=company,
        origin_url=pdf_url,
    ).first()

    if existing:
        if existing.content_hash == content_hash:
            logger.info('PDF unchanged (hash match), skipping re-index: %s', pdf_url)
            return existing
        # Content changed — update file and re-index.
        logger.info('PDF changed, re-indexing: %s', pdf_url)
        source = existing
    else:
        # New PDF found during crawl — create with is_shareable=False (admin must review).
        source = KnowledgeSourceDocument(
            company=company,
            title=title,
            file_type=KnowledgeSourceDocument.FileType.PDF,
            origin_url=pdf_url,
            is_shareable=False,
            is_published=True,
        )

    # Save the file to Django storage using a temp file.
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.pdf')
    try:
        with os.fdopen(tmp_fd, 'wb') as tmp_file:
            tmp_file.write(pdf_bytes)
        with open(tmp_path, 'rb') as f:
            if existing and existing.file:
                # Replace the stored file in-place.
                existing.file.delete(save=False)
            source.file.save(file_name, File(f), save=False)
        source.save()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Index asynchronously-safe: index_source_document is synchronous but short.
    index_source_document(source)
    return source


def ingest_crawled_pdfs(
    web_source: KnowledgeWebSource,
    pdf_urls: list[str],
) -> dict:
    """Download and ingest all PDF URLs collected during a web-source crawl.

    Returns a summary dict with counts.
    """
    crawler = WebSourceCrawler(web_source)
    indexed = 0
    skipped = 0
    failed = 0

    for pdf_url in pdf_urls:
        try:
            pdf_bytes = crawler.fetch_pdf_bytes(pdf_url)
            if pdf_bytes is None:
                skipped += 1
                continue
            result = _ingest_crawled_pdf(web_source, pdf_url, pdf_bytes)
            if result is not None:
                indexed += 1
            else:
                skipped += 1
        except IntegrityError:
            # Race condition: another worker created the same record; safe to skip.
            logger.info('PDF ingestion skipped (integrity error, likely duplicate): %s', pdf_url)
            skipped += 1
        except Exception:
            logger.exception('PDF ingestion failed for: %s', pdf_url)
            failed += 1

    return {'indexed': indexed, 'skipped': skipped, 'failed': failed}


def pages_to_sections(pages: list[FetchedPage]) -> list[ExtractedSection]:
    sections = []
    for page in pages:
        heading = page.title or page.url
        source_line = f'Source URL: {page.url}'
        sections.append(
            ExtractedSection(
                text=f'{source_line}\n{page.text}',
                heading=heading,
            )
        )
    return sections


def index_web_source(source: KnowledgeWebSource) -> KnowledgeWebSource:
    source.status = KnowledgeWebSource.Status.CRAWLING
    source.last_error = ''
    source.save(update_fields=['status', 'last_error', 'updated_at'])

    crawled_at = timezone.now()
    try:
        if not source.is_published:
            with transaction.atomic():
                KnowledgeChunk.objects.filter(web_source=source).delete()
                source.status = KnowledgeWebSource.Status.DISABLED
                source.last_crawled_at = crawled_at
                source.schedule_next_crawl(crawled_at)
                source.save(
                    update_fields=[
                        'status',
                        'last_crawled_at',
                        'next_crawl_at',
                        'updated_at',
                    ]
                )
            return source

        pages, pdf_urls = WebSourceCrawler(source).crawl()

        # ----- HTML pages → knowledge chunks -----
        if pages:
            combined_text = '\n'.join(page.text for page in pages)
            content_hash = hash_text(combined_text)

            if source.content_hash and source.content_hash == content_hash:
                source.status = KnowledgeWebSource.Status.UNCHANGED
                source.last_crawled_at = crawled_at
                source.last_success_at = crawled_at
                source.schedule_next_crawl(crawled_at)
                source.save(
                    update_fields=[
                        'status',
                        'last_crawled_at',
                        'last_success_at',
                        'next_crawl_at',
                        'updated_at',
                    ]
                )
                # Even when HTML is unchanged, still try to ingest any new PDFs.
                if pdf_urls:
                    ingest_crawled_pdfs(source, pdf_urls)
                return source

            sections = pages_to_sections(pages)
            chunks = build_chunks(sections)
            embeddings = embed_texts([chunk['text'] for chunk in chunks])

            with transaction.atomic():
                KnowledgeChunk.objects.filter(web_source=source).delete()
                KnowledgeChunk.objects.bulk_create(
                    [
                        KnowledgeChunk(
                            company=source.company,
                            web_source=source,
                            chunk_index=index,
                            text=chunk['text'],
                            heading=chunk.get('heading', ''),
                            token_count=chunk['token_count'],
                            embedding=embeddings[index] if index < len(embeddings) else [],
                            metadata={
                                'source_title': source.title or pages[0].title,
                                'source_type': 'web',
                                'source_url': source.url,
                                'crawled_urls': [page.url for page in pages],
                                'crawl_mode': source.crawl_mode,
                                'content_is_data_not_instruction': True,
                            },
                        )
                        for index, chunk in enumerate(chunks)
                    ]
                )
                source.title = source.title or pages[0].title
                source.content_hash = content_hash
                source.status = KnowledgeWebSource.Status.INDEXED
                source.last_crawled_at = crawled_at
                source.last_success_at = crawled_at
                source.last_error = ''
                source.schedule_next_crawl(crawled_at)
                source.save(
                    update_fields=[
                        'title',
                        'content_hash',
                        'status',
                        'last_crawled_at',
                        'last_success_at',
                        'last_error',
                        'next_crawl_at',
                        'updated_at',
                    ]
                )
        elif not pdf_urls:
            raise ValueError('No indexable text or PDF documents were found at this URL.')
        else:
            # No HTML text at all, but PDFs were discovered — mark as indexed.
            source.status = KnowledgeWebSource.Status.INDEXED
            source.last_crawled_at = crawled_at
            source.last_success_at = crawled_at
            source.last_error = ''
            source.schedule_next_crawl(crawled_at)
            source.save(
                update_fields=[
                    'status',
                    'last_crawled_at',
                    'last_success_at',
                    'last_error',
                    'next_crawl_at',
                    'updated_at',
                ]
            )

        # ----- PDFs discovered during HTML crawl -----
        if pdf_urls:
            pdf_summary = ingest_crawled_pdfs(source, pdf_urls)
            logger.info(
                'PDF ingestion for web source %s: %s',
                source.pk,
                pdf_summary,
            )

    except Exception as exc:
        logger.exception('Knowledge web source indexing failed: %s', source.pk)
        source.status = KnowledgeWebSource.Status.FAILED
        source.last_error = str(exc)
        source.last_crawled_at = crawled_at
        source.schedule_next_crawl(crawled_at)
        source.save(
            update_fields=[
                'status',
                'last_error',
                'last_crawled_at',
                'next_crawl_at',
                'updated_at',
            ]
        )
    return source


def refresh_due_web_sources(limit: int = 50) -> dict:
    now = timezone.now()
    due_sources = list(
        KnowledgeWebSource.objects.filter(
            is_published=True,
            next_crawl_at__lte=now,
        )
        .exclude(status=KnowledgeWebSource.Status.CRAWLING)
        .select_related('company')
        .order_by('next_crawl_at')[:limit]
    )
    indexed = 0
    failed = 0
    unchanged = 0
    for source in due_sources:
        index_web_source(source)
        source.refresh_from_db(fields=['status'])
        if source.status == KnowledgeWebSource.Status.INDEXED:
            indexed += 1
        elif source.status == KnowledgeWebSource.Status.UNCHANGED:
            unchanged += 1
        elif source.status == KnowledgeWebSource.Status.FAILED:
            failed += 1
    return {
        'processed': len(due_sources),
        'indexed': indexed,
        'unchanged': unchanged,
        'failed': failed,
    }
