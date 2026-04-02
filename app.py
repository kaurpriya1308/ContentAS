import streamlit as st
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import re
from collections import deque, defaultdict
import json

# Page config
st.set_page_config(
    page_title="Website & PDF Link Extractor",
    page_icon="🔗",
    layout="wide"
)

# Initialize session state
if 'crawling' not in st.session_state:
    st.session_state.crawling = False
if 'results' not in st.session_state:
    st.session_state.results = None

# ═══════════════════════════════════════════════════════════════
# EXTERNAL DOMAIN WHITELIST
# Domains allowed even if they don't match the base domain.
# Only news/IR-style pages from these are kept.
# ═══════════════════════════════════════════════════════════════
ALLOWED_EXTERNAL_DOMAINS = {
    # Investor-relations hosting platforms
    "ir.", "investor.", "investors.",
}

# Keywords that justify keeping an external-domain URL (news/IR pages only)
EXTERNAL_KEEP_KEYWORDS = [
    "investor", "press", "media", "news", "release",
    "announcement", "publication", "ir.", "/ir/",
]

# ═══════════════════════════════════════════════════════════════
# SEC / REGULATORY FILING DOMAINS & PATTERNS
# Checked BEFORE category matching so they always become Out-of-Scope
# ═══════════════════════════════════════════════════════════════
SEC_FILING_DOMAINS = [
    "sec.gov",
    "edgar.sec.gov",
    "efts.sec.gov",
]

SEC_FILING_URL_PATTERNS = [
    # path-based patterns (order: most specific first)
    r"/sec-filings?/",          # /sec-filing/ or /sec-filings/
    r"/sec[-_]filings?",        # covers sec-filing, sec_filings etc.
    r"/edgar/",
    r"sec[-_]filing",
    r"secfiling",
    r"/annual-reports?$",       # bare /annual-report page with nothing after
                                # (but NOT /annual-reports/something-else)
]

# Pre-compile SEC patterns
_SEC_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in SEC_FILING_URL_PATTERNS]


def is_sec_filing_url(url: str) -> bool:
    """
    Return True if the URL points to a SEC filing page/domain.
    Handles cases like https://ir.seeclearfield.com/sec-filings/annual-reports
    where 'annual-reports' would otherwise match a legitimate category.
    """
    url_lower = url.lower()
    parsed = urlparse(url_lower)
    domain = parsed.netloc.replace("www.", "")

    # 1. Domain is SEC/EDGAR itself
    if any(sec_domain in domain for sec_domain in SEC_FILING_DOMAINS):
        return True

    # 2. URL path contains SEC filing patterns
    full_path = parsed.path
    for pattern in _SEC_PATTERNS_COMPILED:
        if pattern.search(full_path):
            return True

    # 3. Explicit keyword in full URL (catches query-string variants)
    if "sec-filing" in url_lower or "sec_filing" in url_lower or "secfiling" in url_lower:
        return True

    return False


# ═══════════════════════════════════════════════════════════════
# PARENT-URL DEDUPLICATION HELPERS
# ═══════════════════════════════════════════════════════════════

def get_url_depth(url: str) -> int:
    """Return the number of path segments in a URL."""
    path = urlparse(url).path.strip("/")
    if not path:
        return 0
    return len(path.split("/"))


def deduplicate_to_parents(urls: list) -> list:
    """
    Given a list of URLs, remove child URLs whose parent is also present.

    Example:
        /solutions                           ← kept
        /solutions/some-sub-page            ← removed  (parent present)
        /solutions/sub/sub-sub              ← removed  (grandparent present)
        /products/overview                  ← kept     (no parent in list)

    Strategy:
      1. Build a set of all URL path prefixes present in the list.
      2. For each URL, check if any *shorter* prefix (same scheme+host) exists
         in the set.  If yes → it's a child → drop it.
    """
    if not urls:
        return urls

    # Normalise once
    norm_urls = [u.rstrip("/") for u in urls]

    # Build lookup: (scheme, netloc, path) → full url
    parsed_map = {}
    for u in norm_urls:
        p = urlparse(u)
        parsed_map[u] = p

    # Collect all (scheme, netloc, path) tuples
    present_paths = set()
    for u, p in parsed_map.items():
        present_paths.add((p.scheme, p.netloc, p.path.rstrip("/")))

    result = []
    for u in norm_urls:
        p = parsed_map[u]
        path_parts = p.path.strip("/").split("/")
        is_child = False

        # Walk up the path tree
        for depth in range(len(path_parts) - 1, 0, -1):
            parent_path = "/" + "/".join(path_parts[:depth])
            if (p.scheme, p.netloc, parent_path) in present_paths:
                is_child = True
                break

        if not is_child:
            result.append(u)

    return result


# ═══════════════════════════════════════════════════════════════
# CATEGORY DEFINITIONS
# ═══════════════════════════════════════════════════════════════

