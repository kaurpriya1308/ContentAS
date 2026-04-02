import streamlit as st
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import re
from collections import deque, defaultdict
import json

# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Website & PDF Link Extractor",
    page_icon="🔗",
    layout="wide"
)

if 'crawling' not in st.session_state:
    st.session_state.crawling = False
if 'results' not in st.session_state:
    st.session_state.results = None

# ═══════════════════════════════════════════════════════════════
# CATEGORY DEFINITIONS
# ═══════════════════════════════════════════════════════════════
CATEGORIES = [
    (
        "⛔ Out of Scope", [
            r"career", r"job", r"faq", r"question",
            r"contact.*us", r"privacy", r"sec.*filing",
            r"term.*of.*use", r"contact", r"cookie",
            r"stock.*price", r"legal.*term", r"term.*condition",
            r"stock.*quote", r"linkedin", r"facebook",
            r"twitter", r"youtube", r"forum", r"chat", r"recipe",
        ]
    ),
    (
        "Presentation", [
            r"investor.*day", r"presentation", r"deck",
            r"slide", r"earnings", r"poster", r"supplemental",
            r"supplementary", r"non.*gaap", r"gaap", r"ifrs",
            r"reconciliation", r"roadshow", r"road.*show",
        ]
    ),
    (
        "Reports", [
            r"letter.*to.*shareholder", r"shareholder.*letter",
            r"letter.*stockholder", r"agm",
            r"annual.*general.*meeting", r"meeting",
            r"extra.*ordinary.*meeting", r"egm",
            r"annual.*report", r"integrated.*report",
            r"yearly.*report", r"interim.*report",
            r"quarterly.*report", r"half.*year.*report",
            r"semi.*annual.*report", r"report",
            r"management.*report", r"management.*commentary",
            r"mda", r"management.*discussion", r"proxy",
            r"proxy.*statement", r"information.*circular",
            r"agm.*notice", r"egm.*notice", r"meeting.*notice",
            r"operating.*metric", r"profit.*loss",
            r"financial.*result", r"operating.*result",
            r"fixed.*income", r"bond", r"debt", r"prospectus",
            r"ipo", r"initial.*public.*offering",
            r"fact.*sheet", r"fact.*book", r"result",
            r"revenue", r"sales", r"profit", r"financial",
            r"snapshot", r"funding", r"fund.*raise",
            r"capital.*raise", r"prescription", r"trial",
        ]
    ),
    (
        "News", [
            r"press.*release", r"news", r"media",
            r"press", r"announcement", r"notices",
        ]
    ),
    (
        "Filings", [
            r"board", r"director", r"reorgani", r"restructur",
            r"agreement", r"material.*contract", r"cancellation",
            r"filing.*change", r"cancel.*notice", r"delisting",
            r"suspension", r"bankruptcy", r"trading.*suspension",
            r"disposal", r"asset.*sale", r"legal.*action",
            r"litigation", r"lawsuit", r"material.*change",
            r"late.*filing", r"regulato.*correspondence",
            r"regulato.*letter", r"exemption",
            r"securities.*registration", r"listing.*application",
            r"withdrawal", r"termination", r"debt.*indenture",
            r"credit.*agreement", r"pre.*ipo",
            r"private.*offering", r"privately.*held",
            r"institutional.*ownership", r"institutional.*holding",
            r"officer.*ownership", r"director.*ownership",
            r"beneficial.*ownership", r"share.*holding.*pattern",
            r"major.*shareholder", r"stock.*option",
            r"employee.*stock", r"esop", r"stock.*split",
            r"reverse.*split", r"tender.*offer",
            r"exchange.*offer", r"rights.*offer", r"rights.*issue",
            r"share.*repurchase", r"buyback",
            r"securities.*purchase", r"corporate.*action",
            r"merger", r"takeover", r"m&a", r"acquisition",
            r"dividend", r"audit", r"fund", r"etf",
            r"prepared.*remark", r"transcript", r"speech",
            r"executive.*commentary", r"ceo.*commentary",
            r"business.*update",
        ]
    ),
    (
        "ESG", [
            r"esg", r"sustainabilit", r"csr",
            r"corporate.*social.*responsibility",
            r"ehs", r"environmental.*health.*safety",
            r"carbon.*disclosure", r"carbon.*report",
            r"cdp.*report", r"green.*report", r"tcfd",
            r"climate", r"social", r"human.*rights",
            r"modern.*slavery", r"diversity", r"dei.*report",
            r"inclusion.*report", r"gri.*report",
            r"global.*reporting.*initiative", r"sasb.*report",
            r"sasb.*index", r"cdp", r"estma", r"policy",
            r"policies", r"charter", r"guideline", r"ethics",
            r"code.*of.*conduct", r"governance", r"sustainable",
        ]
    ),
    (
        "Sector Specific", [
            r"white.*paper", r"case.*stud", r"industry",
            r"insight", r"thought.*leadership", r"product",
            r"brochure", r"one.*pager",
            r"integrated.*resource.*plan", r"resource",
            r"scientific", r"research.*publication",
            r"research", r"blog", r"customer.*stor",
            r"client.*stor", r"success.*stor", r"project",
            r"r&d", r"r.*and.*d", r"rd.*update",
            r"research.*development", r"activity",
            r"infographic", r"catalog", r"safety.*sheet",
            r"data.*sheet", r"launch", r"specification",
            r"clinical.*trial", r"sds.*sheet", r"feature",
            r"service", r"solution", r"model",
        ]
    ),
    (
        "Company Info", [
            r"interview", r"about.*us", r"about",
            r"who.*we.*are", r"our.*company", r"overview",
            r"company.*history", r"history", r"mission",
            r"purpose", r"corporate.*info", r"management",
            r"profile", r"board.*of.*director", r"board.*member",
            r"executive.*team", r"leadership", r"team",
            r"supplier", r"vendor", r"partner", r"alliance",
            r"customer.*list", r"who.*we.*work.*with",
        ]
    ),
]

