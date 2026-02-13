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
# CATEGORY DEFINITIONS — aligned to Document Category Table
# Order matters: first match wins. More specific categories
# are listed BEFORE broader/generic ones.
# Each tuple: (display_category, [url_keywords])
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

    # Annual / Integrated Report
    ("3. Filings / Annual Report & Integrated Report", [
        "annual-report", "annual_report", "annualreport",
        "integrated-report", "integrated_report", "integratedreport",
        "yearly-report", "yearly_report",
    ]),
    # Interim Report
    ("3. Filings / Interim Report", [
        "interim-report", "interim_report", "interimreport",
        "half-year-report", "half_year_report", "halfyear",
        "half-yearly", "half_yearly",
        "quarterly-report", "quarterly_report", "quarterlyreport",
        "semi-annual", "semi_annual", "semiannual",
        "q1-report", "q2-report", "q3-report", "q4-report",
    ]),
    # Management Report / MD&A
    ("3. Filings / Management Report & MD&A", [
        "management-report", "management_report",
        "management-commentary", "management_commentary",
        "md-a", "md_a", "mda",
        "management-discussion", "management_discussion",
    ]),
    # Proxies & Information
    ("3. Filings / Proxies & Information", [
        "proxy", "proxy-statement", "proxy_statement",
        "proxystatement", "information-circular",
        "information_circular",
    ]),
    # AGM / EGM Notices
    ("3. Filings / AGM & EGM Notices and Filings", [
        "agm-notice", "agm_notice", "agmnotice",
        "egm-notice", "egm_notice", "egmnotice",
        "agm-filing", "agm_filing",
        "general-meeting-notice", "general_meeting_notice",
        "/agm/", "/egm/",
    ]),
    # Board Changes, Appointments & Resignations
    ("3. Filings / Board Changes, Appointments & Resignations", [
        "board-change", "board_change", "boardchange",
        "appointment", "resignation",
        "director-change", "director_change",
        "board-appointment", "board_appointment",
    ]),
    # Business Administration, Reorganization & Restructures
    ("3. Filings / Reorganization & Restructures", [
        "reorgani", "restructur", "reorganization",
        "restructuring", "business-administration",
        "business_administration",
    ]),
    # Contractual Agreements
    ("3. Filings / Contractual Agreements", [
        "contractual-agreement", "contractual_agreement",
        "contract-agreement", "contract_agreement",
        "material-contract", "material_contract",
    ]),
    # Cancellations & Changes
    ("3. Filings / Cancellations & Changes", [
        "cancellation", "cancel-notice", "cancel_notice",
        "filing-change", "filing_change",
    ]),
    # Delisting, Suspension & Bankruptcy
    ("3. Filings / Delisting, Suspension & Bankruptcy", [
        "delisting", "suspension", "bankruptcy",
        "delist", "de-list", "de_list",
        "trading-suspension", "trading_suspension",
    ]),
    # Other Acquisitions & Disposals
    ("3. Filings / Acquisitions & Disposals", [
        "disposal", "disposals", "divestiture",
        "asset-sale", "asset_sale",
    ]),
    # Legal Actions
    ("3. Filings / Legal Actions", [
        "legal-action", "legal_action", "legalaction",
        "litigation", "lawsuit", "legal-proceeding",
        "legal_proceeding",
    ]),
    # Material Changes
    ("3. Filings / Material Changes", [
        "material-change", "material_change", "materialchange",
    ]),
    # Late Filing Notices
    ("3. Filings / Late Filing Notices", [
        "late-filing", "late_filing", "latefiling",
        "late-notice", "late_notice",
    ]),
    # Regulatory Correspondence
    ("3. Filings / Regulatory Correspondence & Letters", [
        "regulatory-correspondence", "regulatory_correspondence",
        "regulatory-letter", "regulatory_letter",
        "regulator-letter", "regulator_letter",
    ]),
    # Exemptions & Other Applications
    ("3. Filings / Exemptions & Other Applications", [
        "exemption", "exemptions",
        "other-application", "other_application",
    ]),
    # Operating Metrics / Earnings, Profit, Loss
    ("3. Filings / Operating Metrics & Earnings", [
        "operating-metric", "operating_metric", "operatingmetric",
        "profit-loss", "profit_loss", "profitloss",
        "financial-result", "financial_result",
        "operating-result", "operating_result",
    ]),
    # Fixed Income / Debt / Bond Prospectus
    ("3. Filings / Fixed Income & Bond Prospectus", [
        "bond-prospectus", "bond_prospectus", "bondprospectus",
        "fixed-income", "fixed_income", "fixedincome",
        "debt-prospectus", "debt_prospectus",
        "green-bond", "green_bond", "greenbond",
        "municipal-bond", "municipal_bond",
        "bond-offering", "bond_offering",
        "bond-issue", "bond_issue",
    ]),
    # Prospectus - Equity, M&A, IPO  (before General)
    ("3. Filings / Prospectus - Equity, M&A, IPO", [
        "ipo-prospectus", "ipo_prospectus",
        "equity-prospectus", "equity_prospectus",
        "initial-public-offering", "initial_public_offering",
    ]),
    # Prospectus - General
    ("3. Filings / Prospectus - General", [
        "prospectus",
    ]),
    # Securities Registrations
    ("3. Filings / Securities Registrations", [
        "securities-registration", "securities_registration",
        "listing-application", "listing_application",
        "listingapplication",
    ]),
    # Withdrawal & Termination
    ("3. Filings / Withdrawal & Termination", [
        "withdrawal", "termination",
        "security-withdrawal", "security_withdrawal",
    ]),
    # Debt Indentures, Credit Agreements
    ("3. Filings / Debt Indentures & Credit Agreements", [
        "debt-indenture", "debt_indenture", "debtindenture",
        "credit-agreement", "credit_agreement", "creditagreement",
        "loan-agreement", "loan_agreement",
    ]),
    # Pre-IPO / Privately Held Offering
    ("3. Filings / Pre-IPO & Private Offering", [
        "pre-ipo", "pre_ipo", "preipo",
        "private-offering", "private_offering",
        "privately-held", "privately_held",
    ]),
    # Ownership - Institutional
    ("3. Filings / Ownership - Institutional", [
        "institutional-ownership", "institutional_ownership",
        "institutional-holding", "institutional_holding",
    ]),
    # Ownership - JAPAN5%
    ("3. Filings / Ownership - JAPAN5%", [
        "japan5", "japan-5",
    ]),
    # Ownership - Directors & Officers
    ("3. Filings / Ownership - Directors & Officers", [
        "directors-officers", "directors_officers",
        "officer-ownership", "officer_ownership",
        "director-ownership", "director_ownership",
    ]),
    # Ownership - Beneficial
    ("3. Filings / Ownership - Beneficial", [
        "beneficial-ownership", "beneficial_ownership",
        "beneficialownership",
    ]),
    # Shareholding Pattern
    ("3. Filings / Shareholding Pattern", [
        "shareholding-pattern", "shareholding_pattern",
        "shareholdingpattern", "share-holding-pattern",
    ]),
    # Ownership - General fallback
    ("3. Filings / Ownership", [
        "ownership", "major-shareholder", "major_shareholder",
    ]),
    # Capital Changes — Stock Options
    ("3. Filings / Capital Changes - Stock Options", [
        "stock-option", "stock_option", "stockoption",
        "employee-stock", "employee_stock",
        "esop", "espp",
    ]),
    # Capital Changes — Stock Splits
    ("3. Filings / Capital Changes - Stock Splits", [
        "stock-split", "stock_split", "stocksplit",
        "reverse-split", "reverse_split",
    ]),
    # Capital Changes — Offers
    ("3. Filings / Capital Changes - Offers", [
        "tender-offer", "tender_offer", "tenderoffer",
        "exchange-offer", "exchange_offer",
        "rights-offer", "rights_offer", "rightsoffer",
        "rights-issue", "rights_issue",
    ]),
    # Capital Changes — Repurchase / Buyback
    ("3. Filings / Capital Changes - Repurchase & Buyback", [
        "share-repurchase", "share_repurchase", "sharerepurchase",
        "buyback", "buy-back", "buy_back",
        "securities-purchase", "securities_purchase",
    ]),
    # Capital Changes — Corporate Actions
    ("3. Filings / Capital Changes - Corporate Actions", [
        "corporate-action", "corporate_action", "corporateaction",
    ]),
    # M&A, Merger, Takeover
    ("3. Filings / M&A, Merger, Takeover", [
        "merger", "takeover", "take-over", "take_over",
        "m-and-a", "m_and_a", "m&a",
    ]),
    # Dividends
    ("3. Filings / Dividends", [
        "dividend",
    ]),
    # Auditors Report / Change in Auditor
    ("3. Filings / Auditors Report & Change in Auditor", [
        "auditor", "audit-report", "audit_report", "auditreport",
        "change-in-auditor", "change_in_auditor",
        "auditor-change", "auditor_change",
    ]),
    # Change in Year End
    ("3. Filings / Change in Year End", [
        "change-in-year-end", "change_in_year_end",
        "fiscal-year-change", "fiscal_year_change",
        "year-end-change", "year_end_change",
    ]),
    # Fund Sheets
    ("3. Filings / Fund Sheets", [
        "fund-sheet", "fund_sheet", "fundsheet",
        "fund-report", "fund_report",
        "fund-prospectus", "fund_prospectus",
        "fund-annual", "fund_annual",
        "etf-report", "etf_report",
    ]),

    # ──────────────────────────────────────────
    # 4. ESG (ENVIRONMENTAL, SOCIAL, GOVERNANCE)
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
    # 5. SECTOR-SPECIFIC CONTENT
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
    # 6. COMPANY INFORMATION & PROFILES
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
    # 7. BUSINESS UPDATES & REPORTS
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
    ("7. Business Updates / Corporate Actions Updates", [
        # already matched under Filings but kept for HTML pages
    ]),
    ("7. Business Updates / Funding Announcements", [
        "funding-announcement", "funding_announcement",
        "funding", "fundraise", "fund-raise", "fund_raise",
        "capital-raise", "capital_raise",
    ]),

    # ──────────────────────────────────────────
    # 8. PRODUCT & SERVICE INFORMATION
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

    # ──────────────────────────────────────────
    # CATCH-ALL: Resources page (moved to bottom
    # so it doesn't steal from more specific cats)
    # ──────────────────────────────────────────
    ("5. Sector Specific / Resources Page", [
        "resources", "/resources/",
    ]),
]