CATEGORY_KEYWORDS = [

    # ──────────────────────────────────────────
    # 1. PRESENTATIONS
    # ──────────────────────────────────────────
    ("1. Presentations / Investor Day Presentations", [
        "investor-day", "investor_day", "investorday",
        "investor-presentation", "investor_presentation",
        "investorpresentation",
    ]),
    ("1. Presentations / Earnings Presentations", [
        "earnings-presentation", "earnings_presentation",
        "earningspresentation", "earnings-deck", "earnings_deck",
        "earnings-slide", "earnings_slide",
    ]),
    ("1. Presentations / Supplementary Information", [
        "supplementary", "supplemental-info", "supplemental_info",
        "supplemental-data", "supplementary-information",
        "supplemental-information", "supplemental",
    ]),
    ("1. Presentations / Non-GAAP Reconciliation / Non-IFRS Measures", [
        "non-gaap", "non_gaap", "nongaap",
        "non-ifrs", "non_ifrs", "nonifrs",
        "gaap-reconciliation", "gaap_reconciliation",
        "reconciliation",
    ]),
    ("1. Presentations / ESG Presentations / SASB Presentations", [
        "esg-presentation", "esg_presentation",
        "sasb-presentation", "sasb_presentation",
        "esg-slide", "esg_slide",
    ]),
    ("1. Presentations / Letter to Shareholders", [
        "letter-to-shareholder", "letter_to_shareholder",
        "shareholder-letter", "shareholder_letter",
        "shareholderletter", "letter-to-stockholder",
        "letter_to_stockholder",
    ]),
    ("1. Presentations / Roadshow Presentations", [
        "roadshow", "road-show", "road_show",
    ]),
    ("1. Presentations / AGM Presentations", [
        "agm-presentation", "agm_presentation",
        "annual-general-meeting-presentation",
        "agm-slide", "agm_slide",
    ]),

    # ──────────────────────────────────────────
    # 2. PRESS RELEASES / NEWS / ANNOUNCEMENTS
    # ──────────────────────────────────────────
    ("2. Press Releases / News / Announcements", [
        "press-release", "press_release", "pressrelease",
        "news-release", "news_release", "newsrelease",
        "newsroom", "news-room", "news_room",
        "media-center", "media_center", "mediacenter",
        "press-room", "pressroom", "press_room",
        "/news/", "/news.",
        "announcement", "/announcements/",
        "/media/", "media-release", "media_release",
        "company-news", "company_news",
        "latest-news", "latest_news",
    ]),

    # ──────────────────────────────────────────
    # 3. FILINGS
    # ──────────────────────────────────────────
    ("3. Filings / Annual Report & Integrated Report", [
        "annual-report", "annual_report", "annualreport",
        "integrated-report", "integrated_report", "integratedreport",
        "yearly-report", "yearly_report",
    ]),
    ("3. Filings / Interim Report", [
        "interim-report", "interim_report", "interimreport",
        "half-year-report", "half_year_report", "halfyear",
        "half-yearly", "half_yearly",
        "quarterly-report", "quarterly_report", "quarterlyreport",
        "semi-annual", "semi_annual", "semiannual",
        "q1-report", "q2-report", "q3-report", "q4-report",
    ]),
    ("3. Filings / Management Report & MD&A", [
        "management-report", "management_report",
        "management-commentary", "management_commentary",
        "md-a", "md_a", "mda",
        "management-discussion", "management_discussion",
    ]),
    ("3. Filings / Proxies & Information", [
        "proxy", "proxy-statement", "proxy_statement",
        "proxystatement", "information-circular",
        "information_circular",
    ]),
    ("3. Filings / AGM & EGM Notices and Filings", [
        "agm-notice", "agm_notice", "agmnotice",
        "egm-notice", "egm_notice", "egmnotice",
        "agm-filing", "agm_filing",
        "general-meeting-notice", "general_meeting_notice",
        "/agm/", "/egm/",
    ]),
    ("3. Filings / Board Changes, Appointments & Resignations", [
        "board-change", "board_change", "boardchange",
        "appointment", "resignation",
        "director-change", "director_change",
        "board-appointment", "board_appointment",
    ]),
    ("3. Filings / Reorganization & Restructures", [
        "reorgani", "restructur", "reorganization",
        "restructuring", "business-administration",
        "business_administration",
    ]),
    ("3. Filings / Contractual Agreements", [
        "contractual-agreement", "contractual_agreement",
        "contract-agreement", "contract_agreement",
        "material-contract", "material_contract",
    ]),
    ("3. Filings / Cancellations & Changes", [
        "cancellation", "cancel-notice", "cancel_notice",
        "filing-change", "filing_change",
    ]),
    ("3. Filings / Delisting, Suspension & Bankruptcy", [
        "delisting", "suspension", "bankruptcy",
        "delist", "de-list", "de_list",
        "trading-suspension", "trading_suspension",
    ]),
    ("3. Filings / Acquisitions & Disposals", [
        "disposal", "disposals", "divestiture",
        "asset-sale", "asset_sale",
    ]),
    ("3. Filings / Legal Actions", [
        "legal-action", "legal_action", "legalaction",
        "litigation", "lawsuit", "legal-proceeding",
        "legal_proceeding",
    ]),
    ("3. Filings / Material Changes", [
        "material-change", "material_change", "materialchange",
    ]),
    ("3. Filings / Late Filing Notices", [
        "late-filing", "late_filing", "latefiling",
        "late-notice", "late_notice",
    ]),
    ("3. Filings / Regulatory Correspondence & Letters", [
        "regulatory-correspondence", "regulatory_correspondence",
        "regulatory-letter", "regulatory_letter",
        "regulator-letter", "regulator_letter",
    ]),
    ("3. Filings / Exemptions & Other Applications", [
        "exemption", "exemptions",
        "other-application", "other_application",
    ]),
    ("3. Filings / Operating Metrics & Earnings", [
        "operating-metric", "operating_metric", "operatingmetric",
        "profit-loss", "profit_loss", "profitloss",
        "financial-result", "financial_result",
        "operating-result", "operating_result",
    ]),
    ("3. Filings / Fixed Income & Bond Prospectus", [
        "bond-prospectus", "bond_prospectus", "bondprospectus",
        "fixed-income", "fixed_income", "fixedincome",
        "debt-prospectus", "debt_prospectus",
        "green-bond", "green_bond", "greenbond",
        "municipal-bond", "municipal_bond",
        "bond-offering", "bond_offering",
        "bond-issue", "bond_issue",
    ]),
    ("3. Filings / Prospectus - Equity, M&A, IPO", [
        "ipo-prospectus", "ipo_prospectus",
        "equity-prospectus", "equity_prospectus",
        "initial-public-offering", "initial_public_offering",
    ]),
    ("3. Filings / Prospectus - General", [
        "prospectus",
    ]),
    ("3. Filings / Securities Registrations", [
        "securities-registration", "securities_registration",
        "listing-application", "listing_application",
        "listingapplication",
    ]),
    ("3. Filings / Withdrawal & Termination", [
        "withdrawal", "termination",
        "security-withdrawal", "security_withdrawal",
    ]),
    ("3. Filings / Debt Indentures & Credit Agreements", [
        "debt-indenture", "debt_indenture", "debtindenture",
        "credit-agreement", "credit_agreement", "creditagreement",
        "loan-agreement", "loan_agreement",
    ]),
    ("3. Filings / Pre-IPO & Private Offering", [
        "pre-ipo", "pre_ipo", "preipo",
        "private-offering", "private_offering",
        "privately-held", "privately_held",
    ]),
    ("3. Filings / Ownership - Institutional", [
        "institutional-ownership", "institutional_ownership",
        "institutional-holding", "institutional_holding",
    ]),
    ("3. Filings / Ownership - JAPAN5%", [
        "japan5", "japan-5",
    ]),
    ("3. Filings / Ownership - Directors & Officers", [
        "directors-officers", "directors_officers",
        "officer-ownership", "officer_ownership",
        "director-ownership", "director_ownership",
    ]),
    ("3. Filings / Ownership - Beneficial", [
        "beneficial-ownership", "beneficial_ownership",
        "beneficialownership",
    ]),
    ("3. Filings / Shareholding Pattern", [
        "shareholding-pattern", "shareholding_pattern",
        "shareholdingpattern", "share-holding-pattern",
    ]),
    ("3. Filings / Ownership", [
        "ownership", "major-shareholder", "major_shareholder",
    ]),
    ("3. Filings / Capital Changes - Stock Options", [
        "stock-option", "stock_option", "stockoption",
        "employee-stock", "employee_stock",
        "esop", "espp",
    ]),
    ("3. Filings / Capital Changes - Stock Splits", [
        "stock-split", "stock_split", "stocksplit",
        "reverse-split", "reverse_split",
    ]),
    ("3. Filings / Capital Changes - Offers", [
        "tender-offer", "tender_offer", "tenderoffer",
        "exchange-offer", "exchange_offer",
        "rights-offer", "rights_offer", "rightsoffer",
        "rights-issue", "rights_issue",
    ]),
    ("3. Filings / Capital Changes - Repurchase & Buyback", [
        "share-repurchase", "share_repurchase", "sharerepurchase",
        "buyback", "buy-back", "buy_back",
        "securities-purchase", "securities_purchase",
    ]),
    ("3. Filings / Capital Changes - Corporate Actions", [
        "corporate-action", "corporate_action", "corporateaction",
    ]),
    ("3. Filings / M&A, Merger, Takeover", [
        "merger", "takeover", "take-over", "take_over",
        "m-and-a", "m_and_a", "m&a",
    ]),
    ("3. Filings / Dividends", [
        "dividend",
    ]),
    ("3. Filings / Auditors Report & Change in Auditor", [
        "auditor", "audit-report", "audit_report", "auditreport",
        "change-in-auditor", "change_in_auditor",
        "auditor-change", "auditor_change",
    ]),
    ("3. Filings / Change in Year End", [
        "change-in-year-end", "change_in_year_end",
        "fiscal-year-change", "fiscal_year_change",
        "year-end-change", "year_end_change",
    ]),
    ("3. Filings / Fund Sheets", [
        "fund-sheet", "fund_sheet", "fundsheet",
        "fund-report", "fund_report",
        "fund-prospectus", "fund_prospectus",
        "fund-annual", "fund_annual",
        "etf-report", "etf_report",
    ]),

    # ──────────────────────────────────────────
    # 4. ESG
    # ──────────────────────────────────────────
    ("4. ESG / Sustainability Reports", [
        "sustainability-report", "sustainability_report",
        "sustainabilityreport",
    ]),
    ("4. ESG / CSR Reports", [
        "csr-report", "csr_report", "csrreport",
        "corporate-social-responsibility", "corporate_social_responsibility",
        "csr",
    ]),
    ("4. ESG / Integrated Reports (ESG focus)", [
        "esg-integrated", "esg_integrated",
    ]),
    ("4. ESG / EHS Reports", [
        "ehs-report", "ehs_report", "ehsreport",
        "ehs", "environmental-health-safety",
        "environmental_health_safety",
    ]),
    ("4. ESG / Carbon Disclosure Reports", [
        "carbon-disclosure", "carbon_disclosure", "carbondisclosure",
        "cdp-report", "cdp_report",
        "carbon-report", "carbon_report",
    ]),
    ("4. ESG / Green Reports", [
        "green-report", "green_report", "greenreport",
    ]),
    ("4. ESG / TCFD Reports", [
        "tcfd-report", "tcfd_report", "tcfdreport",
        "tcfd",
    ]),
    ("4. ESG / Climate Risk Reports", [
        "climate-risk", "climate_risk", "climaterisk",
        "climate-report", "climate_report",
    ]),
    ("4. ESG / Social Reports", [
        "social-report", "social_report", "socialreport",
        "social-impact", "social_impact",
    ]),
    ("4. ESG / Human Rights Reports", [
        "human-rights", "human_rights", "humanrights",
        "human-rights-report", "human_rights_report",
        "modern-slavery", "modern_slavery",
    ]),
    ("4. ESG / Diversity & Inclusion Reports", [
        "diversity-inclusion", "diversity_inclusion",
        "diversityinclusion", "dei-report", "dei_report",
        "diversity-report", "diversity_report",
        "inclusion-report", "inclusion_report",
    ]),
    ("4. ESG / GRI Reports", [
        "gri-report", "gri_report", "grireport",
        "gri-index", "gri_index",
        "global-reporting-initiative", "global_reporting_initiative",
        "gri",
    ]),
    ("4. ESG / SASB Reports", [
        "sasb-report", "sasb_report", "sasbreport",
        "sasb-index", "sasb_index",
        "sasb",
    ]),
    ("4. ESG / CDP Reports", [
        "cdp",
    ]),
    ("4. ESG / ESTMA Reports", [
        "estma",
    ]),
    ("4. ESG / Company Policies", [
        "company-policy", "company_policy",
        "corporate-policy", "corporate_policy",
        "/policy/", "/policies/",
    ]),
    ("4. ESG / Charters", [
        "charter", "/charters/",
    ]),
    ("4. ESG / Guidelines", [
        "guideline", "/guidelines/",
    ]),
    ("4. ESG / Code of Ethics", [
        "code-of-ethics", "code_of_ethics", "codeofethics",
        "code-of-conduct", "code_of_conduct", "codeofconduct",
        "ethics-code", "ethics_code",
    ]),
    ("4. ESG / Governance Policies", [
        "governance-policy", "governance_policy",
        "corporate-governance", "corporate_governance",
        "governance-document", "governance_document",
        "governance",
    ]),
    ("4. ESG / Sustainability (General)", [
        "sustainability", "sustainable",
    ]),
    ("4. ESG / Topic-Specific ESG Reports", [
        "esg-report", "esg_report", "esgreport",
        "esg",
    ]),

    # ──────────────────────────────────────────
    # 5. SECTOR-SPECIFIC
    # ──────────────────────────────────────────
    ("5. Sector Specific / White Papers", [
        "whitepaper", "white-paper", "white_paper",
    ]),
    ("5. Sector Specific / Case Studies", [
        "case-study", "case_study", "casestudy",
        "case-studies", "case_studies",
    ]),
    ("5. Sector Specific / Industry Insights", [
        "industry-insight", "industry_insight", "industryinsight",
        "industry-trend", "industry_trend",
        "industry-analysis", "industry_analysis",
    ]),
    ("5. Sector Specific / Thought Leadership", [
        "thought-leadership", "thought_leadership", "thoughtleadership",
    ]),
    ("5. Sector Specific / FactSheets & Factbooks", [
        "factsheet", "fact-sheet", "fact_sheet",
        "factbook", "fact-book", "fact_book",
    ]),
    ("5. Sector Specific / Product Brochures", [
        "product-brochure", "product_brochure", "productbrochure",
        "brochure",
    ]),
    ("5. Sector Specific / One Pagers", [
        "one-pager", "one_pager", "onepager",
    ]),
    ("5. Sector Specific / Prepared Remarks", [
        "prepared-remarks", "prepared_remarks", "preparedremarks",
        "prepared-remark", "prepared_remark",
    ]),
    ("5. Sector Specific / Speeches", [
        "speech", "speeches",
    ]),
    ("5. Sector Specific / Executive Commentary", [
        "executive-commentary", "executive_commentary",
        "executivecommentary", "ceo-commentary", "ceo_commentary",
    ]),
    ("5. Sector Specific / Follow-Up Transcripts", [
        "follow-up-transcript", "follow_up_transcript",
        "followup-transcript", "followup_transcript",
        "transcript",
    ]),
    ("5. Sector Specific / Integrated Resource Plans", [
        "integrated-resource-plan", "integrated_resource_plan",
        "resource-plan", "resource_plan",
        "irp",
    ]),
    ("5. Sector Specific / Scientific Posters & Presentations", [
        "scientific-poster", "scientific_poster",
        "poster-presentation", "poster_presentation",
        "research-poster", "research_poster",
    ]),
    ("5. Sector Specific / Research Publications", [
        "research-publication", "research_publication",
        "researchpublication",
    ]),
    ("5. Sector Specific / Blogs & Insights", [
        "blog", "/blogs/", "insights", "/insights/",
        "viewpoints", "perspectives",
    ]),
    ("5. Sector Specific / Leadership Insights & Interviews", [
        "leadership-insight", "leadership_insight",
        "leadership-interview", "leadership_interview",
        "ceo-interview", "ceo_interview",
        "executive-interview", "executive_interview",
    ]),
    ("5. Sector Specific / Customer Stories", [
        "customer-story", "customer_story", "customerstory",
        "customer-stories", "customer_stories",
        "success-story", "success_story",
        "client-story", "client_story",
    ]),

    # ──────────────────────────────────────────
    # 6. COMPANY INFORMATION
    # ──────────────────────────────────────────
    ("6. Company Info / About Us", [
        "about-us", "about_us", "aboutus",
        "who-we-are", "who_we_are",
        "our-company", "our_company",
        "company-overview", "company_overview",
        "/about/", "/about.",
    ]),
    ("6. Company Info / Company History", [
        "company-history", "company_history", "companyhistory",
        "our-history", "our_history", "ourhistory",
        "/history/", "/history.",
    ]),
    ("6. Company Info / Mission & Vision", [
        "mission", "vision",
        "mission-vision", "mission_vision",
        "our-mission", "our_mission",
        "our-vision", "our_vision",
        "purpose", "our-purpose", "our_purpose",
    ]),
    ("6. Company Info / Corporate Information", [
        "corporate-information", "corporate_information",
        "corporate-info", "corporate_info",
    ]),
    ("6. Company Info / Management Profiles", [
        "management-team", "management_team", "managementteam",
        "management-profile", "management_profile",
        "management-committee", "management_committee",
        "management",
    ]),
    ("6. Company Info / Board of Directors", [
        "board-of-director", "board_of_director",
        "boardofdirector", "board-member", "board_member",
        "/board/",
    ]),
    ("6. Company Info / Executive Team", [
        "executive-team", "executive_team", "executiveteam",
        "executive-profile", "executive_profile",
        "c-suite", "c_suite",
    ]),
    ("6. Company Info / Leadership", [
        "leadership", "our-team", "our_team",
        "leadership-team", "leadership_team",
    ]),
    ("6. Company Info / Suppliers", [
        "supplier", "/suppliers/",
        "our-supplier", "our_supplier",
        "vendor-list", "vendor_list",
    ]),
    ("6. Company Info / Partners", [
        "partner", "/partners/",
        "our-partner", "our_partner",
        "global-partner", "global_partner",
        "strategic-alliance", "strategic_alliance",
        "alliance",
    ]),
    ("6. Company Info / Customers", [
        "customer-list", "customer_list",
        "our-customer", "our_customer",
        "/customers/", "client-list", "client_list",
        "who-we-work-with", "who_we_work_with",
    ]),

    # ──────────────────────────────────────────
    # 7. BUSINESS UPDATES
    # ──────────────────────────────────────────
    ("7. Business Updates / Project Updates", [
        "project-update", "project_update", "projectupdate",
        "project-status", "project_status",
    ]),
    ("7. Business Updates / Business Updates", [
        "business-update", "business_update", "businessupdate",
    ]),
    ("7. Business Updates / R&D Updates", [
        "r-and-d", "r_and_d", "r&d",
        "research-and-development", "research_and_development",
        "research-development", "research_development",
        "innovation", "/innovation/",
        "rd-update", "rd_update",
    ]),
    ("7. Business Updates / Activity Reports", [
        "activity-report", "activity_report", "activityreport",
    ]),
    ("7. Business Updates / Infographics", [
        "infographic", "/infographics/",
    ]),
    ("7. Business Updates / Results Announcements", [
        "results-announcement", "results_announcement",
        "result-announcement", "result_announcement",
    ]),
    ("7. Business Updates / Earnings Updates", [
        "earnings-update", "earnings_update",
        "earnings",
    ]),
    ("7. Business Updates / Revenue & Sales Reports", [
        "revenue-report", "revenue_report",
        "sales-report", "sales_report",
        "revenue", "sales-result", "sales_result",
    ]),
    ("7. Business Updates / Financial Highlights", [
        "financial-highlight", "financial_highlight",
        "financial-snapshot", "financial_snapshot",
        "financial-summary", "financial_summary",
    ]),
    ("7. Business Updates / Funding Announcements", [
        "funding-announcement", "funding_announcement",
        "funding", "fundraise", "fund-raise", "fund_raise",
        "capital-raise", "capital_raise",
    ]),

    # ──────────────────────────────────────────
    # 8. PRODUCTS & SERVICES
    # ──────────────────────────────────────────
    ("8. Products & Services / Product Listings", [
        "product-listing", "product_listing", "productlisting",
        "product-catalog", "product_catalog",
        "/products/", "/product/",
    ]),
    ("8. Products & Services / Product Launch Announcements", [
        "product-launch", "product_launch", "productlaunch",
        "new-product", "new_product",
    ]),
    ("8. Products & Services / Product Specifications", [
        "product-spec", "product_spec", "productspec",
        "specification", "/specs/",
    ]),
    ("8. Products & Services / Feature Descriptions", [
        "feature-description", "feature_description",
        "/features/", "/feature/",
    ]),
    ("8. Products & Services / Service Listings", [
        "service-listing", "service_listing",
        "/services/", "/service/",
    ]),
    ("8. Products & Services / Solutions Overview", [
        "solution", "/solutions/",
        "solutions-overview", "solutions_overview",
    ]),
    ("8. Products & Services / Service Model Information", [
        "service-model", "service_model",
        "pricing-model", "pricing_model",
        "offering", "/offerings/",
    ]),

    # ── Catch-all ──
    ("5. Sector Specific / Resources Page", [
        "resources", "/resources/",
    ]),
]