COMPILED_CATEGORIES = [
    (label, [re.compile(p, re.IGNORECASE) for p in patterns])
    for label, patterns in CATEGORIES
]

# PDF extension pattern — used to separate HTML pages from PDFs
PDF_EXTENSION_RE = re.compile(
    r"\.pdf($|\?)|/pdf/|download.*pdf", re.IGNORECASE
)

# ═══════════════════════════════════════════════════════════════
# EXTERNAL DOMAIN FILTERS
# ═══════════════════════════════════════════════════════════════
JUNK_EXTERNAL_DOMAINS = {
    "doi.org", "dx.doi.org", "ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov", "iopscience.iop.org",
    "link.springer.com", "springer.com", "sciencedirect.com",
    "pubs.acs.org", "pubs.rsc.org", "onlinelibrary.wiley.com",
    "nature.com", "wikipedia.org", "en.wikipedia.org",
    "scitation.aip.org", "opticsinfobase.org",
    "ingentaconnect.com", "mdpi.com", "jove.com",
    "hal.inria.fr", "scripts.iucr.org",
    "nar.oxfordjournals.org", "nass.oxfordjournals.org",
    "uvx.edpsciences.org", "biophysj.org",
    "medcraveonline.com", "readcube.com", "rsc.org",
    "intechopen.com", "photonics.com",
}

EXTERNAL_KEEP_KEYWORDS = [
    "investor", "press", "media", "news",
    "release", "announcement", "publication", "/ir/",
]

SEC_FILING_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"sec\.gov", r"edgar\.sec\.gov",
        r"/sec[-_]filings?", r"sec[-_]filing",
        r"secfiling", r"/edgar/",
    ]
]


# ═══════════════════════════════════════════════════════════════
# CORE HELPERS
# ═══════════════════════════════════════════════════════════════

def is_pdf_url(url: str) -> bool:
    """Return True if the URL points to a PDF (not an HTML page)."""
    return bool(PDF_EXTENSION_RE.search(url))


def categorize_url(url: str) -> str:
    """First match wins. Out of Scope is always index 0."""
    for label, compiled_patterns in COMPILED_CATEGORIES:
        for pattern in compiled_patterns:
            if pattern.search(url):
                return label
    return "❓ Unclassified"


def categorize_all_urls(urls: list) -> dict:
    result = defaultdict(list)
    for url in urls:
        result[categorize_url(url)].append(url)
    return dict(result)


def normalize_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((
        p.scheme, p.netloc.lower(),
        p.path.rstrip("/"),
        p.params, p.query, ""
    ))


def strip_query(url: str) -> str:
    """Remove query string and fragment, lowercase netloc."""
    p = urlparse(url)
    return urlunparse((
        p.scheme, p.netloc.lower(),
        p.path.rstrip("/"),
        "", "", ""
    ))


