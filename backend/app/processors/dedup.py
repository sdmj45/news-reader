"""Deduplication and cross-publisher event grouping.

Specification section 7 asks for five layers and sets one constraint that shapes the whole
design: *never rely exclusively on title matching*, and *keep individual article records* -
five outlets covering one story is five pieces of journalism, not four redundant ones.

So the module does two different jobs and keeps them apart:

:func:`deduplicate`
    Decides that two records are **the same article**, and keeps one. The only evidence
    accepted is the canonical URL, because that is the only signal that cannot be wrong. Two
    articles with identical headlines from different publishers are not the same article.

:func:`cluster_events`
    Decides that two *different* articles **cover the same event**, and links them with a
    shared ``event_id`` without deleting either. Over-merging is the worse failure here, so a
    pair is grouped only when it agrees on time, on content words, and on a named entity.

Multilingual by necessity: the registry carries French, English and Chinese sources, and the
GDELT firehose carries forty more languages. Tokenisation therefore branches - whitespace
languages are tokenised on words with stopwords removed, CJK on character bigrams, which is
the standard cheap substitute for a segmenter and needs no model or dictionary.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.models.article import Article
from app.processors.normalization import normalise_title

#: Articles published further apart than this are never grouped, however similar the headlines.
#: Rolling coverage of one event spans a day or two; beyond that it is a different story.
TIME_WINDOW_HOURS = 36

#: Jaccard overlap of content tokens required before a pair is even considered.
TITLE_SIMILARITY_THRESHOLD = 0.42

#: CJK bigrams overlap more readily than words do, so the bar is higher.
CJK_SIMILARITY_THRESHOLD = 0.55

#: Two single-word entities, or one multi-word entity, is the evidence rule 3 requires.
MIN_SHARED_SINGLE_ENTITIES = 2

_WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
#: A capitalised run - "Emmanuel Macron", "European Central Bank". Latin scripts only.
_ENTITY_RE = re.compile(
    r"\b([A-ZÀ-Þ][\wÀ-ÿ'-]+(?:\s+(?:de|du|des|la|le|of|the|d')?\s*[A-ZÀ-Þ][\wÀ-ÿ'-]+)*)"
)

#: Function words carry no topical signal and would inflate every similarity score. Covers the
#: three interface languages plus the European languages GDELT supplies most of.
STOPWORDS = frozenset(
    (
    # French
    "a au aux avec ce ces dans de des du elle en et eux il ils je la le les leur lui ma mais me "
    "meme mes moi mon ne nos notre nous on ou par pas pour qu que qui sa se ses son sur ta te "
    "tes toi ton tu un une vos votre vous c d j l m n s t y ete etant suis es est sommes sont "
    "sera seront etait etaient ai as avons avez ont plus moins tres bien entre apres avant "
    "depuis vers chez sans sous contre pendant selon alors ainsi aussi encore deja toujours "
    "jamais quand comme si donc or ni car lors dont leurs cette cet quel quelle tout tous toute "
    "toutes autre autres apres "
    # English
    "the a an and or but of to in on at for with by from as is are was were be been being this "
    "that these those it its his her their our your my we you they he she i not no nor so if "
    "then than when while after before over under about into out up down new says said will "
    "would can could may might must have has had do does did "
    # German, Spanish, Italian, Portuguese - the next most common in GAL
    "der die das und ist von den dem ein eine mit sich auf fur el la los las y en que se con por "
    "para del al un una es il lo gli una di da del nel che non per come piu os as uma dos no na"
    ).split()
)

#: Tokens that look like entities but are too common in headlines to identify an event.
_GENERIC_ENTITIES = frozenset(
    {
        "France", "Paris", "Europe", "European", "Union", "State", "States", "Government",
        "President", "Minister", "US", "USA", "UK", "China", "World", "News", "Live",
        "Etat", "État", "Gouvernement", "Assemblée", "Sénat", "Monde", "International",
    }
)


@dataclass
class DeduplicationReport:
    """What :func:`deduplicate` actually did, for the metrics in specification section 14.5."""

    input_count: int = 0
    kept_count: int = 0
    duplicate_canonical_url: int = 0
    """Collapsed because the canonical URL matched exactly."""

    @property
    def duplicate_rate(self) -> float:
        return (self.input_count - self.kept_count) / self.input_count if self.input_count else 0.0


@dataclass
class EventCluster:
    """Articles covering one event. Membership, never a merge - each article survives."""

    event_id: str
    articles: list[Article] = field(default_factory=list)

    @property
    def publishers(self) -> set[str]:
        return {a.publisher for a in self.articles}

    @property
    def is_multi_publisher(self) -> bool:
        return len(self.publishers) > 1


# --------------------------------------------------------------------------- layer 1-3

def deduplicate(articles: list[Article]) -> tuple[list[Article], DeduplicationReport]:
    """Collapses records that are the *same article*, keeping the earliest-discovered one.

    Layers one to three of specification section 7 collapse into one comparison, because
    :func:`app.processors.normalization.canonicalise_url` already performs exact matching, URL
    normalisation and tracking-parameter removal. Running them as three separate passes would
    produce three identical answers.

    Title similarity is deliberately *not* used here. Two publishers writing the same headline
    is routine - wire copy guarantees it - and deleting one of them would silently discard a
    publisher's work. That case is handled by :func:`cluster_events` instead.
    """
    report = DeduplicationReport(input_count=len(articles))
    kept: dict[str, Article] = {}

    for article in articles:
        key = article.canonical_url
        existing = kept.get(key)
        if existing is None:
            kept[key] = article
            continue
        report.duplicate_canonical_url += 1
        # Keep whichever was discovered first, but take the better metadata from the other:
        # feeds differ in what they supply for the same URL.
        kept[key] = _merge(existing, article)

    report.kept_count = len(kept)
    return list(kept.values()), report


def _merge(primary: Article, other: Article) -> Article:
    """Fills gaps in ``primary`` from ``other``. Never overwrites a value that is already set."""
    if primary.discovered_at <= other.discovered_at:
        base, extra = primary, other
    else:
        base, extra = other, primary

    if not base.image_url and extra.image_url:
        base.image_url = extra.image_url
    if not base.author and extra.author:
        base.author = extra.author
    if not base.original_description and extra.original_description:
        # Only if the *extra* record's own licence permitted keeping it, which it must have
        # done for the field to be populated at all.
        base.original_description = extra.original_description
    if base.offered_description_chars == 0:
        base.offered_description_chars = extra.offered_description_chars
    # The earlier publication time is the right one: a feed re-stamping an article on update
    # should not make it look newer than it is.
    base.published_at = min(base.published_at, extra.published_at)
    return base


# --------------------------------------------------------------------------- layer 4-5

def _is_cjk(text: str) -> bool:
    """Whether the headline is predominantly CJK, which decides the tokeniser."""
    if not text:
        return False
    cjk = len(_CJK_RE.findall(text))
    return cjk >= 2 and cjk / max(len(text.replace(" ", "")), 1) > 0.3


def content_tokens(title: str) -> frozenset[str]:
    """Topical tokens from a headline. Word-based, or character bigrams for CJK."""
    if _is_cjk(title):
        compact = "".join(_CJK_RE.findall(title))
        return frozenset(compact[i : i + 2] for i in range(len(compact) - 1))
    normalised = normalise_title(title)
    return frozenset(
        token for token in _WORD_RE.findall(normalised)
        if len(token) > 2 and token not in STOPWORDS
    )


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def entities(title: str) -> tuple[frozenset[str], frozenset[str]]:
    """Capitalised runs in a headline, split into multi-word and single-word sets.

    Returns empty sets for CJK, which has no capitalisation; those headlines are grouped on
    bigram overlap alone, at the higher threshold.
    """
    if _is_cjk(title):
        return frozenset(), frozenset()
    found = [m.group(0).strip() for m in _ENTITY_RE.finditer(title)]
    multi = {e for e in found if " " in e and e not in _GENERIC_ENTITIES}
    single = {e for e in found if " " not in e and e not in _GENERIC_ENTITIES and len(e) > 2}
    # A headline in Title Case Like This produces an entity for every word; that is noise.
    if len(single) > 6:
        single = set()
    return frozenset(multi), frozenset(single)


def _entities_agree(
    left_multi: frozenset[str], left_single: frozenset[str],
    right_multi: frozenset[str], right_single: frozenset[str],
) -> bool:
    """Rule 3: a shared named entity, allowing for "Gadi Eisenkot" vs "Eisenkot"."""
    if left_multi & right_multi:
        return True
    if len(left_single & right_single) >= MIN_SHARED_SINGLE_ENTITIES:
        return True
    # A single-word entity on one side that is a component of a multi-word entity on the other.
    for single in left_single:
        if any(single in multi.split() for multi in right_multi):
            return True
    return any(
        single in multi.split() for single in right_single for multi in left_multi
    )


def _same_event(left: Article, right: Article) -> bool:
    if abs((left.published_at - right.published_at).total_seconds()) > TIME_WINDOW_HOURS * 3600:
        return False

    left_cjk, right_cjk = _is_cjk(left.title), _is_cjk(right.title)
    if left_cjk != right_cjk:
        # Cross-script grouping needs translation, which is a later phase and a licence
        # question. Declining is the honest answer, not a missed opportunity hidden in a log.
        return False

    similarity = jaccard(content_tokens(left.title), content_tokens(right.title))
    if left_cjk:
        return similarity >= CJK_SIMILARITY_THRESHOLD
    if similarity < TITLE_SIMILARITY_THRESHOLD:
        return False

    lm, ls = entities(left.title)
    rm, rs = entities(right.title)
    if not (lm or ls) and not (rm or rs):
        # Neither headline names anything. Token overlap alone is not enough: "Markets fall
        # again" and "Markets fall sharply" would merge.
        return similarity >= 0.70
    return _entities_agree(lm, ls, rm, rs)


def cluster_events(articles: list[Article]) -> list[EventCluster]:
    """Groups articles covering the same event, assigning ``event_id`` on each member.

    Union-find over pairs that pass :func:`_same_event`. Candidate pairs are restricted to
    articles sharing at least one content token, which keeps this near-linear on the common
    case instead of comparing every article with every other - GDELT alone supplies thousands
    per run, and the quadratic version is the difference between a second and a minute.
    """
    parent: dict[str, str] = {a.id: a.id for a in articles}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_token: dict[str, list[Article]] = defaultdict(list)
    tokens_of: dict[str, frozenset[str]] = {}
    for article in articles:
        tokens = content_tokens(article.title)
        tokens_of[article.id] = tokens
        for token in tokens:
            by_token[token].append(article)

    compared: set[tuple[str, str]] = set()
    for article in articles:
        candidates = {
            other.id: other
            for token in tokens_of[article.id]
            # A token shared by hundreds of headlines is a stopword this module missed; it
            # generates no information and a great deal of comparison.
            if len(by_token[token]) <= 200
            for other in by_token[token]
            if other.id != article.id
        }
        for other in candidates.values():
            pair = (min(article.id, other.id), max(article.id, other.id))
            if pair in compared:
                continue
            compared.add(pair)
            if _same_event(article, other):
                union(article.id, other.id)

    grouped: dict[str, list[Article]] = defaultdict(list)
    for article in articles:
        grouped[find(article.id)].append(article)

    clusters: list[EventCluster] = []
    for root, members in grouped.items():
        event_id = f"evt_{root}"
        for member in members:
            # A single-article "cluster" is just an article; leaving event_id null says so.
            member.event_id = event_id if len(members) > 1 else None
        if len(members) > 1:
            clusters.append(EventCluster(event_id=event_id, articles=members))
    return clusters