# ═══════════════════════════════════════════════════════════════
# OUT OF SCOPE KEYWORDS
# ═══════════════════════════════════════════════════════════════
OUT_OF_SCOPE_KEYWORDS = [
    "career", "/careers/", "/careers.",
    "job-posting", "job_posting", "jobposting",
    "/jobs/", "/jobs.",
    "faq", "frequently-asked", "frequently_asked",
    "contact-us", "contact_us", "contactus",
    "/contact/", "/contact.",
    "privacy-policy", "privacy_policy", "privacypolicy",
    "terms-of-use", "terms_of_use", "termsofuse",
    "terms-of-service", "terms_of_service",
    "terms-and-conditions", "terms_and_conditions",
    "disclaimer",
    "accessibility-statement", "accessibility_statement",
    "cookie-policy", "cookie_policy",
    "legal-terms", "legal_terms",
    "stock-price", "stock_price", "stockprice",
    "stock-quote", "stock_quote", "stockquote",
    "dividend-history", "dividend_history",
    "clinical-trial", "clinical_trial", "clinicaltrial",
    "/trials/", "/trial/",
    "prescription", "prescribing-information", "prescribing_information",
    "drug-label", "drug_label",
    "safety-sheet", "safety_sheet", "safetysheet",
    "safety-data-sheet", "safety_data_sheet",
    "sds-sheet", "sds_sheet",
    "fda-correspondence", "fda_correspondence",
    "journal-abstract", "journal_abstract",
    # SEC / regulatory filing keywords (belt-and-suspenders)
    "sec-filing", "sec_filing", "secfiling",
    "/sec-filings", "/sec_filings",
    "gartner.com", "forrester.com", "idc.com",
    "amazon.com", "ebay.com",
    "reddit.com", "/forum/", "/forums/",
    "open-chat", "open_chat",
    "recipe",
    "/forms/", "registration-form", "registration_form",
    "supplier-form", "supplier_form",
    "timesofindia.com", "theguardian.com",
    "grandviewresearch.com", "williamblair.com",
    "deloitte.com/publications",
]