def is_social_media_url(url: str) -> bool:
    social = [
        "instagram.com", "facebook.com", "linkedin.com",
        "youtube.com", "twitter.com", "x.com", "tiktok.com",
        "snapchat.com", "pinterest.com", "reddit.com",
        "tumblr.com", "whatsapp.com", "telegram.org",
    ]
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(s in domain for s in social)


def is_sec_filing_url(url: str) -> bool:
    return any(pat.search(url) for pat in SEC_FILING_PATTERNS)


def _clean_domain(netloc: str) -> str:
    return netloc.lower().replace("www.", "").split(":")[0]


def is_same_domain_or_allowed(url: str, base_domain: str) -> bool:
    parsed     = urlparse(url)
    url_dom    = _clean_domain(parsed.netloc)
    base_clean = _clean_domain(base_domain)
    if url_dom == base_clean or url_dom.endswith("." + base_clean):
        return True
    for junk in JUNK_EXTERNAL_DOMAINS:
        if url_dom == junk or url_dom.endswith("." + junk):
            return False
    if any(kw in url.lower() for kw in EXTERNAL_KEEP_KEYWORDS):
        return True
    return False


def is_investor_or_media_page(url: str) -> bool:
    kws = ["investor", "press", "media", "news",
           "release", "announcement", "publication"]
    return any(k in url.lower() for k in kws)


# ═══════════════════════════════════════════════════════════════
# DEDUPLICATION
#
# Step 1 — Strip query strings
#           page?src=A + page?src=B → one entry → page
#
# Step 2 — Parent-path suppression
#           /solutions exists → drop /solutions/pageA
#
# Step 3 — Sibling flood (OPTIONAL, off by default)
#           If > threshold siblings share same parent bucket,
#           keep only first N
# ═══════════════════════════════════════════════════════════════

def deduplicate_urls(
    urls: list,
    enable_sibling_flood: bool = False,
    sibling_threshold: int = 10,
    sibling_keep: int = 3,
) -> list:
    """
    Step 1: Strip query strings → unique paths only.
    Step 2: Parent-path suppression.
    Step 3: Sibling flood control (optional).
    """

    # ── Step 1: strip queries ─────────────────────────────────
    seen:  set  = set()
    clean: list = []
    for url in sorted(urls):          # sort → shorter paths first
        c = strip_query(url)
        if c not in seen:
            seen.add(c)
            clean.append(c)

    # ── Step 2: parent-path suppression ──────────────────────
    path_set:     set  = set()
    parsed_cache: dict = {}
    for u in clean:
        p = urlparse(u)
        parsed_cache[u] = p
        path_set.add((p.scheme, p.netloc, p.path.rstrip("/")))

    after_parent: list = []
    for u in clean:
        p     = parsed_cache[u]
        parts = p.path.strip("/").split("/")
        is_child = False
        for depth in range(len(parts) - 1, 0, -1):
            parent_path = "/" + "/".join(parts[:depth])
            if (p.scheme, p.netloc, parent_path) in path_set:
                is_child = True
                break
        if not is_child:
            after_parent.append(u)

    # ── Step 3: sibling flood (optional) ─────────────────────
    if not enable_sibling_flood:
        after_parent.sort()
        return after_parent

    buckets: dict = defaultdict(list)
    for u in after_parent:
        p      = urlparse(u)
        parts  = p.path.strip("/").split("/")
        parent = "/" + "/".join(parts[:-1]) if len(parts) > 1 else "/"
        buckets[(p.netloc, parent)].append(u)

    result: list = []
    for bucket_urls in buckets.values():
        if len(bucket_urls) > sibling_threshold:
            result.extend(bucket_urls[:sibling_keep])
        else:
            result.extend(bucket_urls)

    result.sort()
    return result


# ═══════════════════════════════════════════════════════════════
# JSON EXTRACTION
# ═══════════════════════════════════════════════════════════════

async def extract_json_links(session, url, pdf_regex):
    json_links: set = set()
    json_pdfs:  set = set()
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                return json_links, json_pdfs
            ct = response.headers.get("Content-Type", "").lower()
            if "application/json" in ct:
                try:
                    data = await response.json()
                    _extract_from_json(
                        data, url, json_links, json_pdfs, pdf_regex
                    )
                except Exception:
                    pass
            else:
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                for script in soup.find_all(
                    "script", type="application/json"
                ):
                    try:
                        if script.string:
                            data = json.loads(script.string)
                            _extract_from_json(
                                data, url, json_links,
                                json_pdfs, pdf_regex
                            )
                    except Exception:
                        pass
    except Exception:
        pass
    return json_links, json_pdfs


