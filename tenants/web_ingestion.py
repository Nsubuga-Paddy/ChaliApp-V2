import hashlib
import logging
import re
from collections import deque
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .ingestion import ExtractedSection, build_chunks, embed_texts
from .models import KnowledgeChunk, KnowledgeWebSource

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = 'ChaliKnowledgeCrawler/1.0 (+company-approved-knowledge-refresh)'
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
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


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

    def crawl(self) -> list[FetchedPage]:
        if not self.start_url:
            raise ValueError('Knowledge web source URL is invalid.')

        frontier = deque([(self.start_url, 0)])
        visited = set()
        pages = []

        while frontier and len(pages) < self.max_pages:
            url, depth = frontier.popleft()
            url = normalize_url(url, self.start_url)
            if not url or url in visited:
                continue
            visited.add(url)
            if should_skip_url(url) or not same_domain(url, self.start_url):
                continue
            if depth > self.max_depth:
                continue
            if not self._can_fetch(url):
                logger.info('Robots.txt disallowed crawl for %s', url)
                continue

            page = self._fetch_page(url)
            if page.text:
                pages.append(page)

            if depth >= self.max_depth:
                continue
            for link in page.links:
                next_url = normalize_url(link, url)
                if (
                    next_url
                    and next_url not in visited
                    and same_domain(next_url, self.start_url)
                    and not should_skip_url(next_url)
                ):
                    frontier.append((next_url, depth + 1))

        return pages

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

        pages = WebSourceCrawler(source).crawl()
        if not pages:
            raise ValueError('No indexable text was found at this URL.')

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
