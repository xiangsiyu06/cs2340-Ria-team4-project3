"""Fetch official catalog pages and extract text sections from HTML and PDFs."""

import re
from collections import Counter
from http.client import HTTPException
from io import BytesIO
from time import monotonic
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .preprocessing import Section, split_pdf_columns

CATALOG_HOST = "catalog.gatech.edu"
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 60


class IngestionError(ValueError):
    """A failure that an operator can act on."""


def catalog_url(value):
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.netloc.lower() != CATALOG_HOST
            or len(value) > 2048
        ):
            raise ValueError
    except ValueError:
        raise IngestionError(f"Enter an HTTPS URL on {CATALOG_HOST}.") from None
    return urlunsplit(("https", CATALOG_HOST, url.path or "/", url.query, ""))


class CatalogRedirect(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = catalog_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, destination)


def fetch_html(url):
    request = Request(catalog_url(url), headers={"User-Agent": "DegreeGuide/1.0"})
    deadline = monotonic() + 15
    try:
        with build_opener(CatalogRedirect()).open(request, timeout=8) as response:
            if response.headers.get_content_type() != "text/html":
                raise IngestionError("The catalog URL did not return an HTML page.")
            data = bytearray()
            while True:
                if monotonic() >= deadline:
                    raise IngestionError("The catalog download timed out. Retry in a moment.")
                block = response.read1(64 * 1024)
                if not block:
                    break
                data.extend(block)
                if len(data) > MAX_HTML_BYTES:
                    raise IngestionError("The catalog page exceeds the 2 MiB limit.")
            charset = response.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace")
    except (OSError, HTTPException, LookupError) as exc:
        raise IngestionError("Could not fetch the catalog page. Check the URL and retry.") from exc


def html_sections(html):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else "Catalog page"
    body = soup.select_one("#content, main, [role=main]")
    if body is None:
        raise IngestionError("The catalog page has no recognizable main content.")
    for tag in body.select("nav, script, style, header, footer, aside, #sidebar, #breadcrumb, #tabs"):
        tag.decompose()

    sections = []
    parts = []
    heading = anchor = ""
    for node in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr", "dt", "dd"]):
        if node.find_parent(["p", "li", "tr", "dt", "dd"]) is not None:
            continue
        if node.name in {"h1", "h2", "h3", "h4"}:
            if parts:
                sections.append(Section("\n".join(parts), heading, anchor=anchor))
            heading = node.get_text(" ", strip=True)
            anchor = node.get("id", "")
            parts = []
            continue
        if node.name == "tr":
            text = " | ".join(cell.get_text(" ", strip=True) for cell in node.find_all(["td", "th"], recursive=False))
        else:
            text = " ".join(node.stripped_strings)
        if text:
            parts.append(text)
    if parts:
        sections.append(Section("\n".join(parts), heading, anchor=anchor))
    return title, sections


def pdf_sections(data):
    if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF-"):
        raise IngestionError("Upload a valid PDF no larger than 5 MiB.")
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise IngestionError("Upload an unencrypted PDF.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise IngestionError("Upload a PDF with at most 60 pages.")
        pages = [
            (page.extract_text(extraction_mode="layout", layout_mode_space_vertically=False) or "").strip("\n").splitlines()
            for page in reader.pages
        ]
    except (PyPdfError, OSError, ValueError, OverflowError) as exc:
        if isinstance(exc, IngestionError):
            raise
        raise IngestionError("Could not read this PDF. Try another official copy.") from exc

    def running_label(line, number):
        line = line.strip()
        label = re.sub(rf"^{number}\s+|\s+{number}$", "", line).strip()
        return label if label != line and len(label) > 15 else ""

    running_labels = Counter(
        label
        for number, page in enumerate(pages, 1) if len(page) >= 3
        for label in {running_label(page[0], number), running_label(page[-1], number)}
        if label
    )
    sections = []
    for number, page in enumerate(pages, 1):
        if len(page) >= 3:
            if running_labels[running_label(page[0], number)] >= 2:
                page = page[1:]
            if running_labels[running_label(page[-1], number)] >= 2:
                page = page[:-1]
        for column in split_pdf_columns(page):
            text = "\n".join(re.sub(r" {3,}", " | ", line.strip()) for line in column)
            sections.append(Section(text, page_number=number))
    return sections