def _extract_from_json(data, base_url, links, pdfs, pdf_regex):
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, str) and (
                v.startswith("http") or v.startswith("/")
            ):
                abs_url = normalize_url(urljoin(base_url, v))
                if abs_url.startswith("http"):
                    links.add(abs_url)
                    if pdf_regex.search(abs_url):
                        pdfs.add(abs_url)
            elif isinstance(v, (dict, list)):
                _extract_from_json(v, base_url, links, pdfs, pdf_regex)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str) and (
                item.startswith("http") or item.startswith("/")
            ):
                abs_url = normalize_url(urljoin(base_url, item))
                if abs_url.startswith("http"):
                    links.add(abs_url)
                    if pdf_regex.search(abs_url):
                        pdfs.add(abs_url)
            elif isinstance(item, (dict, list)):
                _extract_from_json(
                    item, base_url, links, pdfs, pdf_regex
                )


# ═══════════════════════════════════════════════════════════════
# MAIN CRAWLER
# ═══════════════════════════════════════════════════════════════

async def crawl_website(
    start_url, pdf_pattern, max_depth,
    max_concurrent, progress_callback,
    enable_sibling_flood, sibling_threshold, sibling_keep,
):
    try:
        if not start_url.startswith(("http://", "https://")):
            start_url = "https://" + start_url

        start_url   = normalize_url(start_url)
        base_domain = urlparse(start_url).netloc
        pdf_regex   = re.compile(pdf_pattern, re.IGNORECASE)

        excluded = [
            "javascript:", "mailto:", "tel:",
            "sms:", "fax:", "data:", "#",
        ]
        skip_exts = {
            ".jpg", ".jpeg", ".png", ".gif", ".css",
            ".js", ".xml", ".ico", ".svg", ".zip", ".exe",
        }

        visited:         set  = set()
        # Separate raw HTML pages from raw PDFs during crawl
        raw_pages:       set  = set()   # HTML pages only
        raw_pdfs:        set  = set()   # PDF links only
        # Map: html_page_url → [pdf_urls found on that page]
        pages_with_pdfs: dict = {}
        json_link_count: int  = 0

        queue     = deque([(start_url, 0)])
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_and_parse(session, url, depth):
            norm = normalize_url(url)
            if norm in visited or depth >= max_depth:
                return []
            visited.add(norm)
            progress_callback(len(visited), len(queue))

            new_urls:  list = []
            page_pdfs: list = []

            async with semaphore:
                try:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status != 200:
                            return []
                        ct = resp.headers.get(
                            "Content-Type", ""
                        ).lower()
                        if "text/html" not in ct:
                            return []

                        html = await resp.text()
                        soup = BeautifulSoup(html, "html.parser")

                        for a in soup.find_all("a", href=True):
                            href = a["href"]
                            if any(
                                href.strip().lower().startswith(ex)
                                for ex in excluded
                            ):
                                continue

                            abs_url = normalize_url(
                                urljoin(url, href)
                            )
                            if is_social_media_url(abs_url):
                                continue
                            if is_sec_filing_url(abs_url):
                                continue

                            parsed = urlparse(abs_url)
                            if parsed.scheme not in ("http", "https"):
                                continue
                            if any(
                                parsed.path.lower().endswith(ext)
                                for ext in skip_exts
                            ):
                                continue
                            if not is_same_domain_or_allowed(
                                abs_url, base_domain
                            ):
                                continue

                            # ── Separate PDFs from HTML pages ──
                            if is_pdf_url(abs_url):
                                raw_pdfs.add(abs_url)
                                page_pdfs.append(abs_url)
                            else:
                                raw_pages.add(abs_url)
                                # Follow only HTML same-domain links
                                if (
                                    parsed.netloc == base_domain
                                    and depth + 1 < max_depth
                                    and abs_url not in visited
                                ):
                                    new_urls.append(
                                        (abs_url, depth + 1)
                                    )

                        # JSON extraction on IR/media pages
                        if is_investor_or_media_page(norm):
                            jlinks, jpdfs = await extract_json_links(
                                session, url, pdf_regex
                            )
                            nonlocal json_link_count
                            json_link_count += len(jlinks)
                            for lnk in jlinks:
                                if (
                                    not is_social_media_url(lnk)
                                    and is_same_domain_or_allowed(
                                        lnk, base_domain
                                    )
                                ):
                                    if is_pdf_url(lnk):
                                        raw_pdfs.add(lnk)
                                        page_pdfs.append(lnk)
                                    else:
                                        raw_pages.add(lnk)
                            for lnk in jpdfs:
                                if (
                                    not is_social_media_url(lnk)
                                    and is_same_domain_or_allowed(
                                        lnk, base_domain
                                    )
                                ):
                                    raw_pdfs.add(lnk)
                                    page_pdfs.append(lnk)

                        # Record which page contained which PDFs
                        if page_pdfs:
                            if norm not in pages_with_pdfs:
                                pages_with_pdfs[norm] = set()
                            pages_with_pdfs[norm].update(page_pdfs)

                except Exception:
                    pass

            return new_urls

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            )
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            while queue:
                batch = min(max_concurrent, len(queue))
                tasks = []
                for _ in range(batch):
                    if queue:
                        u, d = queue.popleft()
                        tasks.append(fetch_and_parse(session, u, d))
                for new_urls in await asyncio.gather(*tasks):
                    for nu, nd in new_urls:
                        if normalize_url(nu) not in visited:
                            queue.append((nu, nd))

        # ── Deduplication on HTML pages only ─────────────────
        # PDFs are NOT deduplicated — we want every PDF found
        deduped_pages = deduplicate_urls(
            sorted(raw_pages),
            enable_sibling_flood=enable_sibling_flood,
            sibling_threshold=sibling_threshold,
            sibling_keep=sibling_keep,
        )
        all_pdfs = sorted(raw_pdfs)   # full list, no dedup

        # ── pages_with_pdfs: convert sets → sorted lists ─────
        pages_with_pdfs_clean = {
            page: sorted(pdfs)
            for page, pdfs in pages_with_pdfs.items()
        }

        # ── Categorize ────────────────────────────────────────
        categorized_pages = categorize_all_urls(deduped_pages)
        categorized_pdfs  = categorize_all_urls(all_pdfs)

        # ── Pages-with-PDFs grouped by page category ─────────
        # Structure:
        # {
        #   "Reports": {
        #       "https://example.com/reports": ["pdf1.pdf", ...]
        #   },
        #   ...
        # }
        pages_pdfs_by_category: dict = defaultdict(dict)
        for page_url, pdfs in pages_with_pdfs_clean.items():
            page_cat = categorize_url(page_url)
            pages_pdfs_by_category[page_cat][page_url] = pdfs

        return {
            # HTML pages (deduplicated)
            "all_pages":               deduped_pages,
            "raw_page_count":          len(raw_pages),
            # PDFs (full, no dedup)
            "all_pdfs":                all_pdfs,
            "raw_pdf_count":           len(raw_pdfs),
            # Categorized
            "categorized_pages":       categorized_pages,
            "categorized_pdfs":        categorized_pdfs,
            "pages_pdfs_by_category":  dict(pages_pdfs_by_category),
            # Meta
            "pages_crawled":           len(visited),
            "json_links_count":        json_link_count,
        }

    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# STREAMLIT UI
