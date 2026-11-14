"""The source registry: every feed this application is allowed to collect from.

**Every URL in this file was fetched from this development host on 2026-11-14** by
``scripts/probe_feeds.py``, and the entry records what came back: HTTP status, entry count and
how many entries carried a description. No URL here was guessed. Endpoints that answered 403,
404 or returned zero parsable entries are kept in :data:`REJECTED_CANDIDATES` with the reason,
so nobody re-tries them next month and so the absence is evidence rather than an oversight.

**Licensing is the other half of an entry, and the default is restrictive.** Of the thirty-one
sources below (twenty-nine active), twenty-eight are ``UNKNOWN`` - headline, publisher,
timestamp and link, and nothing else - because no reuse permission has been researched for
them. Three are not:

* The Conversation (fr and en): **CC BY-ND**, confirmed on their republishing-guidelines page.
  Full text may be republished verbatim; translation and summarisation are forbidden, and their
  guidelines separately prohibit use as AI training data. The model in
  :mod:`app.models.licensing` encodes exactly that: ``allows_full_text`` yes,
  ``allows_derivatives`` no.
* European Commission press releases: **CC BY 4.0**, confirmed on the Commission's legal
  notice, implementing Decision 2011/833/EU. Derivatives are permitted, so this is currently
  the only source from which the application may publish a generated summary.

Raising any other source above ``UNKNOWN`` requires reading that publisher's terms and putting
the citation in ``license_evidence``. The ``NewsSource.__post_init__`` guard refuses an
elevated licence with an empty evidence field.
"""

from __future__ import annotations

from app.models.article import Category
from app.models.licensing import LicenseType
from app.models.source import NewsSource, SourceType, VerificationState

_VERIFIED = "2026-11-14"

#: Boilerplate for the twenty-eight sources with no researched permission.
_NO_PERMISSION = (
    "None. No reuse permission has been researched or obtained for this publisher. "
    "Treated as UNKNOWN: title, publisher, publication time and original URL only."
)


def _unknown(
    source_id: str,
    name: str,
    domain: str,
    country: str,
    language: str,
    feed_url: str,
    items: int,
    *,
    category: Category | None = None,
    interval: int = 30,
    notes: str = "",
) -> NewsSource:
    """A fetch-verified source with no researched reuse permission - the common case."""
    return NewsSource(
        source_id=source_id,
        name=name,
        domain=domain,
        country=country,
        language=language,
        source_type=SourceType.RSS,
        feed_url=feed_url,
        enabled=True,
        verification=VerificationState.FETCH_VERIFIED,
        verified_on=_VERIFIED,
        verified_item_count=items,
        license_type=LicenseType.UNKNOWN,
        attribution_required=True,
        commercial_reuse_allowed=False,
        modification_allowed=False,
        summary_republication_allowed=False,
        license_evidence=_NO_PERMISSION,
        attribution_text=name,
        default_category=category.value if category else None,
        fetch_interval_minutes=interval,
        notes=notes,
    )