# ═══════════════════════════════════════════════════════════════
# KNOWN EXTERNAL JUNK DOMAINS
# URLs from these domains that are NOT news/IR are always dropped.
# Add well-known academic / reference / unrelated domains here.
# ═══════════════════════════════════════════════════════════════
JUNK_EXTERNAL_DOMAINS = {
    "doi.org", "dx.doi.org",
    "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov",
    "iopscience.iop.org",
    "link.springer.com", "springer.com",
    "sciencedirect.com",
    "pubs.acs.org", "pubs.rsc.org",
    "onlinelibrary.wiley.com",
    "nature.com",
    "wikipedia.org", "en.wikipedia.org",
    "scitation.aip.org",
    "opticsinfobase.org",
    "ingentaconnect.com",
    "mdpi.com",
    "jove.com",
    "hal.inria.fr",
    "scripts.iucr.org",
    "nar.oxfordjournals.org",
    "nass.oxfordjournals.org",
    "uvx.edpsciences.org",
    "biophysj.org",
    "medcraveonline.com",
    "readcube.com",
    "rsc.org",
    "intechopen.com",
    "photonics.com",
    "mpserver.pst.qub.ac.uk",
    "ocs.ciemat.es",
}


def _clean_domain(netloc: str) -> str:
    """Strip www. and port from a netloc for comparison."""
    d = netloc.lower().replace("www.", "")
    if ":" in d:
        d = d.split(":")[0]
    return d


