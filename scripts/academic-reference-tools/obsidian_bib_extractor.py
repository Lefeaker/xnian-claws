#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError as UrlHTTPError
from urllib.error import URLError
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    class _FuzzCompat:
        @staticmethod
        def ratio(a: str, b: str) -> float:
            return difflib.SequenceMatcher(None, a, b).ratio() * 100

    fuzz = _FuzzCompat()

try:
    import bibtexparser
    from bibtexparser.bibdatabase import BibDatabase
except Exception:  # pragma: no cover
    bibtexparser = None
    BibDatabase = None


DEFAULT_EXCLUDES = [".obsidian", ".git", "node_modules", "attachments", "Templates"]
DOI_REGEX = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", re.IGNORECASE)
DOI_URL_REGEX = re.compile(r"https?://(?:dx\.)?doi\.org/([^\s)\]}>\"']+)", re.IGNORECASE)
ARXIV_TEXT_REGEX = re.compile(
    r"\barXiv:\s*([a-z\-]+(?:\.[A-Za-z\-]+)?/\d{7}(?:v\d+)?|\d{4}\.\d{4,5}(?:v\d+)?)\b",
    re.IGNORECASE,
)
ARXIV_URL_REGEX = re.compile(r"https?://arxiv\.org/(?:abs|pdf)/([^\s)\]}>\"']+)", re.IGNORECASE)
PMID_URL_REGEX = re.compile(r"https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d{4,10})/?", re.IGNORECASE)
PMID_TEXT_REGEX = re.compile(r"\bPMID\s*:\s*(\d{4,10})\b", re.IGNORECASE)
MD_LINK_URL_REGEX = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)", re.IGNORECASE)
ANGLE_URL_REGEX = re.compile(r"<\s*(https?://[^>\s]+)\s*>", re.IGNORECASE)
BARE_URL_REGEX = re.compile(r"(?<!\()\bhttps?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
TRAILING_PUNCT = ",.;:!?)]}>'\""
TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "from",
    "source",
    "share",
    "spm",
}
RESOURCE_SUFFIXES = {"pdf", "epdf", "fulltext", "download", "viewer", "supplementary-material"}
AIP_JOURNAL_HINTS = {
    "jap": "journal of applied physics",
    "apl": "applied physics letters",
    "apm": "apl materials",
    "jva": "journal of vacuum science technology a",
    "jvb": "journal of vacuum science technology b",
    "aed": "aip advances",
    "npe": "nanophotonics and energy",
    "jla": "journal of laser applications",
}

DEFAULT_STRATEGY_CONFIG: dict[str, Any] = {
    "resolver_order": [
        "optica_uri",
        "pmc_idconv",
        "sciencedirect_pii",
        "semanticscholar_api",
        "aip_path",
        "mdpi_path",
        "researchgate_title",
        "generic_title",
        "page_title",
    ],
    "resolver_enabled": {
        "optica_uri": True,
        "pmc_idconv": True,
        "sciencedirect_pii": True,
        "semanticscholar_api": True,
        "aip_path": True,
        "mdpi_path": True,
        "researchgate_title": True,
        "generic_title": True,
        "page_title": True,
    },
    "thresholds": {
        "crossref_title_min_score": 72,
        "title_guess_min_chars": 22,
        "researchgate_min_chars": 24,
        "researchgate_min_alpha_tokens": 4,
        "scholarly_slug_min_words": 6,
    },
    "heuristics": {
        "scholarly_signals": [
            "article",
            "paper",
            "abstract",
            "fulltext",
            "publication",
            "journal",
            "doi",
            "pii",
            "pmc",
            "pmid",
            "arxiv",
            "science",
            "research",
        ],
        "blocked_extensions": [
            "jpg",
            "jpeg",
            "png",
            "gif",
            "webp",
            "svg",
            "ico",
            "mp3",
            "mp4",
            "avi",
            "mov",
            "zip",
            "rar",
            "7z",
            "css",
            "js",
            "xml",
            "json",
        ],
        "non_scholarly_hosts": [
            "mmbiz.qpic.cn",
            "mp.weixin.qq.com",
            "api.openai.com",
            "web.chatboxai.app",
            "chatgpt.com",
            "g.co",
            "t0.gstatic.com",
            "t1.gstatic.com",
            "t2.gstatic.com",
            "www.bilibili.com",
            "www.zhipin.com",
            "baike.baidu.com",
            "en.wikipedia.org",
            "github.com",
            "www.linkedin.com",
            "linkedin.com"
        ]
    },
}


def merge_strategy_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            merged[key] = merge_strategy_config(value, {})
        elif isinstance(value, list):
            merged[key] = list(value)
        else:
            merged[key] = value

    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_strategy_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_strategy_config(path_arg: str | None, verbose: bool = False) -> dict[str, Any]:
    config_path = Path(path_arg).expanduser() if path_arg else Path(__file__).with_name("strategy_config.json")
    if not config_path.exists():
        if path_arg:
            raise SystemExit(f"Strategy config not found: {config_path}")
        return merge_strategy_config(DEFAULT_STRATEGY_CONFIG, {})

    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Failed to parse strategy config {config_path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise SystemExit(f"Strategy config must be a JSON object: {config_path}")

    merged = merge_strategy_config(DEFAULT_STRATEGY_CONFIG, loaded)
    if verbose:
        print(f"Loaded strategy config: {config_path}")
    return merged


@dataclass
class SourceRef:
    source_file: str
    source_line: int
    source_context: str


@dataclass
class Candidate:
    id_type: str
    normalized_id: str
    raw_matches: set[str] = field(default_factory=set)
    sources: list[SourceRef] = field(default_factory=list)

    def add_source(self, source: SourceRef, raw_match: str) -> None:
        self.raw_matches.add(raw_match)
        if not any(
            s.source_file == source.source_file and s.source_line == source.source_line
            for s in self.sources
        ):
            self.sources.append(source)


@dataclass
class FetchResult:
    success: bool
    canonical_key: str
    bib_entry: dict[str, Any] | None = None
    bibtex_raw: str | None = None
    error: str | None = None


class _SimpleResponse:
    def __init__(self, status_code: int, text: str, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        return json.loads(self.text)


class _SimpleClient:
    def __init__(self, timeout: float, follow_redirects: bool = True):
        self.timeout = timeout
        self.follow_redirects = follow_redirects

    def request(self, method: str, url: str, **kwargs: Any) -> _SimpleResponse:
        params = kwargs.get("params")
        headers = kwargs.get("headers") or {}
        if params:
            query = urlencode(params)
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query}"
        req = Request(url=url, method=method.upper(), headers=headers)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                return _SimpleResponse(resp.status, body, dict(resp.headers.items()))
        except UrlHTTPError as err:
            body = err.read().decode("utf-8", errors="ignore") if err.fp else ""
            return _SimpleResponse(err.code, body, dict(err.headers.items()) if err.headers else {})
        except URLError as err:
            raise RuntimeError(str(err)) from err

    def close(self) -> None:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract references from Obsidian markdown and build a deduplicated BibTeX file."
    )
    parser.add_argument("--input", required=True, help="Input directory to scan recursively")
    parser.add_argument("--output", default="references.bib", help="Output .bib path")
    parser.add_argument("--report", default="extraction_report.json", help="Output report path")
    parser.add_argument("--cache", default="cache.sqlite", help="Cache path (.sqlite or .json)")
    parser.add_argument("--dry-run", action="store_true", help="Extract only, no network requests")
    parser.add_argument("--verbose", action="store_true", help="Verbose logs")
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Additional directory name to exclude (can repeat)",
    )
    parser.add_argument(
        "--keep-arxiv-version",
        action="store_true",
        help="Keep arXiv version suffix like v2 (default strips it)",
    )
    parser.add_argument(
        "--timeout", type=float, default=15.0, help="HTTP timeout seconds (default: 15)"
    )
    parser.add_argument("--max-retries", type=int, default=4, help="Max retry attempts for 429/5xx")
    parser.add_argument(
        "--trust-env-proxy",
        action="store_true",
        help="Use HTTP proxy settings from environment/system (default: disabled for stability)",
    )
    parser.add_argument(
        "--skip-url-fetch",
        action="store_true",
        help="Skip network fetch for plain URL candidates (DOI/arXiv/PMID still fetched)",
    )
    parser.add_argument(
        "--strategy-config",
        default=None,
        help="Path to strategy JSON config (default: strategy_config.json next to script)",
    )
    parser.add_argument(
        "--user-agent",
        default="obsidian-bib-extractor/1.0",
        help="HTTP User-Agent header used for metadata requests",
    )
    return parser.parse_args()