SOURCES: tuple[NewsSource, ...] = (
    # ------------------------------------------------------------------ France, French
    _unknown("lemonde-une", "Le Monde", "lemonde.fr", "FR", "fr",
             "https://www.lemonde.fr/rss/une.xml", 16, category=Category.FRANCE,
             notes="Front page. Article pages are paywalled; only the feed is used."),
    _unknown("lemonde-international", "Le Monde", "lemonde.fr", "FR", "fr",
             "https://www.lemonde.fr/international/rss_full.xml", 20,
             category=Category.INTERNATIONAL),
    _unknown("lemonde-politique", "Le Monde", "lemonde.fr", "FR", "fr",
             "https://www.lemonde.fr/politique/rss_full.xml", 20, category=Category.POLITICS),
    _unknown("lemonde-economie", "Le Monde", "lemonde.fr", "FR", "fr",
             "https://www.lemonde.fr/economie/rss_full.xml", 20, category=Category.ECONOMY),
    _unknown("lemonde-sciences", "Le Monde", "lemonde.fr", "FR", "fr",
             "https://www.lemonde.fr/sciences/rss_full.xml", 20, category=Category.SCIENCE),
    _unknown("lemonde-sport", "Le Monde", "lemonde.fr", "FR", "fr",
             "https://www.lemonde.fr/sport/rss_full.xml", 20, category=Category.SPORTS),
    _unknown("franceinfo-titres", "franceinfo", "francetvinfo.fr", "FR", "fr",
             "https://www.francetvinfo.fr/titres.rss", 32, category=Category.FRANCE,
             interval=20),
    _unknown("franceinfo-monde", "franceinfo", "francetvinfo.fr", "FR", "fr",
             "https://www.francetvinfo.fr/monde.rss", 20, category=Category.INTERNATIONAL),
    _unknown("franceinfo-economie", "franceinfo", "francetvinfo.fr", "FR", "fr",
             "https://www.francetvinfo.fr/economie.rss", 20, category=Category.ECONOMY),
    _unknown("lefigaro-actualites", "Le Figaro", "lefigaro.fr", "FR", "fr",
             "https://www.lefigaro.fr/rss/figaro_actualites.xml", 18, category=Category.FRANCE,
             notes="17 of 18 entries carried a description when probed."),
    _unknown("france24-fr", "France 24", "france24.com", "FR", "fr",
             "https://www.france24.com/fr/rss", 24, category=Category.INTERNATIONAL),
    _unknown("rfi-fr", "RFI", "rfi.fr", "FR", "fr",
             "https://www.rfi.fr/fr/france/rss", 30, category=Category.FRANCE,
             notes="27 of 30 entries carried a description when probed."),
    _unknown("futura-sciences", "Futura Sciences", "futura-sciences.com", "FR", "fr",
             "https://www.futura-sciences.com/rss/actualites.xml", 50,
             category=Category.SCIENCE, interval=120),
    _unknown("sciencepost", "Sciencepost", "sciencepost.fr", "FR", "fr",
             "https://sciencepost.fr/feed/", 400, category=Category.SCIENCE, interval=120,
             notes="Returns 400 entries and 1.2 MB per fetch; polled every two hours."),

    # ------------------------------------------------------------------ Europe, institutions
    NewsSource(
        source_id="ec-presscorner-en",
        name="European Commission",
        domain="ec.europa.eu",
        country="EU",
        language="en",
        source_type=SourceType.RSS,
        feed_url="https://ec.europa.eu/commission/presscorner/api/rss?language=en",
        enabled=True,
        verification=VerificationState.FETCH_VERIFIED,
        verified_on=_VERIFIED,
        verified_item_count=10,
        license_type=LicenseType.CC_BY,
        attribution_required=True,
        commercial_reuse_allowed=True,
        modification_allowed=True,
        summary_republication_allowed=True,
        metadata_reuse_policy=(
            "Full reuse with attribution under CC BY 4.0, including derivative summaries and "
            "translations. Third-party material inside a release is excluded."
        ),
        license_evidence=(
            "https://commission.europa.eu/legal-notice_en, read 2026-11-14: 'Unless otherwise "
            "indicated (e.g. in individual copyright notices), content owned by the EU on this "
            "website is licensed under the Creative Commons Attribution 4.0 International "
            "(CC BY 4.0) licence.' Implements Commission Decision of 12 December 2011 on the "
            "reuse of Commission documents (2011/833/EU). Note the carve-out: material the EU "
            "does not own, and content depicting identifiable individuals, needs separate "
            "clearance, so full-text reuse of an individual release is not automatic."
        ),
        attribution_text="© European Union, 1995-2026 — CC BY 4.0",
        default_category=Category.EUROPE.value,
        fetch_interval_minutes=60,
    ),
    _unknown("euronews-news", "Euronews", "euronews.com", "EU", "en",
             "https://www.euronews.com/rss?level=theme&name=news", 50,
             category=Category.EUROPE, interval=45),

    # ------------------------------------------------------------------ International, English
    _unknown("bbc-news", "BBC News", "bbci.co.uk", "GB", "en",
             "https://feeds.bbci.co.uk/news/rss.xml", 32, category=Category.INTERNATIONAL,
             interval=20),
    _unknown("bbc-world", "BBC News", "bbci.co.uk", "GB", "en",
             "https://feeds.bbci.co.uk/news/world/rss.xml", 23,
             category=Category.INTERNATIONAL),
    _unknown("dw-en", "Deutsche Welle", "dw.com", "DE", "en",
             "https://rss.dw.com/rdf/rss-en-all", 128, category=Category.INTERNATIONAL,
             interval=45, notes="Large feed: 128 entries, 117 kB per fetch."),
    _unknown("guardian-world", "The Guardian", "theguardian.com", "GB", "en",
             "https://www.theguardian.com/world/rss", 45, category=Category.INTERNATIONAL,
             interval=30),
    _unknown("aljazeera-all", "Al Jazeera", "aljazeera.com", "QA", "en",
             "https://www.aljazeera.com/xml/rss/all.xml", 25,
             category=Category.INTERNATIONAL),
    _unknown("npr-news", "NPR", "npr.org", "US", "en",
             "https://feeds.npr.org/1001/rss.xml", 10, category=Category.INTERNATIONAL),
    _unknown("arstechnica", "Ars Technica", "arstechnica.com", "US", "en",
             "https://arstechnica.com/feed/", 20, category=Category.TECHNOLOGY, interval=60),
    _unknown("nature", "Nature", "nature.com", "GB", "en",
             "https://www.nature.com/nature.rss", 75, category=Category.SCIENCE, interval=180),

    # ------------------------------------------------------------------ Chinese
    _unknown("dw-zh", "德国之声", "dw.com", "DE", "zh",
             "https://rss.dw.com/rdf/rss-chi-all", 61, category=Category.INTERNATIONAL,
             interval=45),
    _unknown("rfi-zh", "法国国际广播电台", "rfi.fr", "FR", "zh",
             "https://www.rfi.fr/cn/rss", 30, category=Category.INTERNATIONAL, interval=45),
    _unknown("nytimes-zh", "纽约时报中文网", "cn.nytimes.com", "US", "zh",
             "https://cn.nytimes.com/rss/", 20, category=Category.INTERNATIONAL, interval=60,
             notes=(
                 "Timed out on the first probe on 2026-11-14 and was listed as rejected; a "
                 "re-probe the same day returned HTTP 200 with 20 entries, all carrying "
                 "descriptions. Kept at a 60-minute interval given that history."
             )),

    # ------------------------------------------------------------------ Openly licensed
    NewsSource(
        source_id="theconversation-fr",
        name="The Conversation France",
        domain="theconversation.com",
        country="FR",
        language="fr",
        source_type=SourceType.ATOM,
        feed_url="https://theconversation.com/fr/articles.atom",
        enabled=True,
        verification=VerificationState.FETCH_VERIFIED,
        verified_on=_VERIFIED,
        verified_item_count=50,
        license_type=LicenseType.CC_BY_ND,
        attribution_required=True,
        commercial_reuse_allowed=True,
        modification_allowed=False,
        summary_republication_allowed=False,
        metadata_reuse_policy=(
            "Verbatim republication of the whole article with attribution. No translation, no "
            "summary, no excerpting that alters meaning: ND forbids derivative works."
        ),
        license_evidence=(
            "https://theconversation.com/fr/republishing-guidelines, read 2026-11-14: content "
            "is published under a 'licence Creative Commons Attribution/Pas de modification' "
            "(CC BY-ND). The English guidelines add that the licence prohibits using the "
            "content as AI training data, and that embedded images are licensed separately by "
            "their creators and must be checked individually."
        ),
        attribution_text="The Conversation France — CC BY-ND",
        default_category=Category.SCIENCE.value,
        fetch_interval_minutes=120,
        notes=(
            "836 kB per fetch: the Atom feed carries full article bodies. Because ND forbids "
            "derivatives, this source is readable but must never be summarised or translated."
        ),
    ),
    NewsSource(
        source_id="theconversation-en",
        name="The Conversation",
        domain="theconversation.com",
        country="GB",
        language="en",
        source_type=SourceType.ATOM,
        feed_url="https://theconversation.com/articles.atom",
        enabled=True,
        verification=VerificationState.FETCH_VERIFIED,
        verified_on=_VERIFIED,
        verified_item_count=50,
        license_type=LicenseType.CC_BY_ND,
        attribution_required=True,
        commercial_reuse_allowed=True,
        modification_allowed=False,
        summary_republication_allowed=False,
        metadata_reuse_policy=(
            "Verbatim republication with attribution. No translation or summary."
        ),
        license_evidence=(
            "https://theconversation.com/uk/republishing-guidelines, read 2026-11-14: "
            "'Creative Commons Attribution-No Derivatives licence'. Same AI-training and "
            "third-party-image carve-outs as the French edition."
        ),
        attribution_text="The Conversation — CC BY-ND",
        default_category=Category.SCIENCE.value,
        fetch_interval_minutes=120,
    ),

    # ------------------------------------------------------------------ GDELT
    NewsSource(
        source_id="gdelt-gal",
        name="GDELT Article List",
        domain="gdeltproject.org",
        country="XX",
        language="mul",
        source_type=SourceType.GDELT_GAL_JSONNL,
        # A base URL, not a file: see GDELTGALCollector.candidate_urls.
        feed_url="https://data.gdeltproject.org/gdeltv3/gal/",
        # Disabled by default, and this is a product decision rather than a technical one.
        # GAL works: it is fetch-verified, its schema was measured, and a French-filtered run
        # returned 184 articles in 9 seconds. What those 184 articles *are* is the problem.
        # Filtering GAL to `fr` yields the francophone world, not French news: on 2026-11-14
        # the largest contributors were a Tunisian daily (29), an Algerian paper
        # re-publishing its 2020 archive (16) and a Senegalese site (11). For a household
        # reading French news over breakfast that is noise, and it buries Le Monde and
        # franceinfo under it.
        #
        # Enable with COLLECTOR_ONLY_SOURCES or by flipping this flag; the collector, the
        # language filter and the per-domain cap are all in place and tested.
        enabled=False,
        verification=VerificationState.FETCH_VERIFIED,
        verified_on=_VERIFIED,
        verified_item_count=1791,
        verification_note=(
            "Working and verified. Disabled on editorial grounds, not technical ones - see "
            "the comment above and docs/DATA_SOURCES.md section 1.6."
        ),
        license_type=LicenseType.UNKNOWN,
        attribution_required=True,
        commercial_reuse_allowed=False,
        modification_allowed=False,
        summary_republication_allowed=False,
        metadata_reuse_policy=(
            "Title, outlet, timestamp and original URL only. GDELT indexes other publishers' "
            "pages; it does not license their content, and the 150-character 'desc' it carries "
            "belongs to each underlying publisher. The description is measured and discarded."
        ),
        license_evidence=(
            "No per-publisher permission exists and none can exist: a single GAL file carried "
            "545 distinct domains when measured on 2026-11-14. GDELT's own dataset terms do "
            "not and cannot grant reuse rights over the indexed articles."
        ),
        attribution_text="Discovered via the GDELT Project",
        fetch_interval_minutes=15,
        notes=(
            "Firehose: ~1,800 articles per file, 40+ languages, and no editorial filter - the "
            "same file carries wire copy and marketing blogs. Two files per run by default."
        ),
    ),
    NewsSource(
        source_id="gdelt-gal-rss",
        name="GDELT Article List (RSS)",
        domain="gdeltproject.org",
        country="XX",
        language="mul",
        source_type=SourceType.GDELT_GAL_RSS,
        feed_url="https://data.gdeltproject.org/gdeltv3/gal/feed.rss",
        # Disabled deliberately: measured on 2026-11-14 it carries title, link and pubDate
        # only - no description, no language, no outlet - so it is strictly worse than the
        # JSON-NL files above while costing a 1 MB download every fetch.
        enabled=False,
        verification=VerificationState.FETCH_VERIFIED,
        verified_on=_VERIFIED,
        verified_item_count=3600,
        license_type=LicenseType.UNKNOWN,
        license_evidence="Same as gdelt-gal: GDELT indexes, it does not license.",
        attribution_text="Discovered via the GDELT Project",
        verification_note=(
            "Reachable and parsable (HTTP 200, 1,054,163 bytes, 3,600 entries) but metadata-poor: "
            "0 of 3,600 entries carried a description. Superseded by gdelt-gal."
        ),
        fetch_interval_minutes=60,
    ),
)