# ═══════════════════════════════════════════════════════════════
# OUT OF SCOPE — keywords that mark a URL as irrelevant
# ═══════════════════════════════════════════════════════════════
OUT_OF_SCOPE_KEYWORDS = [
    # Careers / Jobs
    "career", "/careers/", "/careers.",
    "job-posting", "job_posting", "jobposting",
    "/jobs/", "/jobs.",
    # FAQ
    "faq", "frequently-asked", "frequently_asked",
    # Contact
    "contact-us", "contact_us", "contactus",
    "/contact/", "/contact.",
    # Privacy / Legal
    "privacy-policy", "privacy_policy", "privacypolicy",
    "terms-of-use", "terms_of_use", "termsofuse",
    "terms-of-service", "terms_of_service",
    "terms-and-conditions", "terms_and_conditions",
    "disclaimer",
    "accessibility-statement", "accessibility_statement",
    "cookie-policy", "cookie_policy",
    "legal-terms", "legal_terms",
    # Stock / Dividend raw data
    "stock-price", "stock_price", "stockprice",
    "stock-quote", "stock_quote", "stockquote",
    "dividend-history", "dividend_history",
    # Clinical / Pharma
    "clinical-trial", "clinical_trial", "clinicaltrial",
    "/trials/", "/trial/",
    "prescription", "prescribing-information", "prescribing_information",
    "drug-label", "drug_label",
    # Safety sheets
    "safety-sheet", "safety_sheet", "safetysheet",
    "safety-data-sheet", "safety_data_sheet",
    "sds-sheet", "sds_sheet",
    # FDA / Regulatory bodies
    "fda-correspondence", "fda_correspondence",
    "journal-abstract", "journal_abstract",
    # SEC filings (already covered elsewhere)
    "sec-filing", "sec_filing", "secfiling",
    # Third-party research
    "gartner.com", "forrester.com", "idc.com",
    # E-commerce
    "amazon.com", "ebay.com",
    # Forums / Chat
    "reddit.com", "/forum/", "/forums/",
    "open-chat", "open_chat",
    # Recipe docs
    "recipe",
    # Forms
    "/forms/", "registration-form", "registration_form",
    "supplier-form", "supplier_form",
    # News agencies (not about company)
    "timesofindia.com", "theguardian.com",
    # Broker / Consulting research
    "grandviewresearch.com", "williamblair.com",
    "deloitte.com/publications",
]