# ═══════════════════════════════════════════════════════════════

st.title("🔗 Website & PDF Link Extractor")
st.markdown(
    "**Async Deep Crawler — Regex Categories · "
    "Query-Strip · Parent Suppression · Optional Sibling Flood**"
)

with st.sidebar:
    st.header("⚙️ Settings")

    url_input = st.text_input(
        "Website URL", value="https://",
        help="Enter the website URL to crawl"
    )
    depth = st.slider(
        "Crawl Depth", min_value=1, max_value=5, value=2,
        help="Subpages crawled for PDFs; only parents shown in output"
    )
    concurrent = st.slider(
        "Concurrent Requests", min_value=5, max_value=50, value=30
    )
    pdf_pattern = st.text_input(
        "PDF Regex Pattern",
        value=r"\.pdf($|\?)|/pdf/|download.*pdf",
    )

    st.markdown("---")
    st.markdown("### 🔁 Deduplication Controls")

    enable_sibling_flood = st.toggle(
        "Enable Sibling Flood Control",
        value=False,
        help=(
            "When ON: if too many sibling URLs share the same "
            "parent path, collapse them to N representatives. "
            "OFF by default — turn on only if results are too noisy."
        )
    )

    sibling_threshold = st.slider(
        "Sibling Flood Threshold",
        min_value=3, max_value=50, value=10,
        disabled=not enable_sibling_flood,
        help="Collapse siblings when count exceeds this number."
    )
    sibling_keep = st.slider(
        "Keep N Siblings After Flood",
        min_value=1, max_value=10, value=3,
        disabled=not enable_sibling_flood,
        help="How many siblings to keep after collapsing."
    )

    st.markdown("---")
    st.markdown("### 📂 Categories")
    for label, patterns in CATEGORIES:
        with st.expander(label):
            for p in patterns:
                st.code(p)

    st.markdown("---")
    st.markdown("### Features")
    st.markdown("""
    ✅ HTML pages & PDFs tracked separately  
    ✅ Query-string deduplication  
    ✅ Parent-path suppression  
    ✅ Sibling flood *(optional toggle)*  
    ✅ External domain filtering  
    ✅ SEC filing override  
    ✅ Regex-based categorization  
    ✅ Social media filter  
    ✅ JSON link extraction  
    """)