def is_same_domain_or_allowed(url: str, base_domain: str) -> bool:
    """
    Return True when the URL should be included in results.

    Rules:
    1. Same domain as the crawl target  → always keep
    2. Known junk external domain       → always drop
    3. External domain with IR/news kw  → keep
    4. Any other external domain        → drop
    """
    parsed = urlparse(url)
    url_domain = _clean_domain(parsed.netloc)
    base_clean = _clean_domain(base_domain)

    # Rule 1 – same domain (including sub-domains of base)
    if url_domain == base_clean or url_domain.endswith("." + base_clean):
        return True

    # Rule 2 – known academic / junk domain
    for junk in JUNK_EXTERNAL_DOMAINS:
        if url_domain == junk or url_domain.endswith("." + junk):
            return False

    # Rule 3 – external but looks like IR / news page
    url_lower = url.lower()
    if any(kw in url_lower for kw in EXTERNAL_KEEP_KEYWORDS):
        return True

    # Rule 4 – unknown external domain → drop
    return False


def categorize_url(url: str) -> str:
    """
    Categorize a URL.

    Priority order:
      1. SEC filing check  → always '⛔ Out of Scope'
      2. Out-of-scope keywords
      3. Category keyword matching
      4. Fallback '❓ Unclassified'
    """
    url_lower = url.lower()

    # 1. SEC / regulatory filing – must come BEFORE category matching
    if is_sec_filing_url(url):
        return "⛔ Out of Scope"

    # 2. Generic out-of-scope keywords
    for kw in OUT_OF_SCOPE_KEYWORDS:
        if kw in url_lower:
            return "⛔ Out of Scope"

    # 3. Category matching
    for category_name, keywords in CATEGORY_KEYWORDS:
        if not keywords:
            continue
        for kw in keywords:
            if kw in url_lower:
                return category_name

    return "❓ Unclassified"