def log(verbose: bool, message: str) -> None:
    if verbose:
        print(message)


def normalize_doi(raw: str) -> str | None:
    def strip_doi_noise(candidate: str) -> str:
        doi_text = candidate.strip().rstrip(TRAILING_PUNCT)
        doi_text = doi_text.split("?", 1)[0].split("#", 1)[0]
        while True:
            previous = doi_text
            doi_text = re.sub(r"(?i)(\.pdf|\.html?)$", "", doi_text)
            doi_text = re.sub(r"(?i)\.(full|short)$", "", doi_text)
            doi_text = re.sub(r"(?i)/(full|fulltext|epub|epdf|pdf|abstract)$", "", doi_text)
            doi_text = doi_text.rstrip(TRAILING_PUNCT)
            if doi_text == previous:
                break

        parts = doi_text.split("/")
        if (
            len(parts) > 2
            and re.fullmatch(r"\d+\.\d+[a-z0-9.\-]*", parts[1], re.IGNORECASE)
            and re.fullmatch(r"\d{4,}[a-z0-9._\-]*", parts[2], re.IGNORECASE)
        ):
            doi_text = "/".join(parts[:2])
        return doi_text

    text = unquote(raw.strip())
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip("<>()[]{} ")
    text = text.rstrip(TRAILING_PUNCT)
    text = text.replace("\u200b", "")
    text = text.lower()
    matches = [match.group(0) for match in DOI_REGEX.finditer(text)]
    cleaned_candidates: list[str] = []
    for match_text in matches:
        cleaned = strip_doi_noise(match_text).lower()
        if DOI_REGEX.fullmatch(cleaned):
            cleaned_candidates.append(cleaned)
    if cleaned_candidates:
        return min(cleaned_candidates, key=len)
    return None


def normalize_arxiv(raw: str, keep_version: bool = False) -> str | None:
    text = unquote(raw.strip())
    text = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\.pdf$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^arxiv:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip("<>()[]{} ").rstrip(TRAILING_PUNCT)
    if not keep_version:
        text = re.sub(r"v\d+$", "", text, flags=re.IGNORECASE)
    text = text.lower()
    if re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", text):
        return text if keep_version else re.sub(r"v\d+$", "", text)
    if re.fullmatch(r"[a-z\-]+(?:\.[a-z\-]+)?/\d{7}(?:v\d+)?", text):
        return text if keep_version else re.sub(r"v\d+$", "", text)
    return None


def normalize_pmid(raw: str) -> str | None:
    text = raw.strip()
    match = re.search(r"(\d{4,10})", text)
    return match.group(1) if match else None


def normalize_url(raw: str) -> str | None:
    text = raw.strip().strip("<>").rstrip(TRAILING_PUNCT)
    try:
        parts = urlsplit(text)
    except Exception:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = re.sub(r"//+", "/", parts.path or "/")
    query = parts.query
    return urlunsplit((scheme, netloc, path, query, ""))


def build_url_retry_candidates(raw_url: str) -> list[str]:
    base = normalize_url(raw_url)
    if not base:
        return []

    candidates: list[str] = []

    def add(url: str) -> None:
        if url and url not in candidates:
            candidates.append(url)

    add(base)
    try:
        sp = urlsplit(base)
    except Exception:
        return candidates

    query_items = parse_qsl(sp.query, keep_blank_values=True)
    cleaned_query = [(k, v) for k, v in query_items if k.lower() not in TRACKING_QUERY_KEYS]
    if cleaned_query != query_items:
        add(urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(cleaned_query), "")))
    if sp.query:
        add(urlunsplit((sp.scheme, sp.netloc, sp.path, "", "")))

    path = sp.path or "/"
    path_no_ext = re.sub(r"\.(pdf|docx?|xlsx?|pptx?)$", "", path, flags=re.IGNORECASE)
    if path_no_ext != path:
        add(urlunsplit((sp.scheme, sp.netloc, path_no_ext, urlencode(cleaned_query), "")))
        add(urlunsplit((sp.scheme, sp.netloc, path_no_ext, "", "")))

    trimmed_path = path_no_ext.rstrip("/")
    for suffix in RESOURCE_SUFFIXES:
        if trimmed_path.lower().endswith(f"/{suffix}"):
            trimmed_path = re.sub(rf"/{suffix}$", "", trimmed_path, flags=re.IGNORECASE)
    if trimmed_path and trimmed_path != path_no_ext:
        add(urlunsplit((sp.scheme, sp.netloc, trimmed_path, urlencode(cleaned_query), "")))
        add(urlunsplit((sp.scheme, sp.netloc, trimmed_path, "", "")))

    article_rewritten = re.sub(r"/article/(pdf|epdf|full|abstract)/", "/article/", trimmed_path, flags=re.IGNORECASE)
    if article_rewritten != trimmed_path:
        add(urlunsplit((sp.scheme, sp.netloc, article_rewritten, urlencode(cleaned_query), "")))
        add(urlunsplit((sp.scheme, sp.netloc, article_rewritten, "", "")))

    # Generic fallback: step up parent paths only for clearly over-specific URLs
    parent_path = article_rewritten or trimmed_path or path_no_ext or path
    segments = [seg for seg in parent_path.split("/") if seg]
    is_over_specific = (
        bool(sp.query)
        or bool(re.search(r"\.(pdf|docx?|xlsx?|pptx?)$", path, flags=re.IGNORECASE))
        or bool(re.search(r"/(download|pdf|epdf|fulltext|viewer|asset|file)/", path, flags=re.IGNORECASE))
        or len(path) >= 70
        or len(segments) >= 5
    )
    if is_over_specific:
        for depth in range(1, min(3, len(segments)) + 1):
            candidate_path = "/" + "/".join(segments[:-depth]) if len(segments) > depth else "/"
            add(urlunsplit((sp.scheme, sp.netloc, candidate_path, urlencode(cleaned_query), "")))
            add(urlunsplit((sp.scheme, sp.netloc, candidate_path, "", "")))

    combined_text = f"{sp.path} {sp.query}"
    embedded_doi = normalize_doi(combined_text)
    if embedded_doi:
        add(f"https://doi.org/{embedded_doi}")

    # Generic structured URI -> DOI template (e.g., journal-vol-issue-page)
    uri_val = dict(parse_qsl(sp.query, keep_blank_values=True)).get("uri", "")
    uri_match = re.fullmatch(r"([a-z]+)-(\d+)-\d+-(\d+)", uri_val, re.IGNORECASE)
    if uri_match:
        journal_code = uri_match.group(1).upper()
        volume = int(uri_match.group(2))
        page = int(uri_match.group(3))
        add(f"https://doi.org/10.1364/{journal_code}.{volume}.{page:06d}")

    path_doi = normalize_doi(sp.path)
    if path_doi:
        add(f"https://doi.org/{path_doi}")

    # Generic article route cleanup
    cleaned = re.sub(r"/pdf$", "", sp.path, flags=re.IGNORECASE)
    cleaned = re.sub(r"/pdfft$", "", cleaned, flags=re.IGNORECASE)
    if cleaned != sp.path:
        add(urlunsplit((sp.scheme, sp.netloc, cleaned, "", "")))

    return candidates