def categorize_url(url):
    """Categorize a URL based on keyword matching.
    Returns category name, '⛔ Out of Scope', or '❓ Unclassified'."""
    url_lower = url.lower()

    # 1. Check out-of-scope first
    for kw in OUT_OF_SCOPE_KEYWORDS:
        if kw in url_lower:
            return "⛔ Out of Scope"

    # 2. Try each category (first match wins)
    for category_name, keywords in CATEGORY_KEYWORDS:
        if not keywords:  # skip empty keyword lists
            continue
        for kw in keywords:
            if kw in url_lower:
                return category_name

    return "❓ Unclassified"


def categorize_all_urls(urls):
    """Categorize a list of URLs. Returns dict of {category: [urls]}."""
    categorized = defaultdict(list)
    for url in urls:
        cat = categorize_url(url)
        categorized[cat].append(url)
    return dict(categorized)


def normalize_url(url):
    """Normalize URL to avoid duplicates"""
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


def is_social_media_url(url):
    """Check if URL is from social media platforms"""
    social_domains = [
        'instagram.com', 'facebook.com', 'linkedin.com', 'youtube.com',
        'twitter.com', 'x.com', 'tiktok.com', 'snapchat.com', 'pinterest.com',
        'reddit.com', 'tumblr.com', 'whatsapp.com', 'telegram.org'
    ]
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace('www.', '')
    return any(social in domain for social in social_domains)


