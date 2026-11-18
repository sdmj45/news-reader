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


class TestChinaDesk:
    """Added 2026-11-15 with the China section."""

    @pytest.mark.parametrize(
        "headline",
        [
            "Xi Jinping reçoit une délégation européenne",
            "Beijing announces new export controls",
            "中国发布新的经济数据",
            "Huawei dévoile un nouveau processeur",
            "Tensions in the Taiwan Strait after naval exercise",
        ],
    )
    def test_china_is_detected(self, headline):
        from app.processors.classifier import classify_text

        _, geographies = classify_text(headline)
        assert Category.CHINA in geographies, headline

    def test_china_outranks_international_for_the_primary_slot(self):
        # An article about Beijing is China news first and world news second. The reverse
        # buried the China desk inside a 400-article INTERNATIONAL pile.
        article = make_article("La Chine et les États-Unis reprennent le dialogue",
                               "https://a.fr/1")
        classify(article)
        assert article.category is Category.CHINA
        assert Category.INTERNATIONAL in article.secondary_categories

    def test_a_french_story_about_china_keeps_china_as_a_tag(self):
        # It is filed under its subject, but the China chip still finds it because the
        # repository matches secondary categories too.
        article = make_article("Xi Jinping rencontre Emmanuel Macron à Pékin", "https://a.fr/1")
        classify(article)
        assert Category.CHINA in [article.category, *article.secondary_categories]

    def test_non_china_international_news_is_not_swept_in(self):
        article = make_article("Washington impose des sanctions à Moscou", "https://a.fr/1")
        classify(article)
        assert Category.CHINA not in [article.category, *article.secondary_categories]


class TestAiIsFiledUnderTechnology:
    """One section, so a reader looking for technology finds the AI news in it."""

    def test_ai_articles_are_primary_technology(self):
        article = make_article("OpenAI publie un nouveau modèle de langage", "https://a.fr/1")
        classify(article)
        assert article.category is Category.TECHNOLOGY

    def test_the_narrower_label_is_kept_as_a_secondary(self):
        article = make_article("OpenAI publie un nouveau modèle de langage", "https://a.fr/1")
        classify(article)
        assert Category.ARTIFICIAL_INTELLIGENCE in article.secondary_categories

    def test_ordinary_technology_is_not_mislabelled_as_ai(self):
        article = make_article("Apple dévoile un nouveau smartphone", "https://a.fr/1")
        classify(article)
        assert article.category is Category.TECHNOLOGY
        assert Category.ARTIFICIAL_INTELLIGENCE not in article.secondary_categories

    def test_a_chinese_ai_story_lands_in_both_desks(self):
        article = make_article("中国发布人工智能新规", "https://a.cn/1")
        classify(article)
        tags = [article.category, *article.secondary_categories]
        assert Category.TECHNOLOGY in tags and Category.CHINA in tags


class TestFrancePolicyTag:
    @pytest.mark.parametrize("headline", [
        "Visa : ce qui change au 1er janvier pour les étudiants étrangers",
        "Titre de séjour : la préfecture de Paris allonge les délais",
        "Plans d’épargne-retraite : ce qui a changé en 2026",
        "Le SMIC augmentera de 2 % au 1er janvier",
        "Impôt sur le revenu : le barème revalorisé dans le projet de loi de finances",
    ])
    def test_rule_changes_in_french_news_are_tagged(self, headline):
        article = make_article(headline, "https://a.fr/1")
        article.country = "FR"
        classify(article)
        assert Category.FRANCE_POLICY in article.secondary_categories

    def test_the_tag_comes_first_so_the_three_tag_cap_cannot_drop_it(self):
        article = make_article("Visa : la Chine, l'Union européenne et la France", "https://a.fr/2")
        article.country = "FR"
        classify(article)
        assert article.secondary_categories[0] is Category.FRANCE_POLICY

    def test_a_foreign_story_is_not_french_policy(self):
        article = make_article("US visa rules tightened for students", "https://a.us/1",
                               language="en")
        article.country = "US"
        classify(article)
        assert Category.FRANCE_POLICY not in article.secondary_categories

    def test_a_foreign_publisher_writing_about_france_is(self):
        article = make_article("France raises the minimum wage: SMIC up 2%", "https://a.uk/1",
                               language="en")
        article.country = "GB"
        classify(article)
        assert Category.FRANCE_POLICY in article.secondary_categories

    @pytest.mark.parametrize("headline", [
        "Amazon Prime : bonne nouvelle pour les abonnés",
        "Nvidia écarte le retour de Jensen Huang",
        # Whole words only: "visa" must not match "visages".
        "Cet homme voit d’étranges visages chez les gens",
    ])
    def test_ordinary_french_news_is_not_tagged(self, headline):
        article = make_article(headline, "https://a.fr/3")
        article.country = "FR"
        classify(article)
        assert Category.FRANCE_POLICY not in article.secondary_categories