def compute_line_starts(text: str) -> list[int]:
    starts = [0]
    for idx, char in enumerate(text):
        if char == "\n":
            starts.append(idx + 1)
    return starts


def pos_to_line(line_starts: list[int], pos: int) -> int:
    left, right = 0, len(line_starts) - 1
    while left <= right:
        mid = (left + right) // 2
        if line_starts[mid] <= pos:
            left = mid + 1
        else:
            right = mid - 1
    return right + 1


def line_context(text: str, line_no: int) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    idx = max(0, min(len(lines) - 1, line_no - 1))
    return lines[idx].strip()


def should_skip(path: Path, input_dir: Path, excluded_dirs: set[str]) -> bool:
    rel = path.relative_to(input_dir)
    return any(part in excluded_dirs for part in rel.parts)


def scan_markdown_files(input_dir: Path, excluded_dirs: set[str]) -> list[Path]:
    return sorted(
        [
            path
            for path in input_dir.rglob("*.md")
            if path.is_file() and not should_skip(path, input_dir, excluded_dirs)
        ]
    )


def add_candidate(
    candidates: dict[str, Candidate],
    id_type: str,
    normalized_id: str,
    raw_match: str,
    source: SourceRef,
) -> None:
    key = f"{id_type}:{normalized_id}"
    if key not in candidates:
        candidates[key] = Candidate(id_type=id_type, normalized_id=normalized_id)
    candidates[key].add_source(source, raw_match)


def extract_candidates_from_file(
    path: Path, input_dir: Path, keep_arxiv_version: bool
) -> dict[str, Candidate]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    line_starts = compute_line_starts(text)
    rel_path = str(path.relative_to(input_dir))
    candidates: dict[str, Candidate] = {}

    def source_from_pos(pos: int) -> SourceRef:
        line = pos_to_line(line_starts, pos)
        return SourceRef(source_file=rel_path, source_line=line, source_context=line_context(text, line))

    for match in DOI_URL_REGEX.finditer(text):
        normalized = normalize_doi(match.group(1))
        if normalized:
            add_candidate(candidates, "doi", normalized, match.group(0), source_from_pos(match.start()))

    for match in DOI_REGEX.finditer(text):
        normalized = normalize_doi(match.group(0))
        if normalized:
            add_candidate(candidates, "doi", normalized, match.group(0), source_from_pos(match.start()))

    for match in ARXIV_TEXT_REGEX.finditer(text):
        normalized = normalize_arxiv(match.group(1), keep_arxiv_version)
        if normalized:
            add_candidate(candidates, "arxiv", normalized, match.group(0), source_from_pos(match.start()))

    for match in ARXIV_URL_REGEX.finditer(text):
        normalized = normalize_arxiv(match.group(1), keep_arxiv_version)
        if normalized:
            add_candidate(candidates, "arxiv", normalized, match.group(0), source_from_pos(match.start()))

    for match in PMID_TEXT_REGEX.finditer(text):
        normalized = normalize_pmid(match.group(1))
        if normalized:
            add_candidate(candidates, "pmid", normalized, match.group(0), source_from_pos(match.start()))

    for match in PMID_URL_REGEX.finditer(text):
        normalized = normalize_pmid(match.group(1))
        if normalized:
            add_candidate(candidates, "pmid", normalized, match.group(0), source_from_pos(match.start()))

    url_matches: list[tuple[str, int]] = []
    for regex in (MD_LINK_URL_REGEX, ANGLE_URL_REGEX, BARE_URL_REGEX):
        for match in regex.finditer(text):
            raw_url = match.group(1) if match.lastindex else match.group(0)
            url_matches.append((raw_url, match.start()))

    for raw_url, start in url_matches:
        normalized_url = normalize_url(raw_url)
        if not normalized_url:
            continue
        if DOI_URL_REGEX.search(normalized_url) or ARXIV_URL_REGEX.search(normalized_url) or PMID_URL_REGEX.search(
            normalized_url
        ):
            continue
        add_candidate(candidates, "url", normalized_url, raw_url, source_from_pos(start))

    return candidates