def is_investor_or_media_page(url):
    """Check if URL likely contains investor or press release information"""
    keywords = ['investor', 'press', 'media', 'news', 'release', 'announcement', 'publication']
    url_lower = url.lower()
    return any(keyword in url_lower for keyword in keywords)


async def extract_json_links(session, url, pdf_regex):
    """Extract links from JSON data on investor/media pages"""
    json_links = set()
    json_pdfs = set()

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                return json_links, json_pdfs

            content_type = response.headers.get('Content-Type', '').lower()

            if 'application/json' in content_type:
                try:
                    data = await response.json()
                    extract_urls_from_json(data, url, json_links, json_pdfs, pdf_regex)
                except:
                    pass
            else:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                for script in soup.find_all('script', type='application/json'):
                    try:
                        if script.string:
                            data = json.loads(script.string)
                            extract_urls_from_json(data, url, json_links, json_pdfs, pdf_regex)
                    except:
                        pass
    except:
        pass

    return json_links, json_pdfs


def extract_urls_from_json(data, base_url, links_set, pdfs_set, pdf_regex):
    """Recursively extract URLs from JSON data"""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and (value.startswith('http') or value.startswith('/')):
                absolute_url = urljoin(base_url, value)
                if absolute_url.startswith('http'):
                    normalized_url = normalize_url(absolute_url)
                    links_set.add(normalized_url)
                    if pdf_regex.search(normalized_url):
                        pdfs_set.add(normalized_url)
            elif isinstance(value, (dict, list)):
                extract_urls_from_json(value, base_url, links_set, pdfs_set, pdf_regex)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str) and (item.startswith('http') or item.startswith('/')):
                absolute_url = urljoin(base_url, item)
                if absolute_url.startswith('http'):
                    normalized_url = normalize_url(absolute_url)
                    links_set.add(normalized_url)
                    if pdf_regex.search(normalized_url):
                        pdfs_set.add(normalized_url)
            elif isinstance(item, (dict, list)):
                extract_urls_from_json(item, base_url, links_set, pdfs_set, pdf_regex)