def categorize_all_urls(urls: list) -> dict:
    """Categorize a list of URLs. Returns dict of {category: [urls]}."""
    categorized = defaultdict(list)
    for url in urls:
        cat = categorize_url(url)
        categorized[cat].append(url)
    return dict(categorized)


def normalize_url(url: str) -> str:
    """Normalize URL to avoid duplicates."""
    parsed = urlparse(url)
    path = parsed.path.rstrip('/')
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc.lower(),
        path,
        parsed.params,
        parsed.query,
        ''
    ))
    return normalized


def is_social_media_url(url: str) -> bool:
    """Check if URL is from social media platforms."""
    social_domains = [
        'instagram.com', 'facebook.com', 'linkedin.com', 'youtube.com',
        'twitter.com', 'x.com', 'tiktok.com', 'snapchat.com',
        'pinterest.com', 'reddit.com', 'tumblr.com',
        'whatsapp.com', 'telegram.org',
    ]
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace('www.', '')
    return any(s in domain for s in social_domains)


def is_investor_or_media_page(url: str) -> bool:
    """Check if URL likely contains investor or press release information."""
    keywords = [
        'investor', 'press', 'media', 'news', 'release',
        'announcement', 'publication',
    ]
    url_lower = url.lower()
    return any(kw in url_lower for kw in keywords)


async def extract_json_links(session, url, pdf_regex):
    """Extract links from JSON data on investor/media pages."""
    json_links: set = set()
    json_pdfs: set = set()

    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                return json_links, json_pdfs

            content_type = response.headers.get('Content-Type', '').lower()

            if 'application/json' in content_type:
                try:
                    data = await response.json()
                    extract_urls_from_json(
                        data, url, json_links, json_pdfs, pdf_regex
                    )
                except Exception:
                    pass
            else:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                for script in soup.find_all(
                    'script', type='application/json'
                ):
                    try:
                        if script.string:
                            data = json.loads(script.string)
                            extract_urls_from_json(
                                data, url, json_links, json_pdfs, pdf_regex
                            )
                    except Exception:
                        pass
    except Exception:
        pass

    return json_links, json_pdfs


def extract_urls_from_json(data, base_url, links_set, pdfs_set, pdf_regex):
    """Recursively extract URLs from JSON data."""
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, str) and (
                value.startswith('http') or value.startswith('/')
            ):
                absolute_url = urljoin(base_url, value)
                if absolute_url.startswith('http'):
                    n = normalize_url(absolute_url)
                    links_set.add(n)
                    if pdf_regex.search(n):
                        pdfs_set.add(n)
            elif isinstance(value, (dict, list)):
                extract_urls_from_json(
                    value, base_url, links_set, pdfs_set, pdf_regex
                )
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str) and (
                item.startswith('http') or item.startswith('/')
            ):
                absolute_url = urljoin(base_url, item)
                if absolute_url.startswith('http'):
                    n = normalize_url(absolute_url)
                    links_set.add(n)
                    if pdf_regex.search(n):
                        pdfs_set.add(n)
            elif isinstance(item, (dict, list)):
                extract_urls_from_json(
                    item, base_url, links_set, pdfs_set, pdf_regex
                )