class CacheBackend:
    def get(self, key: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def set(self, key: str, value: dict[str, Any]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


class SQLiteCache(CacheBackend):
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL)"
        )
        self.conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        self.conn.execute(
            "INSERT OR REPLACE INTO cache(key, value, updated_at) VALUES(?, ?, ?)",
            (key, payload, int(time.time())),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class JsonCache(CacheBackend):
    def __init__(self, path: Path):
        self.path = path
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        self.data[key] = value
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_cache(path: Path) -> CacheBackend:
    if path.suffix.lower() == ".json":
        return JsonCache(path)
    return SQLiteCache(path)


class MetadataFetcher:
    def __init__(
        self,
        cache: CacheBackend,
        dry_run: bool,
        verbose: bool,
        timeout: float,
        max_retries: int,
        skip_url_fetch: bool = False,
        trust_env_proxy: bool = False,
        strategy_config: dict[str, Any] | None = None,
        user_agent: str = "obsidian-bib-extractor/1.0",
    ):
        self.cache = cache
        self.dry_run = dry_run
        self.verbose = verbose
        self.max_retries = max_retries
        self.skip_url_fetch = skip_url_fetch
        self.strategy_config = merge_strategy_config(DEFAULT_STRATEGY_CONFIG, strategy_config or {})
        self.user_agent = (user_agent or "").strip() or "obsidian-bib-extractor/1.0"
        if httpx:
            self.client = httpx.Client(timeout=timeout, follow_redirects=True, trust_env=trust_env_proxy)
            self._http_error = httpx.HTTPError
        else:
            self.client = _SimpleClient(timeout=timeout, follow_redirects=True)
            self._http_error = RuntimeError

    def close(self) -> None:
        self.client.close()

    def _response_text(self, response: Any) -> str:
        try:
            return response.text
        except Exception:
            content = getattr(response, "content", b"")
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="ignore")
            return str(content)

    def _config_value(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.strategy_config
        for key in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(key)
            if node is None:
                return default
        return node

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("User-Agent", self.user_agent)
        headers.setdefault("Accept-Language", "en-US,en;q=0.9")
        kwargs["headers"] = headers

        backoff = 1.0
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.request(method, url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == self.max_retries:
                        return response
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return response
            except self._http_error as err:
                last_error = err
                if attempt == self.max_retries:
                    raise
                time.sleep(backoff)
                backoff *= 2
        if last_error:
            raise last_error
        raise RuntimeError("Request failed without explicit error")

    def _extract_researchgate_title_guess(self, url: str) -> str | None:
        try:
            sp = urlsplit(url)
        except Exception:
            return None
        path = unquote(sp.path or "")
        path = path.strip("/")
        if not path:
            return None
        parts = [segment for segment in path.split("/") if segment]
        best = ""
        for segment in parts:
            cleaned = segment
            cleaned = re.sub(r"^\d+_", "", cleaned)
            cleaned = re.sub(r"[-_]", " ", cleaned)
            cleaned = re.sub(
                r"\b(fig(?:ure)?\d*|tbl\d*|table\d*|links?|fulltext|publication|journal|profile|download|viewer|index|issue|volume)\b",
                " ",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if len(cleaned) > len(best):
                best = cleaned
        alpha_tokens = re.findall(r"[A-Za-z]{3,}", best)
        min_chars = int(self._config_value("thresholds", "researchgate_min_chars", default=24))
        min_alpha_tokens = int(self._config_value("thresholds", "researchgate_min_alpha_tokens", default=4))
        return best if len(best) >= min_chars and len(alpha_tokens) >= min_alpha_tokens else None

    def _search_crossref_doi_by_title(self, title_guess: str) -> str | None:
        query = re.sub(r"\s+", " ", title_guess).strip()
        if not query:
            return None
        try:
            resp = self._request(
                "GET",
                "https://api.crossref.org/works",
                params={"query.title": query, "rows": 8},
                headers={"Accept": "application/json"},
            )
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            payload = resp.json()
            items = payload.get("message", {}).get("items", [])
        except Exception:
            return None

        best_doi = None
        best_score = 0.0
        query_lower = query.lower()
        for item in items:
            titles = item.get("title") or []
            candidate_title = str(titles[0]).strip() if titles else ""
            if not candidate_title:
                continue
            score = fuzz.ratio(query_lower, candidate_title.lower())
            doi = normalize_doi(str(item.get("DOI", "")))
            if doi and score > best_score:
                best_score = score
                best_doi = doi
        min_score = float(self._config_value("thresholds", "crossref_title_min_score", default=72))
        if best_doi and best_score >= min_score:
            return best_doi
        return None

    def _resolve_researchgate_doi(self, url: str) -> str | None:
        if not self._is_probable_scholarly_url(url):
            return None
        title_guess = self._extract_researchgate_title_guess(url)
        if not title_guess:
            return None
        return self._search_crossref_doi_by_title(title_guess)

    def _extract_generic_title_guess(self, url: str) -> str | None:
        try:
            sp = urlsplit(url)
        except Exception:
            return None
        path = unquote(sp.path or "").strip("/")
        if not path:
            return None
        best = ""
        stop_words = {
            "article",
            "articles",
            "publication",
            "publications",
            "journal",
            "journals",
            "science",
            "fulltext",
            "download",
            "viewer",
            "pdf",
            "paper",
            "papers",
            "file",
            "files",
            "doi",
            "pii",
        }
        for segment in path.split("/"):
            cleaned = re.sub(r"^\d+_", "", segment)
            cleaned = re.sub(r"[-_]", " ", cleaned)
            cleaned = re.sub(r"[^A-Za-z0-9 ]", " ", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if not cleaned:
                continue
            tokens = [token for token in cleaned.split() if token.lower() not in stop_words and len(token) > 2]
            candidate = " ".join(tokens)
            if len(candidate) > len(best):
                best = candidate
        min_chars = int(self._config_value("thresholds", "title_guess_min_chars", default=22))
        return best if len(best) >= min_chars else None

    def _search_crossref_doi_by_bibliographic(self, query: str) -> str | None:
        query = re.sub(r"\s+", " ", query).strip()
        if len(query) < 4:
            return None
        try:
            resp = self._request(
                "GET",
                "https://api.crossref.org/works",
                params={"query.bibliographic": query, "rows": 6},
                headers={"Accept": "application/json"},
            )
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            items = resp.json().get("message", {}).get("items", [])
        except Exception:
            return None
        for item in items:
            doi = normalize_doi(str(item.get("DOI", "")))
            if doi:
                return doi
        return None

    def _resolve_pmc_doi(self, url: str) -> str | None:
        try:
            sp = urlsplit(url)
        except Exception:
            return None
        pmcid_match = re.search(r"PMC(\d+)", sp.path, flags=re.IGNORECASE)
        pmid_match = re.search(r"/(\d{5,10})/?$", sp.path)
        identifier = None
        if pmcid_match:
            identifier = f"PMC{pmcid_match.group(1)}"
        elif pmid_match:
            identifier = pmid_match.group(1)
        if not identifier:
            return None
        try:
            resp = self._request(
                "GET",
                "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                params={"format": "json", "ids": identifier},
                headers={"Accept": "application/json"},
            )
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            records = resp.json().get("records", [])
        except Exception:
            return None
        for record in records:
            doi = normalize_doi(str(record.get("doi", "")))
            if doi:
                return doi
        return None

    def _resolve_sciencedirect_doi(self, url: str) -> str | None:
        try:
            sp = urlsplit(url)
        except Exception:
            return None
        pii_match = re.search(r"/pii/([A-Z0-9]{10,30})", sp.path, flags=re.IGNORECASE)
        if pii_match:
            pii = pii_match.group(1).upper()
            # 1) Crossref alternative-id is usually the best path for PII
            try:
                alt_resp = self._request(
                    "GET",
                    "https://api.crossref.org/works",
                    params={"filter": f"alternative-id:{pii}", "rows": 6},
                    headers={"Accept": "application/json"},
                )
            except Exception:
                alt_resp = None
            if alt_resp and alt_resp.status_code == 200:
                try:
                    items = alt_resp.json().get("message", {}).get("items", [])
                except Exception:
                    items = []
                for item in items:
                    doi = normalize_doi(str(item.get("DOI", "")))
                    if doi:
                        return doi

            # 2) Bibliographic fallback with PII token
            doi = self._search_crossref_doi_by_bibliographic(pii)
            if doi:
                return doi

            # 3) Elsevier article page often exposes citation_doi in metadata
            landing_url = f"{sp.scheme}://{sp.netloc}/science/article/pii/{pii}"
            try:
                page_resp = self._request("GET", landing_url, headers={"Accept": "text/html,*/*"})
            except Exception:
                page_resp = None
            if page_resp and page_resp.status_code < 400:
                doi = extract_doi_from_html(self._response_text(page_resp))
                if doi:
                    return doi

        title_guess = self._extract_generic_title_guess(url)
        if title_guess:
            return self._search_crossref_doi_by_title(title_guess)
        return None

    def _resolve_generic_title_doi(self, url: str) -> str | None:
        if not self._is_probable_scholarly_url(url):
            return None
        title_guess = self._extract_generic_title_guess(url)
        if not title_guess:
            return None
        return self._search_crossref_doi_by_title(title_guess)

    def _resolve_aip_doi(self, url: str) -> str | None:
        try:
            sp = urlsplit(url)
        except Exception:
            return None

        parts = [part for part in unquote(sp.path).split("/") if part]
        if not parts:
            return None
        parts_lower = [part.lower() for part in parts]
        if "article" not in parts_lower and not any(token in AIP_JOURNAL_HINTS for token in parts_lower):
            return None

        journal_hint = ""
        for token in parts:
            if token.lower() in AIP_JOURNAL_HINTS:
                journal_hint = AIP_JOURNAL_HINTS[token.lower()]
                break

        title_guess = self._extract_generic_title_guess(url)
        queries: list[str] = []
        if title_guess:
            queries.append(title_guess)
            if journal_hint:
                queries.append(f"{title_guess} {journal_hint}")

        if "article" in parts:
            article_idx = parts.index("article")
            tail = parts[article_idx + 1 :]
            if len(tail) >= 3:
                volume = tail[0]
                issue = tail[1]
                page = tail[2]
                bib_hint = " ".join(filter(None, [journal_hint, volume, issue, page])).strip()
                if bib_hint:
                    queries.append(bib_hint)
                if journal_hint:
                    queries.append(f"{journal_hint} {volume} {page}")

        seen_queries = set()
        for query in queries:
            q = re.sub(r"\s+", " ", query).strip()
            if not q or q.lower() in seen_queries:
                continue
            seen_queries.add(q.lower())
            doi = self._search_crossref_doi_by_bibliographic(q)
            if doi:
                return doi
            doi = self._search_crossref_doi_by_title(q)
            if doi:
                return doi
        return None

    def _resolve_mdpi_doi(self, url: str) -> str | None:
        try:
            sp = urlsplit(url)
        except Exception:
            return None

        path = unquote(sp.path or "").strip("/")
        parts = [part for part in path.split("/") if part]
        queries: list[str] = []

        # Pattern: /ISSN/vol/issue/article
        if len(parts) >= 4 and re.fullmatch(r"\d{4}-\d{4}", parts[0]) and all(p.isdigit() for p in parts[1:4]):
            issn, volume, issue, article = parts[0], parts[1], parts[2], parts[3]
            queries.extend([
                f"{issn} {volume} {issue} {article}",
                f"mdpi {issn} {volume} {issue} {article}",
            ])
        else:
            return None

        title_guess = self._extract_generic_title_guess(url)
        if title_guess:
            queries.append(title_guess)

        seen = set()
        for query in queries:
            q = re.sub(r"\s+", " ", query).strip()
            if not q or q.lower() in seen:
                continue
            seen.add(q.lower())
            doi = self._search_crossref_doi_by_bibliographic(q)
            if doi:
                return doi
            doi = self._search_crossref_doi_by_title(q)
            if doi:
                return doi

        # Page parse fallback
        try:
            resp = self._request("GET", url, headers={"Accept": "text/html,*/*"})
        except Exception:
            return None
        if resp.status_code >= 400:
            return None
        body = self._response_text(resp)
        doi = extract_doi_from_html(body)
        if doi:
            return doi
        title = extract_title_from_html(body)
        if title:
            return self._search_crossref_doi_by_bibliographic(title)
        return None

    def _resolve_optica_doi(self, url: str) -> str | None:
        try:
            sp = urlsplit(url)
        except Exception:
            return None

        qs = parse_qs(sp.query or "")
        uri_values = qs.get("uri", [])
        if not uri_values:
            return None
        uri = uri_values[0].strip().lower()
        # examples: oe-31-2-2049, prj-11-5-787, optica-3-10-1066, ao-57-3-538
        m = re.fullmatch(r"([a-z]+)-(\d+)-\d+-(\d+)", uri)
        if not m:
            return None
        journal = m.group(1).upper()
        volume = int(m.group(2))
        page = int(m.group(3))
        return normalize_doi(f"10.1364/{journal}.{volume}.{page:06d}")

    def _resolve_semanticscholar_doi(self, url: str) -> str | None:
        try:
            sp = urlsplit(url)
        except Exception:
            return None

        paper_id = None
        for segment in reversed([seg for seg in sp.path.split("/") if seg]):
            if re.fullmatch(r"[0-9a-f]{40}", segment, flags=re.IGNORECASE):
                paper_id = segment
                break
        if not paper_id:
            return None

        try:
            resp = self._request(
                "GET",
                f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}",
                params={"fields": "externalIds,title"},
                headers={"Accept": "application/json"},
            )
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            payload = resp.json()
        except Exception:
            return None

        external_ids = payload.get("externalIds") or {}
        doi = normalize_doi(str(external_ids.get("DOI", "")))
        if doi:
            return doi

        title = str(payload.get("title", "")).strip()
        if title:
            return self._search_crossref_doi_by_title(title)
        return None


    def _is_probable_scholarly_url(self, url: str) -> bool:
        try:
            sp = urlsplit(url)
        except Exception:
            return False

        path = unquote(sp.path or "").lower()
        query = (sp.query or "").lower()
        if not path and not query:
            return False

        blocked_extensions = [
            str(x).lower().strip(".")
            for x in self._config_value("heuristics", "blocked_extensions", default=[])
            if str(x).strip()
        ]
        if blocked_extensions:
            ext_pattern = r"\.(" + "|".join(re.escape(ext) for ext in blocked_extensions) + r")$"
            if re.search(ext_pattern, path):
                return False

        combined = f"{path}?{query}"
        signals = [
            str(x).lower()
            for x in self._config_value("heuristics", "scholarly_signals", default=[])
            if str(x).strip()
        ]
        if any(token in combined for token in signals):
            return True

        slug = self._extract_generic_title_guess(url)
        min_words = int(self._config_value("thresholds", "scholarly_slug_min_words", default=6))
        if slug and len(slug.split()) >= min_words:
            return True

        return False

    def _resolve_page_title_doi(self, url: str) -> str | None:
        if not self._is_probable_scholarly_url(url):
            return None
        try:
            resp = self._request("GET", url, headers={"Accept": "text/html,*/*"})
        except Exception:
            return None
        if resp.status_code >= 400:
            return None
        title_guess = extract_title_from_html(self._response_text(resp))
        if not title_guess:
            return None
        doi = self._search_crossref_doi_by_bibliographic(title_guess)
        if doi:
            return doi
        return self._search_crossref_doi_by_title(title_guess)

    def _resolve_url_to_doi(self, url: str) -> str | None:
        resolver_map = {
            "optica_uri": self._resolve_optica_doi,
            "pmc_idconv": self._resolve_pmc_doi,
            "sciencedirect_pii": self._resolve_sciencedirect_doi,
            "semanticscholar_api": self._resolve_semanticscholar_doi,
            "aip_path": self._resolve_aip_doi,
            "mdpi_path": self._resolve_mdpi_doi,
            "researchgate_title": self._resolve_researchgate_doi,
            "generic_title": self._resolve_generic_title_doi,
            "page_title": self._resolve_page_title_doi,
        }
        order = self._config_value("resolver_order", default=list(resolver_map.keys()))
        enabled_map = self._config_value("resolver_enabled", default={})

        for resolver_name in order:
            resolver = resolver_map.get(str(resolver_name))
            if not resolver:
                continue
            if isinstance(enabled_map, dict) and enabled_map.get(str(resolver_name), True) is False:
                continue
            doi = resolver(url)
            if doi:
                return doi
        return None

    def fetch_doi(self, doi: str) -> FetchResult:
        cache_key = f"doi:{doi}"
        cached = self.cache.get(cache_key)
        if cached:
            return FetchResult(**cached)
        if self.dry_run:
            return FetchResult(False, cache_key, error="dry_run")

        headers = {"Accept": "application/x-bibtex; charset=utf-8"}
        urls = [f"https://doi.org/{doi}", f"https://api.crossref.org/works/{doi}/transform/application/x-bibtex"]
        last_error = "network"
        for url in urls:
            try:
                resp = self._request("GET", url, headers=headers)
            except Exception:
                continue
            body_text = self._response_text(resp)
            if resp.status_code == 200 and body_text.strip().startswith("@"):
                entry = parse_bibtex_to_entry(body_text)
                if entry:
                    result = FetchResult(True, cache_key, bib_entry=entry, bibtex_raw=body_text)
                    self.cache.set(cache_key, _serialize_fetch_result(result))
                    return result
                last_error = "parse_error"
            elif resp.status_code in {401, 403}:
                last_error = "paywall"
            else:
                last_error = f"http_{resp.status_code}"
        result = FetchResult(False, cache_key, error=last_error)
        self.cache.set(cache_key, _serialize_fetch_result(result))
        return result

    def fetch_arxiv(self, arxiv_id: str) -> FetchResult:
        cache_key = f"arxiv:{arxiv_id}"
        cached = self.cache.get(cache_key)
        if cached:
            return FetchResult(**cached)
        if self.dry_run:
            return FetchResult(False, cache_key, error="dry_run")

        url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
        try:
            resp = self._request("GET", url)
        except Exception:
            result = FetchResult(False, cache_key, error="network")
            self.cache.set(cache_key, _serialize_fetch_result(result))
            return result
        if resp.status_code != 200:
            result = FetchResult(False, cache_key, error=f"http_{resp.status_code}")
            self.cache.set(cache_key, _serialize_fetch_result(result))
            return result

        meta = parse_arxiv_atom(self._response_text(resp))
        if not meta:
            result = FetchResult(False, cache_key, error="parse_error")
            self.cache.set(cache_key, _serialize_fetch_result(result))
            return result

        doi = normalize_doi(meta.get("doi", "")) if meta.get("doi") else None
        if doi:
            doi_result = self.fetch_doi(doi)
            if doi_result.success:
                self.cache.set(cache_key, _serialize_fetch_result(doi_result))
                return doi_result

        entry = {
            "ENTRYTYPE": "article",
            "title": meta.get("title", ""),
            "author": " and ".join(meta.get("authors", [])),
            "year": meta.get("year", ""),
            "journal": "arXiv preprint",
            "eprint": arxiv_id,
            "archivePrefix": "arXiv",
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        }
        if doi:
            entry["doi"] = doi
        result = FetchResult(True, cache_key, bib_entry=entry)
        self.cache.set(cache_key, _serialize_fetch_result(result))
        return result

    def fetch_pmid(self, pmid: str) -> FetchResult:
        cache_key = f"pmid:{pmid}"
        cached = self.cache.get(cache_key)
        if cached:
            return FetchResult(**cached)
        if self.dry_run:
            return FetchResult(False, cache_key, error="dry_run")

        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        try:
            resp = self._request("GET", url, params={"db": "pubmed", "id": pmid, "retmode": "json"})
        except Exception:
            result = FetchResult(False, cache_key, error="network")
            self.cache.set(cache_key, _serialize_fetch_result(result))
            return result
        if resp.status_code != 200:
            result = FetchResult(False, cache_key, error=f"http_{resp.status_code}")
            self.cache.set(cache_key, _serialize_fetch_result(result))
            return result

        try:
            payload = resp.json()
            doc = payload["result"][pmid]
        except Exception:
            result = FetchResult(False, cache_key, error="parse_error")
            self.cache.set(cache_key, _serialize_fetch_result(result))
            return result

        doi = None
        for aid in doc.get("articleids", []):
            if str(aid.get("idtype", "")).lower() == "doi":
                doi = normalize_doi(str(aid.get("value", "")))
                break
        if doi:
            doi_result = self.fetch_doi(doi)
            if doi_result.success:
                self.cache.set(cache_key, _serialize_fetch_result(doi_result))
                return doi_result

        title = doc.get("title", "")
        pubdate = str(doc.get("pubdate", ""))
        year_match = re.search(r"\b(19|20)\d{2}\b", pubdate)
        year = year_match.group(0) if year_match else ""
        authors = [a.get("name", "") for a in doc.get("authors", []) if a.get("name")]
        entry = {
            "ENTRYTYPE": "article",
            "title": title,
            "author": " and ".join(authors),
            "year": year,
            "journal": doc.get("fulljournalname") or doc.get("source", ""),
            "pmid": pmid,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        }
        if doi:
            entry["doi"] = doi
        result = FetchResult(True, cache_key, bib_entry=entry)
        self.cache.set(cache_key, _serialize_fetch_result(result))
        return result

    def _is_non_scholarly_host(self, url: str) -> bool:
        try:
            host = (urlsplit(url).netloc or "").lower()
        except Exception:
            return False
        deny = {
            str(x).lower()
            for x in self._config_value("heuristics", "non_scholarly_hosts", default=[])
            if str(x).strip()
        }
        return host in deny

    def fetch_url(self, url: str) -> FetchResult:
        cache_key = f"url:{url}"
        cached = self.cache.get(cache_key)
        if cached:
            return FetchResult(**cached)
        if self.dry_run:
            return FetchResult(False, cache_key, error="dry_run")

        if self._is_non_scholarly_host(url):
            result = FetchResult(False, cache_key, error="non_scholarly_host_skipped")
            self.cache.set(cache_key, _serialize_fetch_result(result))
            return result

        direct_doi = normalize_doi(url)
        if direct_doi:
            return self.fetch_doi(direct_doi)

        resolved_doi = self._resolve_url_to_doi(url)
        if resolved_doi:
            doi_result = self.fetch_doi(resolved_doi)
            if doi_result.success:
                self.cache.set(cache_key, _serialize_fetch_result(doi_result))
                return doi_result

        if self.skip_url_fetch:
            result = FetchResult(False, cache_key, error="url_fetch_skipped")
            self.cache.set(cache_key, _serialize_fetch_result(result))
            return result
        if url.lower().endswith(".pdf"):
            match = DOI_REGEX.search(url)
            if match:
                doi = normalize_doi(match.group(0))
                if doi:
                    return self.fetch_doi(doi)

        retry_urls = build_url_retry_candidates(url)
        last_error = "no_doi_found"
        saw_no_doi = False
        saw_http_400 = False
        for try_url in retry_urls:
            try:
                resp = self._request("GET", try_url, headers={"Accept": "text/html,*/*"})
            except Exception:
                last_error = "network"
                continue
            if resp.status_code in {401, 403}:
                last_error = "paywall"
                continue
            if resp.status_code >= 400:
                if resp.status_code == 400:
                    saw_http_400 = True
                last_error = f"http_{resp.status_code}"
                continue

            doi = extract_doi_from_html(self._response_text(resp))
            if not doi:
                saw_no_doi = True
                last_error = "no_doi_found"
                continue
            doi_result = self.fetch_doi(doi)
            if doi_result.success:
                self.cache.set(cache_key, _serialize_fetch_result(doi_result))
                return doi_result
            last_error = doi_result.error or "doi_fetch_failed"

        if last_error == "http_400" and saw_no_doi:
            last_error = "no_doi_found"
        elif last_error == "http_400" and not saw_http_400:
            last_error = "no_doi_found"

        result = FetchResult(False, cache_key, error=last_error)
        self.cache.set(cache_key, _serialize_fetch_result(result))
        return result


def _serialize_fetch_result(result: FetchResult) -> dict[str, Any]:
    return {
        "success": result.success,
        "canonical_key": result.canonical_key,
        "bib_entry": result.bib_entry,
        "bibtex_raw": result.bibtex_raw,
        "error": result.error,
    }


def parse_arxiv_atom(xml_text: str) -> dict[str, Any] | None:
    import xml.etree.ElementTree as ET

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    try:
        root = ET.fromstring(xml_text)
        entry = root.find("atom:entry", ns)
        if entry is None:
            return None
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        published = entry.findtext("atom:published", default="", namespaces=ns) or ""
        year = published[:4] if published else ""
        authors = [
            (el.findtext("atom:name", default="", namespaces=ns) or "").strip()
            for el in entry.findall("atom:author", ns)
        ]
        doi = (entry.findtext("arxiv:doi", default="", namespaces=ns) or "").strip()
        return {"title": title, "authors": [a for a in authors if a], "year": year, "doi": doi}
    except Exception:
        return None


def extract_doi_from_html(html: str) -> str | None:
    meta_patterns = [
        re.compile(
            r'<meta[^>]+(?:name|property)="(?:citation_doi|dc\.identifier|dc\.identifier\.doi|prism\.doi)"[^>]+content="([^"]+)"',
            re.IGNORECASE,
        ),
        re.compile(
            r"<meta[^>]+(?:name|property)='(?:citation_doi|dc\.identifier|dc\.identifier\.doi|prism\.doi)'[^>]+content='([^']+)'",
            re.IGNORECASE,
        ),
    ]
    for pattern in meta_patterns:
        match = pattern.search(html)
        if match:
            doi = normalize_doi(match.group(1))
            if doi:
                return doi

    extra_patterns = [
        re.compile(r'"doi"\s*:\s*"(10\.\d{4,9}/[^"\s]+)"', re.IGNORECASE),
        re.compile(r"'doi'\s*:\s*'(10\.\d{4,9}/[^'\s]+)'", re.IGNORECASE),
        re.compile(r"10\.\d{4,9}%2[fF][^\s\"'<>]+", re.IGNORECASE),
        re.compile(r"doi\.org/(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE),
    ]
    for pattern in extra_patterns:
        match = pattern.search(html)
        if match:
            doi = normalize_doi(match.group(0))
            if doi:
                return doi

    match = DOI_REGEX.search(html)
    return normalize_doi(match.group(0)) if match else None


def extract_title_from_html(html: str) -> str | None:
    patterns = [
        re.compile(r'<meta[^>]+name="citation_title"[^>]+content="([^"]+)"', re.IGNORECASE),
        re.compile(r"<meta[^>]+name='citation_title'[^>]+content='([^']+)'", re.IGNORECASE),
        re.compile(r"<meta[^>]+property=\"og:title\"[^>]+content=\"([^\"]+)\"", re.IGNORECASE),
        re.compile(r"<meta[^>]+property='og:title'[^>]+content='([^']+)'", re.IGNORECASE),
        re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL),
    ]
    for pattern in patterns:
        match = pattern.search(html)
        if match:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            if len(title) >= 10:
                return title
    return None


def parse_bibtex_to_entry(raw_bibtex: str) -> dict[str, Any] | None:
    if bibtexparser:
        try:
            parsed = bibtexparser.loads(raw_bibtex)
            if not parsed.entries:
                return None
            entry = dict(parsed.entries[0])
            clean: dict[str, Any] = {}
            for key, value in entry.items():
                if key in {"ID", "ENTRYTYPE"}:
                    clean[key] = str(value)
                    continue
                text = re.sub(r"\s+", " ", str(value)).strip()
                if text:
                    clean[key] = text
            if "ENTRYTYPE" not in clean:
                clean["ENTRYTYPE"] = "article"
            return clean
        except Exception:
            pass

    try:
        head = re.search(r"@([A-Za-z]+)\s*\{\s*([^,]+)", raw_bibtex)
        if not head:
            return None
        entry: dict[str, Any] = {"ENTRYTYPE": head.group(1).lower(), "ID": head.group(2).strip()}
        field_pattern = re.compile(r"([A-Za-z][A-Za-z0-9_\-]*)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"(?:[^\"]|\\.)*\")\s*,?", re.DOTALL)
        for match in field_pattern.finditer(raw_bibtex):
            key = match.group(1)
            value = match.group(2).strip()
            if value.startswith("{") and value.endswith("}"):
                value = value[1:-1]
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            value = re.sub(r"\s+", " ", value).strip()
            if value:
                entry[key] = value
        return entry
    except Exception:
        return None


def first_author_lastname(author_field: str) -> str:
    if not author_field:
        return "unknown"
    first = author_field.split(" and ")[0].strip()
    if "," in first:
        last = first.split(",", 1)[0]
    else:
        last = first.split()[-1]
    return re.sub(r"[^A-Za-z0-9]", "", last).lower() or "unknown"


def short_title_token(title: str) -> str:
    if not title:
        return "untitled"
    text = re.sub(r"[{}]", "", title)
    words = [re.sub(r"[^A-Za-z0-9]", "", w).lower() for w in text.split()]
    words = [w for w in words if w and w not in {"the", "a", "an", "of", "and", "for", "to", "in"}]
    if not words:
        return "untitled"
    return "".join(words[:2])[:18] or "untitled"


def assign_citekey(entry: dict[str, Any], used_keys: set[str], base_keys: set[str]) -> str:
    author = first_author_lastname(str(entry.get("author", "")))
    year_match = re.search(r"\b(19|20)\d{2}\b", str(entry.get("year", "")))
    year = year_match.group(0) if year_match else "nd"
    short = short_title_token(str(entry.get("title", "")))
    base = re.sub(r"[^a-z0-9]", "", f"{author}{year}{short}")
    if not base:
        base = f"{author}{year}paper"

    similar = next((existing for existing in base_keys if fuzz.ratio(base, existing) >= 96), None)
    if similar and similar not in used_keys:
        base = similar

    key = base
    suffix_ord = ord("a")
    while key in used_keys:
        key = f"{base}{chr(suffix_ord)}"
        suffix_ord += 1
    used_keys.add(key)
    base_keys.add(base)
    return key


def render_bibtex_entry(entry: dict[str, Any]) -> str:
    entry = {k: v for k, v in entry.items() if v not in (None, "")}
    entry_type = str(entry.get("ENTRYTYPE", "article"))
    citation_key = str(entry.get("ID", "unnamed"))
    fields_order = [
        "author",
        "title",
        "journal",
        "booktitle",
        "year",
        "volume",
        "number",
        "pages",
        "doi",
        "url",
        "eprint",
        "archivePrefix",
        "pmid",
        "note",
    ]
    lines = [f"@{entry_type}{{{citation_key},"]
    seen = {"ID", "ENTRYTYPE"}
    for field in fields_order + sorted([k for k in entry.keys() if k not in seen and k not in fields_order]):
        if field not in entry:
            continue
        value = re.sub(r"\s+", " ", str(entry[field])).strip()
        if not value:
            continue
        value = value.replace("\\", "\\\\")
        lines.append(f"  {field} = {{{value}}},")
        seen.add(field)
    if len(lines) > 1:
        lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return "\n".join(lines)


def merge_candidates(candidate_sets: Iterable[dict[str, Candidate]]) -> dict[str, Candidate]:
    merged: dict[str, Candidate] = {}
    for group in candidate_sets:
        for key, candidate in group.items():
            if key not in merged:
                merged[key] = Candidate(candidate.id_type, candidate.normalized_id)
            for source in candidate.sources:
                merged[key].add_source(source, next(iter(candidate.raw_matches), candidate.normalized_id))
            merged[key].raw_matches.update(candidate.raw_matches)
    return merged


def priority(candidate: Candidate) -> int:
    ranking = {"doi": 0, "arxiv": 1, "pmid": 2, "url": 3}
    return ranking.get(candidate.id_type, 99)


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    cache_path = Path(args.cache).expanduser().resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"Input directory not found: {input_dir}")

    excluded_dirs = set(DEFAULT_EXCLUDES + list(args.exclude_dir or []))
    md_files = scan_markdown_files(input_dir, excluded_dirs)
    extracted = [extract_candidates_from_file(path, input_dir, args.keep_arxiv_version) for path in md_files]
    candidates = merge_candidates(extracted)

    strategy_config = load_strategy_config(args.strategy_config, verbose=args.verbose)
    cache = make_cache(cache_path)
    fetcher = MetadataFetcher(
        cache=cache,
        dry_run=args.dry_run,
        verbose=args.verbose,
        timeout=args.timeout,
        max_retries=max(1, args.max_retries),
        skip_url_fetch=args.skip_url_fetch,
        trust_env_proxy=args.trust_env_proxy,
        strategy_config=strategy_config,
        user_agent=args.user_agent,
    )

    reports: list[dict[str, Any]] = []
    final_entries: dict[str, dict[str, Any]] = {}
    used_keys: set[str] = set()
    base_keys: set[str] = set()

    try:
        ordered_candidates = sorted(candidates.values(), key=priority)
        total_candidates = len(ordered_candidates)
        for idx, candidate in enumerate(ordered_candidates, start=1):
            if args.verbose and (idx == 1 or idx % 50 == 0 or idx == total_candidates):
                print(f"Progress: {idx}/{total_candidates} ({candidate.id_type}:{candidate.normalized_id})")
            if candidate.id_type == "doi":
                result = fetcher.fetch_doi(candidate.normalized_id)
                dedupe_key = f"doi:{candidate.normalized_id}"
            elif candidate.id_type == "arxiv":
                result = fetcher.fetch_arxiv(candidate.normalized_id)
                dedupe_key = f"arxiv:{candidate.normalized_id}"
            elif candidate.id_type == "pmid":
                result = fetcher.fetch_pmid(candidate.normalized_id)
                dedupe_key = f"pmid:{candidate.normalized_id}"
            else:
                result = fetcher.fetch_url(candidate.normalized_id)
                dedupe_key = f"url:{candidate.normalized_id}"

            canonical_key = result.canonical_key or dedupe_key
            if result.success and result.bib_entry:
                entry = dict(result.bib_entry)
                if "doi" in entry:
                    doi_norm = normalize_doi(str(entry["doi"]))
                    if doi_norm:
                        canonical_key = f"doi:{doi_norm}"
                        entry["doi"] = doi_norm

                if canonical_key not in final_entries:
                    entry["ID"] = assign_citekey(entry, used_keys, base_keys)
                    final_entries[canonical_key] = entry

            first_source = candidate.sources[0] if candidate.sources else SourceRef("", 0, "")
            reports.append(
                {
                    "source_file": first_source.source_file,
                    "source_line": first_source.source_line,
                    "source_context": first_source.source_context,
                    "sources": [source.__dict__ for source in candidate.sources],
                    "raw_match": sorted(candidate.raw_matches)[0] if candidate.raw_matches else candidate.normalized_id,
                    "raw_matches": sorted(candidate.raw_matches),
                    "id_type": candidate.id_type,
                    "normalized_id": candidate.normalized_id,
                    "fetch_status": "success" if result.success and result.bib_entry else "fail",
                    "bibtex_entry": render_bibtex_entry(result.bib_entry)
                    if result.success and result.bib_entry
                    else None,
                    "error": None if result.success and result.bib_entry else (result.error or "unknown"),
                    "canonical_key": canonical_key,
                }
            )
    finally:
        fetcher.close()
        cache.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    bib_entries = [render_bibtex_entry(entry) for entry in final_entries.values()]
    output_path.write_text("\n\n".join(bib_entries) + ("\n" if bib_entries else ""), encoding="utf-8")
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

    success_count = sum(1 for item in reports if item["fetch_status"] == "success")
    fail_count = len(reports) - success_count
    print(
        "Summary: "
        f"scanned_files={len(md_files)}, "
        f"extracted_candidates={sum(len(group) for group in extracted)}, "
        f"deduplicated_candidates={len(candidates)}, "
        f"bibtex_generated={len(final_entries)}, "
        f"success={success_count}, "
        f"failed={fail_count}"
    )
    print(f"BibTeX output: {output_path}")
    print(f"Report output: {report_path}")
    print(f"Cache file: {cache_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