async def crawl_website(start_url, pdf_pattern, max_depth, max_concurrent, progress_callback):
    """Main crawling function"""
    try:
        if not start_url.startswith(('http://', 'https://')):
            start_url = 'https://' + start_url

        start_url = normalize_url(start_url)
        parsed_start = urlparse(start_url)
        base_domain = parsed_start.netloc

        pdf_regex = re.compile(pdf_pattern, re.IGNORECASE)
        excluded_protocols = ['javascript:', 'mailto:', 'tel:', 'sms:', 'fax:', 'data:', '#']

        visited = set()
        all_links = set()
        pdf_links = set()
        pages_with_pdfs = {}
        json_extracted_links = set()

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
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status != 200:
                            return []

                        content_type = response.headers.get('Content-Type', '').lower()
                        if 'text/html' not in content_type:
                            return []

                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        for a_tag in soup.find_all('a', href=True):
                            href = a_tag['href']

                            if any(href.strip().lower().startswith(proto) for proto in excluded_protocols):
                                continue

                            absolute_url = urljoin(url, href)
                            normalized_absolute = normalize_url(absolute_url)

                            if is_social_media_url(normalized_absolute):
                                continue

                            parsed = urlparse(normalized_absolute)
                            if parsed.scheme not in ['http', 'https']:
                                continue

                            if any(ext in normalized_absolute.lower() for ext in
                                   ['.jpg', '.png', '.gif', '.css', '.js', '.xml',
                                    '.ico', '.svg', '.zip', '.exe']):
                                continue

                            all_links.add(normalized_absolute)

                            if pdf_regex.search(normalized_absolute):
                                pdf_links.add(normalized_absolute)
                                page_pdfs.append(normalized_absolute)

                            if parsed.netloc == base_domain and depth + 1 < max_depth:
                                if normalized_absolute not in visited:
                                    new_urls.append((normalized_absolute, depth + 1))

                        if is_investor_or_media_page(normalized_url):
                            json_links, json_pdfs = await extract_json_links(
                                session, url, pdf_regex
                            )

                            json_links = {
                                link for link in json_links
                                if not is_social_media_url(link)
                            }
                            json_pdfs = {
                                link for link in json_pdfs
                                if not is_social_media_url(link)
                            }

                            json_extracted_links.update(json_links)
                            all_links.update(json_links)
                            pdf_links.update(json_pdfs)
                            page_pdfs.extend(list(json_pdfs))

                        if page_pdfs:
                            pages_with_pdfs[normalized_url] = list(set(page_pdfs))

                except:
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
                        url, depth_val = queue.popleft()
                        tasks.append(fetch_and_parse(session, url, depth_val))

                results = await asyncio.gather(*tasks)

                for new_urls in results:
                    for new_url, new_depth in new_urls:
                        normalized_new = normalize_url(new_url)
                        if normalized_new not in visited:
                            queue.append((normalized_new, new_depth))

        # ── Categorize all links ──
        categorized = categorize_all_urls(sorted(all_links))
        categorized_pdfs = categorize_all_urls(sorted(pdf_links))

        return {
            'all_links': sorted(all_links),
            'pdf_links': sorted(pdf_links),
            'pages_with_pdfs': pages_with_pdfs,
            'pages_crawled': len(visited),
            'json_links_count': len(json_extracted_links),
            'categorized_links': categorized,
            'categorized_pdfs': categorized_pdfs,
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

# Sidebar
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
    ✅ Social Media Filter  
    ✅ JSON Link Extraction  
    ✅ **Keyword-based Categorization**  
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


# Sorting helper used in display tabs
def sort_key(cat_name):
    """Sort: numbered categories first, then Unclassified, then Out of Scope."""
    if cat_name == "❓ Unclassified":
        return (1, cat_name)
    if cat_name == "⛔ Out of Scope":
        return (2, cat_name)
    return (0, cat_name)


# Main content
col1, col2 = st.columns([3, 1])

with col1:
    if st.button("🚀 Start Crawling", type="primary",
                 disabled=st.session_state.crawling):
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
                        url_input, pdf_pattern, depth, concurrent,
                        update_progress
                    ))

                st.session_state.results = results
                st.session_state.crawling = False
                progress_bar.progress(100)
                st.success("✅ Crawl complete!")

with col2:
    if st.button("🗑️ Clear Results"):
        st.session_state.results = None
        st.rerun()