async def crawl_website(
    start_url, pdf_pattern, max_depth, max_concurrent, progress_callback
):
    """Main crawling function."""
    try:
        if not start_url.startswith(('http://', 'https://')):
            start_url = 'https://' + start_url

        start_url = normalize_url(start_url)
        parsed_start = urlparse(start_url)
        base_domain = parsed_start.netloc

        pdf_regex = re.compile(pdf_pattern, re.IGNORECASE)
        excluded_protocols = [
            'javascript:', 'mailto:', 'tel:',
            'sms:', 'fax:', 'data:', '#',
        ]

        visited: set = set()
        all_links: set = set()
        pdf_links: set = set()
        pages_with_pdfs: dict = {}
        json_extracted_links: set = set()

        queue = deque([(start_url, 0)])
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_and_parse(session, url, depth):
            normalized_url = normalize_url(url)

            if normalized_url in visited or depth >= max_depth:
                return []

            visited.add(normalized_url)
            progress_callback(len(visited), len(queue))

            new_urls = []
            page_pdfs = []

            async with semaphore:
                try:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status != 200:
                            return []

                        content_type = response.headers.get(
                            'Content-Type', ''
                        ).lower()
                        if 'text/html' not in content_type:
                            return []

                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        for a_tag in soup.find_all('a', href=True):
                            href = a_tag['href']

                            if any(
                                href.strip().lower().startswith(proto)
                                for proto in excluded_protocols
                            ):
                                continue

                            absolute_url = urljoin(url, href)
                            normalized_abs = normalize_url(absolute_url)

                            if is_social_media_url(normalized_abs):
                                continue

                            parsed = urlparse(normalized_abs)
                            if parsed.scheme not in ['http', 'https']:
                                continue

                            if any(
                                ext in normalized_abs.lower()
                                for ext in [
                                    '.jpg', '.png', '.gif', '.css',
                                    '.js', '.xml', '.ico', '.svg',
                                    '.zip', '.exe',
                                ]
                            ):
                                continue

                            # ── Domain filter ──────────────────────────
                            # Only collect URLs that belong to the same
                            # domain OR are legitimate external IR/news.
                            # This removes academic refs, doi links, etc.
                            if not is_same_domain_or_allowed(
                                normalized_abs, base_domain
                            ):
                                continue
                            # ───────────────────────────────────────────

                            all_links.add(normalized_abs)

                            if pdf_regex.search(normalized_abs):
                                pdf_links.add(normalized_abs)
                                page_pdfs.append(normalized_abs)

                            # Only follow links within the same domain
                            if (
                                parsed.netloc == base_domain
                                and depth + 1 < max_depth
                                and normalized_abs not in visited
                            ):
                                new_urls.append(
                                    (normalized_abs, depth + 1)
                                )

                        if is_investor_or_media_page(normalized_url):
                            json_links, json_pdfs = await extract_json_links(
                                session, url, pdf_regex
                            )
                            json_links = {
                                lnk for lnk in json_links
                                if not is_social_media_url(lnk)
                                and is_same_domain_or_allowed(
                                    lnk, base_domain
                                )
                            }
                            json_pdfs = {
                                lnk for lnk in json_pdfs
                                if not is_social_media_url(lnk)
                                and is_same_domain_or_allowed(
                                    lnk, base_domain
                                )
                            }

                            json_extracted_links.update(json_links)
                            all_links.update(json_links)
                            pdf_links.update(json_pdfs)
                            page_pdfs.extend(list(json_pdfs))

                        if page_pdfs:
                            pages_with_pdfs[normalized_url] = list(
                                set(page_pdfs)
                            )

                except Exception:
                    pass

            return new_urls

        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36'
            )
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            while queue:
                batch_size = min(max_concurrent, len(queue))
                tasks = []

                for _ in range(batch_size):
                    if queue:
                        url_item, depth_val = queue.popleft()
                        tasks.append(
                            fetch_and_parse(session, url_item, depth_val)
                        )

                results_batch = await asyncio.gather(*tasks)

                for new_urls in results_batch:
                    for new_url, new_depth in new_urls:
                        norm = normalize_url(new_url)
                        if norm not in visited:
                            queue.append((norm, new_depth))

        # ── Parent-URL deduplication ────────────────────────────────
        # Remove child URLs when their parent path is also in the list.
        deduped_links = deduplicate_to_parents(sorted(all_links))
        deduped_pdfs  = deduplicate_to_parents(sorted(pdf_links))
        # ───────────────────────────────────────────────────────────

        categorized      = categorize_all_urls(deduped_links)
        categorized_pdfs = categorize_all_urls(deduped_pdfs)

        return {
            'all_links':        deduped_links,
            'pdf_links':        deduped_pdfs,
            'pages_with_pdfs':  pages_with_pdfs,
            'pages_crawled':    len(visited),
            'json_links_count': len(json_extracted_links),
            'categorized_links': categorized,
            'categorized_pdfs':  categorized_pdfs,
        }

    except Exception as e:
        return {'error': str(e)}


# ═══════════════════════════════════════════════════════════════
# Streamlit UI
# ═══════════════════════════════════════════════════════════════
st.title("🔗 Website & PDF Link Extractor")
st.markdown(
    "**Async Deep Crawler with URL Categorization, "
    "Normalization & Social Media Filtering**"
)

with st.sidebar:
    st.header("⚙️ Settings")

    url_input = st.text_input(
        "Website URL", value="https://",
        help="Enter the website URL to crawl"
    )
    depth = st.slider(
        "Crawl Depth", min_value=1, max_value=5, value=2,
        help="How many levels deep to crawl (2 recommended)"
    )
    concurrent = st.slider(
        "Concurrent Requests", min_value=5, max_value=50, value=30,
        help="Higher = faster but more server load"
    )
    pdf_pattern = st.text_input(
        "PDF Regex Pattern",
        value=r"\.pdf$|/pdf/|download.*pdf|\.PDF$",
        help="Regular expression to detect PDF links"
    )

    st.markdown("---")
    st.markdown("### Features")
    st.markdown("""
    ✅ URL Deduplication  
    ✅ **Parent-path Deduplication** *(new)*  
    ✅ Social Media Filter  
    ✅ **External Domain Filter** *(new)*  
    ✅ **SEC Filing Override** *(new)*  
    ✅ JSON Link Extraction  
    ✅ Keyword-based Categorization  
    ✅ Out-of-Scope Detection  
    ✅ Clickable Results  
    """)

    st.markdown("---")
    st.markdown("### 📂 Categories Tracked")
    with st.expander("View all categories"):
        current_section = ""
        for cat_name, _ in CATEGORY_KEYWORDS:
            section = cat_name.split("/")[0].strip()
            if section != current_section:
                st.markdown(f"**{section}**")
                current_section = section
            st.markdown(f"  - {cat_name}")
        st.markdown("- ⛔ Out of Scope")
        st.markdown("- ❓ Unclassified")