#: Endpoints that were probed and rejected, with the measured reason. Kept so the absence of a
#: well-known outlet is a recorded decision rather than something nobody thought of.
REJECTED_CANDIDATES: dict[str, str] = {
    "https://www.europarl.europa.eu/rss/doc/top-stories/en.xml":
        "HTTP 403 on 2026-11-14. The European Parliament refuses this client; not worked around.",
    "https://www.europarl.europa.eu/rss/doc/top-stories/fr.xml": "HTTP 403 on 2026-11-14.",
    "https://www.consilium.europa.eu/en/press/press-releases/rss.xml": "HTTP 403 on 2026-11-14.",
    "https://apnews.com/apf-topnews":
        "HTTP 403 on 2026-11-14. AP blocks automated clients at this path.",
    "https://www.reutersagency.com/feed/": "HTTP 404 on 2026-11-14; the feed has moved or ended.",
    "https://www.france24.com/zh/rss": "HTTP 404 on 2026-11-14. No Chinese France 24 feed found.",
    "https://www.france24.com/zh-hans/rss": "HTTP 404 on 2026-11-14.",
    "https://www.liberation.fr/arc/outboundfeeds/collection/accueil-une/?outputType=xml":
        "HTTP 200 but 0 parsable entries on 2026-11-14, re-probed the same day with the same "
        "result. Liberation's outbound feed returns XML this parser cannot read as a feed.",
    "https://rss.dw.com/xml/rss-fr-all":
        "HTTP 200 with a 28-byte empty body on 2026-11-14. DW's French feed is at another path.",
    "https://chinese.aljazeera.net/feed":
        "HTTP 200, 352 kB, but 0 parsable entries on 2026-11-14, re-probed the same day with "
        "the same result (feedparser bozo). The body is served but is not a feed.",
    "https://www.voachinese.com/api/zkvypeuikq":
        "HTTP 200 with an 11-byte body on 2026-11-14.",
    "https://feedx.net/rss/zaobao.xml":
        "HTTP 200, 20 entries on 2026-11-14. Rejected on provenance, not reachability: a "
        "third-party mirror "
        "of Lianhe Zaobao, not the publisher's own feed, so neither its completeness nor its "
        "right to redistribute can be established.",
}


def active_sources() -> tuple[NewsSource, ...]:
    """Sources that may be collected from. The only entry point the pipeline should use."""
    return tuple(s for s in SOURCES if s.enabled)


def by_id(source_id: str) -> NewsSource | None:
    return next((s for s in SOURCES if s.source_id == source_id), None)


def sources_permitting_derivatives() -> tuple[NewsSource, ...]:
    """Sources whose licence allows a generated summary or translation to be published."""
    return tuple(s for s in SOURCES if s.enabled and s.summary_republication_allowed)