# ═══════════════════════════════════════════════════════════════
# Display results
# ═══════════════════════════════════════════════════════════════
if st.session_state.results:
    results = st.session_state.results

    if 'error' in results:
        st.error(f"Error: {results['error']}")
    else:
        # Summary metrics
        categorized = results.get('categorized_links', {})
        unclassified_count = len(categorized.get("❓ Unclassified", []))
        out_of_scope_count = len(categorized.get("⛔ Out of Scope", []))
        classified_count = (
            len(results['all_links']) - unclassified_count - out_of_scope_count
        )

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("Pages Crawled", results['pages_crawled'])
        with col2:
            st.metric("Total Links", len(results['all_links']))
        with col3:
            st.metric("PDF Links", len(results['pdf_links']))
        with col4:
            st.metric("Classified", classified_count)
        with col5:
            st.metric("Unclassified", unclassified_count)
        with col6:
            st.metric("Out of Scope", out_of_scope_count)

        st.markdown("---")

        # Tabs
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📄 All Links",
            "🏷️ Categorized Links",
            "📑 PDF Links",
            "📑 Categorized PDFs",
            "🗂️ Pages with PDFs",
        ])

        # ── Tab 1: All Links (flat) ──
        with tab1:
            st.subheader(f"All Links Found ({len(results['all_links'])})")
            if results['all_links']:
                for link in results['all_links']:
                    st.markdown(f"[{link}]({link})")

                links_text = "\n".join(results['all_links'])
                st.download_button(
                    label="📥 Download All Links",
                    data=links_text,
                    file_name="all_links.txt",
                    mime="text/plain"
                )
            else:
                st.info("No links found")

        # ── Tab 2: Categorized Links ──
        with tab2:
            st.subheader("🏷️ Links Sorted by Category")

            if categorized:
                report_lines = []
                sorted_cats = sorted(categorized.keys(), key=sort_key)

                for cat in sorted_cats:
                    urls = categorized[cat]
                    report_lines.append(f"\n{'=' * 80}")
                    report_lines.append(f"{cat}  ({len(urls)} URLs)")
                    report_lines.append(f"{'=' * 80}")

                    with st.expander(
                        f"📂 {cat} — {len(urls)} URL(s)",
                        expanded=False
                    ):
                        for u in urls:
                            st.markdown(f"- [{u}]({u})")
                            report_lines.append(u)

                report_text = "\n".join(report_lines)
                st.download_button(
                    label="📥 Download Categorized Report",
                    data=report_text,
                    file_name="categorized_links.txt",
                    mime="text/plain",
                    key="dl_cat_links",
                )
            else:
                st.info("No links to categorize")

        # ── Tab 3: PDF Links (flat) ──
        with tab3:
            st.subheader(f"PDF Links ({len(results['pdf_links'])})")
            if results['pdf_links']:
                for link in results['pdf_links']:
                    st.markdown(f"[{link}]({link})")

                pdf_text = "\n".join(results['pdf_links'])
                st.download_button(
                    label="📥 Download PDF Links",
                    data=pdf_text,
                    file_name="pdf_links.txt",
                    mime="text/plain"
                )
            else:
                st.info("No PDF links found")

        # ── Tab 4: Categorized PDFs ──
        with tab4:
            st.subheader("📑 PDF Links Sorted by Category")
            categorized_pdfs = results.get('categorized_pdfs', {})

            if categorized_pdfs:
                pdf_report_lines = []
                sorted_pdf_cats = sorted(
                    categorized_pdfs.keys(), key=sort_key
                )

                for cat in sorted_pdf_cats:
                    urls = categorized_pdfs[cat]
                    pdf_report_lines.append(f"\n{'=' * 80}")
                    pdf_report_lines.append(f"{cat}  ({len(urls)} PDFs)")
                    pdf_report_lines.append(f"{'=' * 80}")

                    with st.expander(
                        f"📂 {cat} — {len(urls)} PDF(s)",
                        expanded=False
                    ):
                        for u in urls:
                            st.markdown(f"- [{u}]({u})")
                            pdf_report_lines.append(u)

                pdf_report_text = "\n".join(pdf_report_lines)
                st.download_button(
                    label="📥 Download Categorized PDFs",
                    data=pdf_report_text,
                    file_name="categorized_pdfs.txt",
                    mime="text/plain",
                    key="dl_cat_pdfs",
                )
            else:
                st.info("No PDF links to categorize")

        # ── Tab 5: Pages with PDFs ──
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
                        st.markdown(
                            f"**Page:** [{page_url}]({page_url})"
                        )
                        st.markdown(
                            f"**Contains {len(pdfs)} PDF(s):**"
                        )
                        for pdf in pdfs:
                            cat = categorize_url(pdf)
                            st.markdown(
                                f"  ↳ [{pdf}]({pdf})  `{cat}`"
                            )
            else:
                st.info("No pages with PDFs found")
