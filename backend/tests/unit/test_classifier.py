"""Category assignment."""

from __future__ import annotations

import pytest

from app.models.article import Category
from app.processors.classifier import classify, classify_text
from tests.conftest import make_article


class TestSubjectDetection:
    @pytest.mark.parametrize(
        "headline,expected",
        [
            ("OpenAI publie un nouveau modèle de langage", Category.ARTIFICIAL_INTELLIGENCE),
            ("Google announces a new quantum chip", Category.TECHNOLOGY),
            ("Inflation slows as the ECB holds interest rates", Category.FINANCE),
            ("Le chômage recule de 0,2 point au troisième trimestre", Category.ECONOMY),
            ("Le gouvernement présente son projet de loi", Category.POLITICS),
            ("Tour de France : victoire au sprint à Bordeaux", Category.SPORTS),
            ("Une étude scientifique sur le génome humain", Category.SCIENCE),
            ("La COP31 s'ouvre sur fond de records de température", Category.ENVIRONMENT),
            ("Nouvelle campagne de vaccination à l'hôpital", Category.HEALTH),
            ("欧盟就人工智能法案达成协议", Category.ARTIFICIAL_INTELLIGENCE),
            ("上海国际电影节开幕", Category.CULTURE),
        ],
    )
    def test_detects_the_subject(self, headline, expected):
        assert classify_text(headline)[0] is expected

    def test_counting_beats_first_match(self):
        # "budget" is an economy term; the headline is about politics, and says so twice.
        headline = "Emmanuel Macron défend le budget devant l'Assemblée nationale"
        assert classify_text(headline)[0] is Category.POLITICS

    def test_abstains_rather_than_guessing(self):
        # A wrong category hides an article from where it belongs and shows it where it does
        # not. OTHER is the honest answer.
        assert classify_text("Something entirely unremarkable happened yesterday")[0] is None


class TestGeography:
    def test_geography_is_secondary_to_subject(self):
        article = make_article("Le chômage recule en France", "https://a.fr/1")
        classify(article)
        assert article.category is Category.ECONOMY
        assert Category.FRANCE in article.secondary_categories

    def test_geography_becomes_primary_when_no_subject_is_found(self):
        article = make_article("Ce qu'il s'est passé à Washington hier", "https://a.fr/1")
        classify(article)
        assert article.category is Category.INTERNATIONAL

    def test_several_geographies_are_kept_as_secondaries(self):
        article = make_article(
            "L'Union européenne et les États-Unis signent un accord commercial",
            "https://a.fr/1",
        )
        classify(article)
        assert Category.EUROPE in [article.category, *article.secondary_categories]
        assert Category.INTERNATIONAL in [article.category, *article.secondary_categories]


class TestSourceDefault:
    def test_a_section_feed_wins_over_keywords(self):
        # lemonde.fr/politique/ really does publish politics; the publisher filed it there.
        article = make_article("Le budget de l'État en débat", "https://a.fr/1")
        classify(article, source_default=Category.POLITICS)
        assert article.category is Category.POLITICS

    def test_the_section_default_does_not_suppress_geography(self):
        article = make_article("Sommet à Bruxelles sur la défense", "https://a.fr/1")
        classify(article, source_default=Category.POLITICS)
        assert Category.EUROPE in article.secondary_categories

    def test_other_as_a_default_is_ignored(self):
        article = make_article("Victoire au Tour de France", "https://a.fr/1")
        classify(article, source_default=Category.OTHER)
        assert article.category is Category.SPORTS

    def test_primary_never_repeats_in_secondaries(self):
        article = make_article("Élections en France : le scrutin de dimanche", "https://a.fr/1")
        classify(article)
        assert article.category not in article.secondary_categories

    def test_secondaries_are_capped(self):
        article = make_article(
            "France, Europe, Chine, Russie et États-Unis au sommet de Washington",
            "https://a.fr/1",
        )
        classify(article)
        assert len(article.secondary_categories) <= 3
