"""Category assignment.

Specification section 9 asks for lightweight classification and says explicitly not to reach
for AI before it is necessary. The order of evidence here follows from that:

1. **The source's own section.** ``lemonde.fr/politique/rss_full.xml`` publishes politics.
   This is the publisher's own editorial judgement and costs nothing, so it wins.
2. **Keyword matching on the headline**, for general feeds that mix sections and for the GDELT
   firehose, which has no sections at all.
3. **Abstention.** When neither fires, the category is ``OTHER``. A wrong category is worse
   than no category: it hides an article from the section a reader is browsing *and* puts it
   in one where it does not belong.

Geography is treated as a separate axis from topic, because the specification's category list
mixes the two - ``FRANCE``, ``EUROPE`` and ``INTERNATIONAL`` are places, the rest are subjects.
A French article about the economy is economy; it does not stop being French. So the primary
category prefers the subject when one is detected, and the geographic label becomes a secondary
category rather than competing with it.
"""

from __future__ import annotations

import re

from app.models.article import Article, Category
from app.processors.normalization import normalise_title

#: Accent-folded lowercase stems, matched against the normalised headline. Trailing spaces are
#: significant: " ia " must not match "iago". Keys are checked in dictionary order and the
#: first subject category to match wins, so the more specific ones come first.
KEYWORDS: dict[Category, tuple[str, ...]] = {
    Category.ARTIFICIAL_INTELLIGENCE: (
        "intelligence artificielle", "artificial intelligence", "machine learning",
        "apprentissage automatique", "chatgpt", "openai", "anthropic", "claude", "gemini",
        "llm", "large language model", "modele de langage", "deep learning", "generative ai",
        "ia generative", "人工智能", "人工智慧", "大模型", "生成式",
    ),
    Category.TECHNOLOGY: (
        "numerique", "logiciel", "software", "cyberattaque", "cyberattack", "cybersecurite",
        "cybersecurity", "smartphone", "internet", "reseaux sociaux", "social media",
        "startup", "semi conducteur", "semiconductor", "puce", "chip", "microsoft", "apple",
        "google", "meta", "nvidia", "tiktok", "algorithme", "algorithm", "donnees personnelles",
        "data breach", "quantum", "quantique", "科技", "互联网", "芯片", "软件",
    ),
    Category.HEALTH: (
        "sante", "health", "hopital", "hospital", "vaccin", "vaccine", "epidemie", "epidemic",
        "pandemie", "pandemic", "cancer", "virus", "maladie", "disease", "medecin", "doctor",
        "oms", "who warns", "mental health", "sante mentale", "健康", "医院", "疫苗", "疾病",
    ),
    Category.ENVIRONMENT: (
        "climat", "climate", "rechauffement", "global warming", "biodiversite", "biodiversity",
        "pollution", "cop30", "cop31", "emissions", "carbone", "carbon", "deforestation",
        "energie renouvelable", "renewable", "secheresse", "drought", "inondation", "flood",
        "environnement", "environment", "气候", "环境", "污染", "碳排放",
    ),
    Category.SCIENCE: (
        "chercheur", "researcher", "etude scientifique", "scientific study", "recherche",
        "cnrs", "nasa", "espace", "space", "fusee", "rocket", "satellite", "telescope",
        "astronomie", "astronomy", "physique", "physics", "genome", "adn", "dna",
        "archeolog", "archaeolog", "科学", "研究", "太空",
    ),
    Category.FINANCE: (
        "bourse", "stock market", "cac 40", "nasdaq", "dow jones", "bce", "ecb",
        "banque centrale", "central bank", "taux directeur", "interest rate", "obligations",
        "bonds", "crypto", "bitcoin", "wall street", "股市", "加息", "央行",
    ),
    Category.ECONOMY: (
        "inflation", "croissance", "growth", "chomage", "unemployment", "pouvoir d achat",
        "budget", "deficit", "dette publique", "public debt", "impot", "tax", "fiscalite",
        "salaire", "wages", "smic", "retraite", "pension", "pib", "gdp", "tarifs douaniers",
        "tariffs", "recession", "经济", "通胀", "失业",
    ),
    Category.BUSINESS: (
        "entreprise", "company", "fusion acquisition", "merger", "acquisition", "ipo",
        "licenciement", "layoffs", "chiffre d affaires", "revenue", "benefices", "profits",
        "faillite", "bankruptcy", "ceo", "pdg", "企业", "收购", "裁员",
    ),
    Category.POLITICS: (
        "gouvernement", "government", "assemblee nationale", "senat", "senate", "parliament",
        "parlement", "ministre", "minister", "elysee", "depute", "elections", "election",
        "scrutin", "referendum", "municipales", "legislatives", "presidentielle",
        "presidential", "matignon", "motion de censure", "projet de loi", "coalition",
        "political", "politique", "macron", "president", "chancelier", "chancellor",
        "政府", "选举", "议会",
    ),
    Category.SPORTS: (
        "football", "soccer", "rugby", "tennis", "basketball", "olympique", "olympics",
        "championnat", "championship", "ligue 1", "premier league", "formule 1", "formula 1",
        "tour de france", "coupe du monde", "world cup", "match", "nba", "nfl", "golf",
        "leaderboard", "体育", "足球", "奥运",
    ),
    Category.CULTURE: (
        "cinema", "film", "festival", "musee", "museum", "exposition", "exhibition",
        "litterature", "literature", "roman", "musique", "music", "album", "theatre",
        "concert", "oscar", "cannes", "文化", "电影", "音乐",
    ),
    Category.EDUCATION: (
        "education", "ecole", "school", "lycee", "universite", "university", "etudiant",
        "student", "bac", "enseignant", "teacher", "scolaire", "教育", "学校", "大学",
    ),
}