def sort_key(cat: str) -> int:
    order = {
        "Presentation": 0, "Reports": 1, "News": 2,
        "Filings": 3, "ESG": 4, "Sector Specific": 5,
        "Company Info": 6, "❓ Unclassified": 8,
        "⛔ Out of Scope": 9,
    }
    return order.get(cat, 7)


# ── Main buttons ──────────────────────────────────────────────
col1, col2 = st.columns([3, 1])

with col1:
    if st.button(
        "🚀 Start Crawling", type="primary",
        disabled=st.session_state.crawling
    ):
        if not url_input or url_input == "https://":
            st.error("Please enter a valid URL")
        else:
            try:
                re.compile(pdf_pattern)
            except re.error as e:
                st.error(f"Invalid regex: {e}")
            else:
                st.session_state.crawling = True
                st.session_state.results  = None

                progress_bar = st.progress(0)
                status_text  = st.empty()

                def update_progress(vis, q_len):
                    status_text.text(
                        f"Pages crawled: {vis} | Queue: {q_len}"
                    )

                with st.spinner("Crawling…"):
                    res = asyncio.run(crawl_website(
                        url_input, pdf_pattern,
                        depth, concurrent,
                        update_progress,
                        enable_sibling_flood,
                        sibling_threshold,
                        sibling_keep,
                    ))

                st.session_state.results  = res
                st.session_state.crawling = False
                progress_bar.progress(100)
                st.success("✅ Crawl complete!")

with col2:
    if st.button("🗑️ Clear Results"):
        st.session_state.results = None
        st.rerun()