def sort_key(cat_name: str):
    if cat_name == "❓ Unclassified":
        return (1, cat_name)
    if cat_name == "⛔ Out of Scope":
        return (2, cat_name)
    return (0, cat_name)


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
                st.error(f"Invalid regex pattern: {str(e)}")
            else:
                st.session_state.crawling = True
                st.session_state.results = None

                progress_bar = st.progress(0)
                status_text = st.empty()

                def update_progress(visited, queue_len):
                    status_text.text(
                        f"Pages crawled: {visited} | Queue: {queue_len}"
                    )

                with st.spinner("Crawling website..."):
                    results = asyncio.run(crawl_website(
                        url_input, pdf_pattern, depth,
                        concurrent, update_progress
                    ))

                st.session_state.results = results
                st.session_state.crawling = False
                progress_bar.progress(100)
                st.success("✅ Crawl complete!")

with col2:
    if st.button("🗑️ Clear Results"):
        st.session_state.results = None
        st.rerun()


# ── Results display ──────────────────────────────────────────
if st.session_state.results:
    results = st.session_state.results

    if 'error' in results:
        st.error(f"Error: {results['error']}")
    else:
        categorized = results.get('categorized_links', {})
        unclassified_count  = len(categorized.get("❓ Unclassified", []))
        out_of_scope_count  = len(categorized.get("⛔ Out of Scope", []))
        classified_count    = (
            len(results['all_links'])
            - unclassified_count
            - out_of_scope_count
        )

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1: st.metric("Pages Crawled",  results['pages_crawled'])
        with c2: st.metric("Total Links",    len(results['all_links']))
        with c3: st.metric("PDF Links",      len(results['pdf_links']))
        with c4: st.metric("Classified",     classified_count)
        with c5: st.metric("Unclassified",   unclassified_count)
        with c6: st.metric("Out of Scope",   out_of_scope_count)

        st.markdown("---")

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📄 All Links",
            "🏷️ Categorized Links",
            "📑 PDF Links",
            "📑 Categorized PDFs",
            "🗂️ Pages with PDFs",
        ])

        with tab1:
            st.subheader(f"All Links Found ({len(results['all_links'])})")
            if results['all_links']:
                for link in results['all_links']:
                    st.markdown(f"[{link}]({link})")
                st.download_button(
                    "📥 Download All Links",
                    "\n".join(results['all_links']),
                    "all_links.txt", "text/plain"
                )
            else:
                st.info("No links found")

        with tab2:
            st.subheader("🏷️ Links Sorted by Category")
            if categorized:
                report_lines = []
                for cat in sorted(categorized.keys(), key=sort_key):
                    urls = categorized[cat]
                    report_lines += [
                        f"\n{'='*80}",
                        f"{cat}  ({len(urls)} URLs)",
                        f"{'='*80}",
                    ]
                    with st.expander(
                        f"📂 {cat} — {len(urls)} URL(s)", expanded=False
                    ):
                        for u in urls:
                            st.markdown(f"- [{u}]({u})")
                            report_lines.append(u)
                st.download_button(
                    "📥 Download Categorized Report",
                    "\n".join(report_lines),
                    "categorized_links.txt", "text/plain",
                    key="dl_cat_links",
                )
            else:
                st.info("No links to categorize")

        with tab3:
            st.subheader(f"PDF Links ({len(results['pdf_links'])})")
            if results['pdf_links']:
                for link in results['pdf_links']:
                    st.markdown(f"[{link}]({link})")
                st.download_button(
                    "📥 Download PDF Links",
                    "\n".join(results['pdf_links']),
                    "pdf_links.txt", "text/plain"
                )
            else:
                st.info("No PDF links found")

        with tab4:
            st.subheader("📑 PDF Links Sorted by Category")
            cat_pdfs = results.get('categorized_pdfs', {})
            if cat_pdfs:
                pdf_lines = []
                for cat in sorted(cat_pdfs.keys(), key=sort_key):
                    urls = cat_pdfs[cat]
                    pdf_lines += [
                        f"\n{'='*80}",
                        f"{cat}  ({len(urls)} PDFs)",
                        f"{'='*80}",
                    ]
                    with st.expander(
                        f"📂 {cat} — {len(urls)} PDF(s)", expanded=False
                    ):
                        for u in urls:
                            st.markdown(f"- [{u}]({u})")
                            pdf_lines.append(u)
                st.download_button(
                    "📥 Download Categorized PDFs",
                    "\n".join(pdf_lines),
                    "categorized_pdfs.txt", "text/plain",
                    key="dl_cat_pdfs",
                )
            else:
                st.info("No PDF links to categorize")

        with tab5:
            st.subheader(
                f"Pages Containing PDFs "
                f"({len(results['pages_with_pdfs'])})"
            )
            if results['pages_with_pdfs']:
                for page_url, pdfs in sorted(
                    results['pages_with_pdfs'].items()
                ):
                    with st.expander(
                        f"📄 {page_url} ({len(pdfs)} PDFs)"
                    ):
                        st.markdown(f"**Page:** [{page_url}]({page_url})")
                        st.markdown(f"**Contains {len(pdfs)} PDF(s):**")
                        for pdf in pdfs:
                            cat = categorize_url(pdf)
                            st.markdown(
                                f"  ↳ [{pdf}]({pdf})  `{cat}`"
                            )
            else:
                st.info("No pages with PDFs found")