#: Geographic signals. Secondary to subject: see the module docstring.
GEOGRAPHY: dict[Category, tuple[str, ...]] = {
    Category.EUROPE: (
        "union europeenne", "european union", "bruxelles", "brussels", "commission europeenne",
        "european commission", "parlement europeen", "european parliament", "eurozone",
        "zone euro", "otan", "nato", "strasbourg", "欧盟", "欧洲",
    ),
    Category.FRANCE: (
        "france", "francais", "french", "paris", "lyon", "marseille", "elysee", "matignon",
        "assemblee nationale", "法国", "巴黎",
    ),
    Category.INTERNATIONAL: (
        "etats unis", "united states", "washington", "chine", "china", "beijing", "pekin",
        "russie", "russia", "moscou", "moscow", "ukraine", "kyiv", "kiev", "israel", "gaza",
        "iran", "inde", "india", "japon", "japan", "bresil", "brazil", "afrique", "africa",
        "onu", "united nations", "国际", "美国", "中国",
    ),
}


def _compile(table: dict[Category, tuple[str, ...]]) -> dict[Category, re.Pattern[str]]:
    """One alternation per category. Word-boundary anchored for Latin, bare for CJK.

    CJK has no word boundaries, so ``\\b`` would never match a Chinese keyword; those terms are
    matched as plain substrings, which is correct for a script without spaces.
    """
    compiled: dict[Category, re.Pattern[str]] = {}
    for category, terms in table.items():
        parts = []
        for term in terms:
            escaped = re.escape(term)
            if re.search(r"[一-鿿]", term):
                parts.append(escaped)
            else:
                parts.append(rf"\b{escaped}")
        compiled[category] = re.compile("|".join(parts))
    return compiled


_SUBJECT_PATTERNS = _compile(KEYWORDS)
_GEOGRAPHY_PATTERNS = _compile(GEOGRAPHY)


def classify_text(text: str) -> tuple[Category | None, list[Category]]:
    """Returns ``(subject, geographies)`` detected in a headline. ``None`` when it abstains.

    The subject is the category with the *most* keyword hits, not the first to match. A
    headline like "Macron presents the budget to the Assemblee nationale" hits ``budget`` for
    economy and both ``assemblee nationale`` and the president for politics; first-match order
    would call it economy, and counting calls it politics. Ties fall back to the order of
    :data:`KEYWORDS`, which runs from most specific to most general.
    """
    # The normalised form folds accents and strips punctuation, which is what the Latin
    # keywords are written against. CJK survives normalisation unchanged.
    haystack = f" {normalise_title(text)} "

    best: Category | None = None
    best_hits = 0
    for category, pattern in _SUBJECT_PATTERNS.items():
        hits = len(pattern.findall(haystack))
        if hits > best_hits:
            best, best_hits = category, hits

    geographies = [cat for cat, pattern in _GEOGRAPHY_PATTERNS.items() if pattern.search(haystack)]
    return best, geographies


def classify(article: Article, source_default: Category | None = None) -> Article:
    """Assigns ``category`` and ``secondary_categories`` in place and returns the article.

    ``source_default`` is the registry's category for a section feed. It is trusted over
    keywords for the primary category, because the publisher filed the article in that section
    deliberately, but it does not suppress geography detection.
    """
    subject, geographies = classify_text(article.title)

    if source_default and source_default is not Category.OTHER:
        primary = source_default
        secondary = [c for c in ([subject] if subject else []) + geographies if c != primary]
    elif subject:
        primary = subject
        secondary = [c for c in geographies if c != primary]
    elif geographies:
        primary, *rest = geographies
        secondary = rest
    else:
        primary, secondary = Category.OTHER, []

    article.category = primary
    # Deduplicate while preserving order; a headline can hit the same geography twice.
    seen: set[Category] = set()
    article.secondary_categories = [
        c for c in secondary if not (c in seen or seen.add(c))
    ][:3]
    return article