# ═══════════════════════════════════════════════════════════════
# RESULTS DISPLAY
# ═══════════════════════════════════════════════════════════════
if st.session_state.results:
    res = st.session_state.results

    if "error" in res:
        st.error(f"Error: {res['error']}")
    else:
        cat_pages    = res.get("categorized_pages", {})
        n_unclass    = len(cat_pages.get("❓ Unclassified", []))
        n_oos        = len(cat_pages.get("⛔ Out of Scope", []))
        n_classified = len(res["all_pages"]) - n_unclass - n_oos

        # ── Metrics ───────────────────────────────────────────
        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        c1.metric("Pages Crawled",  res["pages_crawled"])
        c2.metric("Raw Pages",      res["raw_page_count"])
        c3.metric("Deduped Pages",  len(res["all_pages"]))
        c4.metric("Total PDFs",     len(res["all_pdfs"]))
        c5.metric("Classified",     n_classified)
        c6.metric("Unclassified",   n_unclass)
        c7.metric("Out of Scope",   n_oos)

        raw   = res["raw_page_count"]
        dedup = len(res["all_pages"])
        if raw > 0:
            pct = round((raw - dedup) / raw * 100, 1)
            st.info(
                f"🔁 Deduplication: {raw} raw pages → "
                f"{dedup} unique ({pct}% reduction)"
            )

        st.markdown("---")

        # ── 4 Tabs ────────────────────────────────────────────
        tab1, tab2, tab3, tab4 = st.tabs([
            "📄 All Pages",
            "🏷️ Categorized Pages",
            "📑 Categorized PDFs",
            "🗂️ Pages with PDFs",
        ])

        # ── Tab 1: All HTML pages (flat list, no PDFs) ────────
        with tab1:
            st.subheader(
                f"All Pages — HTML only ({len(res['all_pages'])})"
            )
            st.caption(
                "Deduplicated HTML pages only. "
                "PDFs are in the Categorized PDFs tab."
            )
            for lnk in res["all_pages"]:
                st.markdown(f"[{lnk}]({lnk})")
            if res["all_pages"]:
                st.download_button(
                    "📥 Download All Pages",
                    "\n".join(res["all_pages"]),
                    "all_pages.txt", "text/plain",
                )

        # ── Tab 2: Categorized HTML pages ─────────────────────
        with tab2:
            st.subheader("🏷️ Pages by Category")
            st.caption("HTML pages only, grouped by category.")
            lines = []
            for label in sorted(cat_pages.keys(), key=sort_key):
                urls = cat_pages[label]
                lines += [
                    f"\n{'='*60}",
                    f"{label}  ({len(urls)} pages)",
                    f"{'='*60}",
                ]
                with st.expander(
                    f"📂 {label} — {len(urls)} page(s)",
                    expanded=False
                ):
                    for u in urls:
                        st.markdown(f"- [{u}]({u})")
                        lines.append(u)
            st.download_button(
                "📥 Download Categorized Pages",
                "\n".join(lines),
                "categorized_pages.txt", "text/plain",
                key="dl_cat_pages",
            )

        # ── Tab 3: Categorized PDFs ───────────────────────────
        with tab3:
            st.subheader("📑 PDFs by Category")
            st.caption(
                f"All {len(res['all_pdfs'])} PDFs found "
                "during crawl, grouped by category."
            )
            cat_pdfs  = res.get("categorized_pdfs", {})
            pdf_lines = []
            for label in sorted(cat_pdfs.keys(), key=sort_key):
                urls = cat_pdfs[label]
                pdf_lines += [
                    f"\n{'='*60}",
                    f"{label}  ({len(urls)} PDFs)",
                    f"{'='*60}",
                ]
                with st.expander(
                    f"📂 {label} — {len(urls)} PDF(s)",
                    expanded=False
                ):
                    for u in urls:
                        st.markdown(f"- [{u}]({u})")
                        pdf_lines.append(u)
            if pdf_lines:
                st.download_button(
                    "📥 Download Categorized PDFs",
                    "\n".join(pdf_lines),
                    "categorized_pdfs.txt", "text/plain",
                    key="dl_cat_pdf",
                )

        # ── Tab 4: Pages with PDFs grouped by page category ───
        with tab4:
            ppbc = res.get("pages_pdfs_by_category", {})
            total_pages_with_pdf = sum(
                len(pages) for pages in ppbc.values()
            )
            st.subheader(
                f"🗂️ Pages with PDFs — by Category "
                f"({total_pages_with_pdf} pages)"
            )
            st.caption(
                "Each HTML page that contains PDFs, "
                "grouped by the page's category."
            )

            if ppbc:
                report_lines = []
                for cat_label in sorted(ppbc.keys(), key=sort_key):
                    pages_dict = ppbc[cat_label]
                    total_pdfs_in_cat = sum(
                        len(v) for v in pages_dict.values()
                    )
                    report_lines += [
                        f"\n{'='*60}",
                        f"{cat_label}  "
                        f"({len(pages_dict)} pages, "
                        f"{total_pdfs_in_cat} PDFs)",
                        f"{'='*60}",
                    ]
                    with st.expander(
                        f"📂 {cat_label} — "
                        f"{len(pages_dict)} page(s), "
                        f"{total_pdfs_in_cat} PDF(s)",
                        expanded=False,
                    ):
                        for page_url, pdfs in sorted(
                            pages_dict.items()
                        ):
                            st.markdown(
                                f"**🔗 [{page_url}]({page_url})**"
                            )
                            for pdf in pdfs:
                                pdf_cat = categorize_url(pdf)
                                st.markdown(
                                    f"&nbsp;&nbsp;&nbsp;↳ "
                                    f"[{pdf}]({pdf})  "
                                    f"`{pdf_cat}`"
                                )
                                report_lines.append(
                                    f"  PAGE: {page_url}"
                                )
                                report_lines.append(
                                    f"    PDF [{pdf_cat}]: {pdf}"
                                )
                            st.markdown("---")

                st.download_button(
                    "📥 Download Pages with PDFs",
                    "\n".join(report_lines),
                    "pages_with_pdfs.txt", "text/plain",
                    key="dl_pages_pdfs",
                )
            else:
                st.info("No pages with PDFs found.")
