from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import TestCase
from rest_framework.test import APIClient

from news.models import Article, Story
from news.services.entity_extractor import extract_entities
from news.services.story_builder import create_or_assign_story
from news.services.story_matcher import evaluate_pair, group_articles

T0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


def fake(title, source, days=0.0):
    return SimpleNamespace(
        pk=None, title=title, source=source,
        published_at=T0 + timedelta(days=days),
    )


class EntityExtractionTests(TestCase):
    def test_no_substring_false_positives(self):
        self.assertEqual(extract_entities("Advances in speech recognition"), set())
        self.assertEqual(extract_entities("Colorado builds new data center"), set())
        self.assertEqual(extract_entities("Devine Capital invests in AI"), set())

    def test_model_names_do_not_swallow_next_word(self):
        self.assertEqual(extract_entities("GPT-5 is now available"), {"gpt-5"})
        self.assertEqual(extract_entities("Gemini 2.5 Pro launches"), {"gemini-2.5"})

    def test_generic_orgs_are_not_entities(self):
        self.assertEqual(extract_entities("OpenAI and Google announce things"), set())


class MatcherTests(TestCase):
    """Pairs that must NOT merge (the incidents you hit) and ones that must."""

    def assertSplit(self, a, b):
        self.assertFalse(evaluate_pair(a, b).matched, f"{a.title} | {b.title}")

    def assertMerge(self, a, b):
        self.assertTrue(evaluate_pair(a, b).matched, f"{a.title} | {b.title}")

    def test_customer_stories_sharing_openai_stay_separate(self):
        self.assertSplit(
            fake("How Radisson Hotels uses OpenAI to transform guest service", "OpenAI"),
            fake("How Jump Trading uses OpenAI for research", "OpenAI"))
        self.assertSplit(
            fake("Oracle scales AI agents with OpenAI", "OpenAI"),
            fake("Atlassian builds with OpenAI", "OpenAI"))

    def test_short_title_does_not_match_everything(self):
        self.assertSplit(fake("OpenAI launches new image model", "OpenAI"),
                         fake("OpenAI", "OpenAI"))

    def test_same_title_far_apart_in_time_is_not_merged(self):
        self.assertSplit(fake("Gemini 2.5 Pro launches", "Google DeepMind"),
                         fake("Gemini 2.5 Pro launches", "Google DeepMind", 20))

    def test_missing_dates_never_merge(self):
        a = fake("Gemini 2.5 Pro launches", "A")
        b = fake("Gemini 2.5 Pro launches", "B")
        b.published_at = None
        self.assertSplit(a, b)

    def test_cross_source_same_event_merges(self):
        self.assertMerge(
            fake("DeepMind unveils AlphaGenome to read DNA", "Google DeepMind"),
            fake("AlphaGenome: DeepMind's new DNA model", "MIT Technology Review", 1))
        self.assertMerge(
            fake("Perplexity acquires Devin maker Cognition", "TechCrunch"),
            fake("Cognition acquired by Perplexity", "The Verge", 0.2))

    def test_same_source_launch_posts_merge(self):
        self.assertMerge(fake("Introducing GPT-5", "OpenAI"),
                         fake("Introducing GPT-5 for developers", "OpenAI"))

    def test_group_articles_clusters_correctly(self):
        items = [
            fake("Introducing GPT-5", "OpenAI"),
            fake("How Radisson Hotels uses OpenAI to transform guest service", "OpenAI", 0.1),
            fake("GPT-5 is here: what developers need to know", "The Verge", 0.5),
            fake("How Jump Trading uses OpenAI for research", "OpenAI", 0.6),
        ]
        sizes = sorted(len(g) for g in group_articles(items))
        self.assertEqual(sizes, [1, 1, 2])


class RealDataRegressionTests(TestCase):
    """Titles taken from your real regroup_stories output."""

    def groups(self, rows):
        items = [fake(t, src, d) for t, src, d in rows]
        return sorted(sorted(a.title for a in g) for g in group_articles(items))

    def test_gpt5_launch_group_excludes_customer_story(self):
        result = self.groups([
            ("Introducing GPT-5", "OpenAI", 0),
            ("Introducing GPT-5 for developers", "OpenAI", 0),
            ("GPT-5 and the new era of work", "OpenAI", 0),
            ("How Amgen uses GPT-5", "OpenAI", 0),
        ])
        self.assertIn(["How Amgen uses GPT-5"], result)

    def test_templated_chatgpt_posts_stay_separate(self):
        result = self.groups([
            ("Learn ChatGPT workflows for sales teams", "OpenAI", 0),
            ("Learn ChatGPT workflows for finance teams", "OpenAI", 0),
            ("ChatGPT for operations teams", "OpenAI", 0),
            ("ChatGPT for customer success teams", "OpenAI", 0),
            ("ChatGPT for marketing teams", "OpenAI", 0),
            ("Data science workflows with ChatGPT Work", "OpenAI", 0),
            ("Sales workflows with ChatGPT Work", "OpenAI", 0),
        ])
        self.assertTrue(all(len(g) == 1 for g in result), result)

    def test_true_duplicates_and_launch_companions_merge(self):
        for a, b in [
            ("GPT-4", "GPT-4"),
            ("Introducing ChatGPT agent", "ChatGPT agent System Card"),
            ("Sora 2 is here", "Sora 2 System Card"),
            ("A new era of intelligence with Gemini 3", "Start building with Gemini 3"),
            ("Research with ChatGPT", "ChatGPT for research"),
            ("Safety overview: GPT-6 Astra", "GPT-6 Astra: A new generation of intelligence"),
        ]:
            src = "Google DeepMind" if "Gemini" in a else "OpenAI"
            with self.subTest(a=a):
                self.assertEqual(len(self.groups([(a, src, 0), (b, src, 0)])), 1)

    def test_cross_source_paraphrases_merge(self):
        self.assertEqual(len(self.groups([
            ("Anthropic's AI gave Philadelphia police a fake tip about an unsolved homicide", "TechCrunch", 0),
            ("An Anthropic AI model sent a false homicide tip to Philadelphia police", "The Verge", 0.3),
        ])), 1)

    def test_roundup_headline_is_not_merged_with_single_topic_story(self):
        # Deliberate: favour two cards over one contaminated summary.
        self.assertEqual(len(self.groups([
            ("Amazon and others are done keeping data center deals secret. Is it enough to build trust?", "MIT Technology Review", 0),
            ("Amazon drops data center NDAs, and AI agents want your credit card", "The Verge", 0.2),
        ])), 2)

    def test_generic_shared_words_do_not_merge_different_models(self):
        self.assertEqual(len(self.groups([
            ("EmbeddingGemma 2: an open, lightweight multimodal embedding model", "Google DeepMind", 0),
            ("Multimodal open d1 decision models for the edge", "Hugging Face", 1),
        ])), 2)

    def test_unrelated_cross_source_stories_stay_separate(self):
        self.assertEqual(len(self.groups([
            ("The maker of non-text AI model Jev valued at $7.5B just weeks after launch", "TechCrunch", 0),
            ("Nikon microscopic video competition winner disqualified for using generative AI", "The Verge", 0.1),
            ("Danu Robotics' fight to build a better recycling robot", "MIT Technology Review", 0.2),
            ("We can't help treating AI like it's human. But should we?", "MIT Technology Review", 0.2),
            ("Amazon drops data center NDAs, and AI agents want your credit card", "The Verge", 0.3),
        ])), 5)


class StoryBuilderTests(TestCase):
    def _article(self, title, source, days, url):
        return Article.objects.create(
            title=title, source=source, url=url,
            published_at=T0 + timedelta(days=days),
        )

    def test_new_coverage_marks_story_for_resummary(self):
        a = self._article("Perplexity acquires Devin maker Cognition", "TechCrunch", 0, "https://x.test/1")
        story, created, _ = create_or_assign_story(a)
        self.assertTrue(created)

        Story.objects.filter(pk=story.pk).update(
            needs_ai_update=False, summary="done", ai_failures=2)

        b = self._article("Cognition acquired by Perplexity", "The Verge", 0.2, "https://x.test/2")
        story2, created2, _ = create_or_assign_story(b)

        self.assertFalse(created2)
        self.assertEqual(story.pk, story2.pk)
        story.refresh_from_db()
        self.assertTrue(story.needs_ai_update)   # old code left this False
        self.assertEqual(story.ai_failures, 0)

    def test_unrelated_articles_get_their_own_story(self):
        a = self._article("How Radisson Hotels uses OpenAI", "OpenAI", 0, "https://x.test/3")
        b = self._article("How Jump Trading uses OpenAI", "OpenAI", 0.1, "https://x.test/4")
        s1, _, _ = create_or_assign_story(a)
        s2, _, _ = create_or_assign_story(b)
        self.assertNotEqual(s1.pk, s2.pk)


class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        now = datetime.now(timezone.utc)
        specs = [  # (title, importance, hours ago)
            ("Old but huge", 95, 24 * 10),
            ("Fresh and decent", 70, 2),
            ("Fresh but minor", 20, 1),
        ]
        for i, (title, importance, hours) in enumerate(specs):
            story = Story.objects.create(
                title=title, summary="s", why_it_matters="w", category="Models",
                importance_score=importance, needs_ai_update=False,
                first_published_at=now - timedelta(hours=hours))
            Article.objects.create(
                title=title, source="OpenAI", url=f"https://api.test/{i}",
                published_at=now - timedelta(hours=hours), story=story)

    def titles(self, query=""):
        response = self.client.get(f"/api/feed/{query}")
        self.assertEqual(response.status_code, 200)
        return [s["title"] for s in response.json()["results"]]

    def test_feed_default_is_ranked(self):
        self.assertEqual(self.titles()[0], "Fresh and decent")

    def test_feed_sort_param_is_honoured(self):
        # The old FeedView ignored ?sort= completely.
        self.assertEqual(self.titles("?sort=latest")[0], "Fresh but minor")
        self.assertEqual(self.titles("?sort=important")[0], "Old but huge")

    def test_noise_stories_are_hidden_from_feed_and_trending(self):
        story = Story.objects.create(
            title="Ticket discounts for a conference", summary="s", why_it_matters="w",
            category="Other", importance_score=3, needs_ai_update=False,
            first_published_at=datetime.now(timezone.utc))
        Article.objects.create(
            title=story.title, source="TechCrunch", url="https://api.test/noise",
            published_at=datetime.now(timezone.utc), story=story)
        self.assertNotIn(story.title, self.titles())
        trending = self.client.get("/api/trending/")
        self.assertEqual(trending.status_code, 200)
        self.assertNotIn(story.title, [s["title"] for s in trending.json()["results"]])

    def test_feed_page_query_count_is_constant(self):
        with self.assertNumQueries(3):   # count, stories, prefetch
            self.client.get("/api/feed/")

    def test_source_filter_does_not_break_counts(self):
        response = self.client.get("/api/feed/?source=openai")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["article_count"], 1)

    def test_bad_params_return_400(self):
        self.assertEqual(self.client.get("/api/stories/?from=nope").status_code, 400)
        self.assertEqual(self.client.get("/api/feed/?page=abc").status_code, 400)
        self.assertEqual(self.client.get("/api/stories/?min_importance=x").status_code, 400)
        self.assertEqual(self.client.get("/api/stories/999999/").status_code, 404)

    def test_detail_lists_articles(self):
        story = Story.objects.first()
        data = self.client.get(f"/api/stories/{story.pk}/").json()
        self.assertEqual(len(data["articles"]), 1)
        self.assertIn("latest_article_at", data)


class FreeTierProcessingTests(TestCase):
    """Batching, quota handling - Gemini is mocked, no network."""

    def _story(self, title, n):
        story = Story.objects.create(title=title, needs_ai_update=True,
                                     first_published_at=datetime.now(timezone.utc))
        Article.objects.create(
            title=title, source="OpenAI", url=f"https://fts.test/{n}",
            published_at=datetime.now(timezone.utc), story=story)
        return story

    def _entry(self, number, score=60):
        return {"story": number, "headline": f"Headline {number}", "summary": "s",
                "why_it_matters": "w", "category": "Models", "importance_score": score}

    def test_one_request_summarises_many_stories(self):
        from unittest import mock
        from news.services.story_ai_processor import process_batch
        stories = [self._story(f"Story {i}", i) for i in range(5)]
        fake_reply = {"stories": [self._entry(i + 1) for i in range(5)]}
        with mock.patch("news.services.story_ai_processor.generate_json",
                        return_value=fake_reply) as gen:
            results = process_batch(stories)
        self.assertEqual(gen.call_count, 1)
        self.assertTrue(all(v is None for v in results.values()))
        self.assertFalse(Story.objects.filter(needs_ai_update=True).exists())

    def test_bad_entry_only_fails_that_story(self):
        from unittest import mock
        from news.services.story_ai_processor import process_batch
        stories = [self._story("A", 10), self._story("B", 11)]
        reply = {"stories": [self._entry(1), {**self._entry(2), "category": "Nope"}]}
        with mock.patch("news.services.story_ai_processor.generate_json", return_value=reply):
            results = process_batch(stories)
        self.assertIsNone(results[stories[0].pk])
        self.assertIsInstance(results[stories[1].pk], ValueError)

    def test_quota_error_does_not_count_as_failure(self):
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        from news.services.gemini_client import QuotaExceeded
        story = self._story("Quota story", 20)
        with mock.patch("news.management.commands.process_stories.process_batch",
                        side_effect=QuotaExceeded("429 RESOURCE_EXHAUSTED")):
            call_command("process_stories", delay=0, stdout=StringIO(), stderr=StringIO())
        story.refresh_from_db()
        self.assertEqual(story.ai_failures, 0)     # NOT parked
        self.assertTrue(story.needs_ai_update)     # still queued


class GeminiBudgetTests(TestCase):
    """Daily budget + model fallback, with the Gemini SDK mocked."""

    def setUp(self):
        from unittest import mock
        from news.services import gemini_client as gc
        self.gc = gc
        patches = [
            mock.patch.object(gc, "_pace", lambda model: None),
            mock.patch.object(gc.time, "sleep", lambda s: None),
            mock.patch.object(gc, "DAILY_LIMIT", 2),
            mock.patch.object(gc, "MODELS", ["model-a", "model-b"]),
            mock.patch.dict(gc._COOLDOWN_UNTIL, {}, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _client(self, calls, fail_models=()):
        from types import SimpleNamespace

        def create(model, input, timeout):
            calls.append(model)
            if model in fail_models:
                raise RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDay")
            return SimpleNamespace(output_text='{"ok": true}')

        return SimpleNamespace(interactions=SimpleNamespace(create=create))

    def test_stops_at_local_daily_budget_without_calling_google(self):
        from unittest import mock
        calls = []
        with mock.patch.object(self.gc, "get_client", return_value=self._client(calls)):
            for _ in range(4):                    # 2 models x budget 2
                self.gc.generate_json("p")
            with self.assertRaises(self.gc.QuotaExceeded):
                self.gc.generate_json("p")        # 5th: everything used up
        self.assertEqual(len(calls), 4)           # the 5th never reached Google
        self.assertEqual(self.gc.requests_today("model-a"), 2)

    def test_falls_back_to_next_model_on_daily_429(self):
        from unittest import mock
        calls = []
        client = self._client(calls, fail_models={"model-a"})
        with mock.patch.object(self.gc, "get_client", return_value=client):
            self.assertEqual(self.gc.generate_json("p"), {"ok": True})
        self.assertEqual(calls, ["model-a", "model-b"])
        self.assertEqual(self.gc.requests_today("model-a"), 2)   # marked used up

    def test_wrong_model_id_is_skipped_not_fatal(self):
        from types import SimpleNamespace
        from unittest import mock
        calls = []

        def create(model, input, timeout):
            calls.append(model)
            if model == "model-a":
                raise RuntimeError("404 NOT_FOUND: models/model-a is not found")
            return SimpleNamespace(output_text='{"ok": true}')

        client = SimpleNamespace(interactions=SimpleNamespace(create=create))
        with mock.patch.object(self.gc, "get_client", return_value=client):
            self.assertEqual(self.gc.generate_json("p"), {"ok": True})
        self.assertEqual(calls, ["model-a", "model-b"])

    def test_model_limits_can_be_set_per_model(self):
        order, limits = self.gc._parse_models("a:18:5, b:480:15 ,c")
        self.assertEqual(order, ["a", "b", "c"])
        self.assertEqual(limits["b"], (480, 15))
        self.assertEqual(limits["c"], (self.gc.DAILY_LIMIT, self.gc.RPM_LIMIT))

    def test_project_429_is_not_retried_and_model_is_skipped_afterwards(self):
        from types import SimpleNamespace
        from unittest import mock
        calls = []

        def create(model, input, timeout):
            calls.append(model)
            if model == "model-a":
                raise RuntimeError("429 Your project has exceeded a quota.")
            return SimpleNamespace(output_text='{"ok": true}')

        client = SimpleNamespace(interactions=SimpleNamespace(create=create))
        with mock.patch.object(self.gc, "get_client", return_value=client), \
             mock.patch.object(self.gc, "DAILY_LIMIT", 10):
            self.gc.generate_json("p")
            self.gc.generate_json("p")
            self.gc.generate_json("p")
        # model-a was tried exactly ONCE: no retry, not repeated on later batches
        self.assertEqual(calls, ["model-a", "model-b", "model-b", "model-b"])

    def test_503_overload_skips_model_without_retry_and_is_not_a_story_failure(self):
        from types import SimpleNamespace
        from unittest import mock
        calls = []

        def create(model, input, timeout):
            calls.append(model)
            if model == "model-a":
                raise RuntimeError("503 gemini is currently experiencing high demand")
            return SimpleNamespace(output_text='{"ok": true}')

        client = SimpleNamespace(interactions=SimpleNamespace(create=create))
        with mock.patch.object(self.gc, "get_client", return_value=client), \
             mock.patch.object(self.gc, "DAILY_LIMIT", 10):
            self.assertEqual(self.gc.generate_json("p"), {"ok": True})
            self.gc.generate_json("p")
        self.assertEqual(calls, ["model-a", "model-b", "model-b"])   # a: one try, then cooldown
        self.assertTrue(issubclass(self.gc.ServiceBusy, self.gc.QuotaExceeded))

    def test_all_models_busy_stops_run_and_does_not_count_story_failures(self):
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        story = Story.objects.create(title="Busy day", needs_ai_update=True,
                                     first_published_at=datetime.now(timezone.utc))
        Article.objects.create(title="Busy day", source="X", url="https://busy.test/1",
                               published_at=datetime.now(timezone.utc), story=story)
        with mock.patch("news.management.commands.process_stories.process_batch",
                        side_effect=self.gc.ServiceBusy("503 high demand")):
            call_command("process_stories", stdout=StringIO(), stderr=StringIO())
        story.refresh_from_db()
        self.assertEqual(story.ai_failures, 0)
        self.assertTrue(story.needs_ai_update)


# =====================================================================
# Batch: trust & correctness (matcher, AI validation, undated, regroup)
# =====================================================================
class MatcherTrustTests(TestCase):
    def test_two_company_case_studies_with_same_model_do_not_merge(self):
        self.assertFalse(evaluate_pair(
            fake("How Amgen uses GPT-5 for drug discovery", "OpenAI"),
            fake("How AstraZeneca uses GPT-5 for drug discovery", "OpenAI")).matched)
        # also across sources
        self.assertFalse(evaluate_pair(
            fake("How Amgen uses GPT-5 for drug discovery", "OpenAI"),
            fake("How AstraZeneca uses GPT-5 for drug discovery", "TechCrunch")).matched)

    def test_company_adopts_model_stories_do_not_merge(self):
        self.assertFalse(evaluate_pair(
            fake("Albertsons adopts ChatGPT Enterprise for retail operations", "OpenAI"),
            fake("Oracle adopts ChatGPT and Codex to accelerate workflows", "OpenAI")).matched)

    def test_chain_a_b_c_does_not_collapse_into_one_story(self):
        a = fake("Gemini 3 Pro launches with new reasoning mode", "TechCrunch", 0)
        b = fake("Gemini 3 Pro launches with adaptive reasoning mode and thinking budget controls",
                 "The Verge", 2)
        c = fake("Adaptive reasoning mode with thinking budget controls rolls out to Workspace users",
                 "MIT Technology Review", 4)
        # A~B and B~C individually, but A and C are different developments
        self.assertTrue(evaluate_pair(a, b).matched)
        self.assertTrue(evaluate_pair(b, c).matched)
        self.assertFalse(evaluate_pair(a, c).matched)
        for order in ([a, b, c], [c, b, a], [b, a, c]):
            sizes = sorted(len(g) for g in group_articles(order))
            self.assertEqual(sizes, [1, 2], f"order {[x.source for x in order]}")

    def test_time_window_boundary(self):
        self.assertTrue(evaluate_pair(
            fake("Falcon ASR released", "Hugging Face", 0),
            fake("Falcon ASR released", "The Verge", 4.0)).matched)
        self.assertFalse(evaluate_pair(
            fake("Falcon ASR released", "Hugging Face", 0),
            fake("Falcon ASR released", "The Verge", 4.2)).matched)

    def test_undated_articles_are_never_grouped(self):
        dated = fake("Falcon ASR released", "Hugging Face", 0)
        undated = fake("Falcon ASR released", "The Verge", 0)
        undated.published_at = None
        self.assertFalse(evaluate_pair(dated, undated).matched)
        self.assertEqual(len(group_articles([dated, undated])), 1)   # undated skipped

    # ---- rules added from real near-duplicate output --------------------
    @staticmethod
    def _filler(n):
        return [fake(f"Zorblax{j} unveils quantum{j} widget{j} platform", "Filler", 30 + j)
                for j in range(n)]

    def _sizes(self, rows, filler=0):
        items = [fake(t, src, d) for t, src, d in rows] + self._filler(filler)
        return sorted(len(g) for g in group_articles(items) if g[0].source != "Filler")

    def test_same_publisher_posts_about_one_model_version_merge(self):
        # real DeepMind titles: three posts for one launch (Rule C2)
        self.assertEqual(self._sizes([
            ("Gemini 4 Argon for Robotics", "Google DeepMind", 0),
            ("Gemini 4 Argon: Built to solve your hardest problems", "Google DeepMind", 0),
            ("Developing Gemini 4 Argon responsibly and safely", "Google DeepMind", 0.1),
        ]), [3])

    def test_different_model_versions_from_same_publisher_stay_separate(self):
        self.assertEqual(self._sizes([
            ("Introducing GPT-5.1 for coding", "OpenAI", 0),
            ("Introducing GPT-5.2 for research agents", "OpenAI", 0),
        ]), [1, 1])

    def test_rare_shared_words_merge_cross_source_when_corpus_is_large(self):
        rows = [
            ("Bluesky’s AI tool now lets you make games and apps to share on social", "The Verge", 0),
            ("Bluesky expands its AI-powered Attie app to let anyone build websites, games, and more",
             "TechCrunch", 0.1),
        ]
        self.assertEqual(self._sizes(rows, filler=120), [2])
        # a small corpus cannot judge rarity, so the rule stays OFF
        self.assertEqual(self._sizes(rows, filler=0), [1, 1])

    def test_everyday_shared_words_never_merge_even_with_large_corpus(self):
        for a, b in [
            ("Anthropic says its workforce has become less junior and is spending more time in meetings",
             "Franchisee reconciles cash in 94% less time with ChatGPT Work"),
            ("Microsoft says AI agents are like insider threats as ‘frontier models can’t be trusted’",
             "We can't help treating AI like it's human. But should we?"),
            ("Floqer’s AI agents research sales prospects so teams don’t have to",
             "Friends don’t let friends feed their data to AI agents"),
            ("Democrats think cracking down on AI could give them an edge",
             "JB Pritzker thinks AI could help us live to 100 — or threaten us like nukes"),
        ]:
            with self.subTest(a=a[:40]):
                self.assertEqual(
                    self._sizes([(a, "TechCrunch", 0), (b, "The Verge", 0.1)], filler=120),
                    [1, 1])

    def test_unrelated_same_source_topics_stay_separate(self):
        self.assertEqual(self._sizes([
            ("Replit makes OpenAI its default over Anthropic, CEO says", "TechCrunch", 0),
            ("Replit’s CEO says the future of work is the ‘self-driving company’", "TechCrunch", 0),
            ("YouTube Music launches new labels as AI-generated music floods streaming platforms",
             "TechCrunch", 0),
            ("Deezer will soon let you filter out AI-generated music", "TechCrunch", 0),
        ], filler=120), [1, 1, 1, 1])

    def test_invisible_characters_are_removed_from_titles(self):
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        entry = {"title": "OpenAI acquires startup Orchestra Bio\u2060 to beef up",
                 "link": "https://t.test/zw", "summary": "s",
                 "published_parsed": datetime(2026, 10, 20, 9).timetuple()}
        with mock.patch("news.management.commands.collect_news.RSS_SOURCES",
                        [{"name": "X", "url": "x", "kind": "press"}]), \
             mock.patch("news.management.commands.collect_news.fetch_feed", return_value=[entry]):
            call_command("collect_news", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(Article.objects.get(url="https://t.test/zw").title,
                         "OpenAI acquires startup Orchestra Bio to beef up")


class AIValidationTests(TestCase):
    def _story(self, n_articles=1, summary=""):
        story = Story.objects.create(
            title="Original", summary=summary, needs_ai_update=True,
            first_published_at=datetime.now(timezone.utc))
        for i in range(n_articles):
            Article.objects.create(
                title=f"A{i}", source=f"S{i}", url=f"https://v.test/{story.pk}/{i}",
                published_at=datetime.now(timezone.utc), story=story)
        return story

    def _good(self, **over):
        entry = {"story": 1, "headline": "New Headline", "summary": "A summary.",
                 "why_it_matters": "It matters.", "category": "Models",
                 "importance_score": 50}
        entry.update(over)
        return entry

    def _run(self, story, entry):
        from unittest import mock
        from news.services.story_ai_processor import process_batch
        with mock.patch("news.services.story_ai_processor.generate_json",
                        return_value={"stories": [entry]}):
            return process_batch([story])[story.pk]

    def test_multi_article_story_without_same_event_is_rejected(self):
        story = self._story(2)
        error = self._run(story, self._good())               # no same_event at all
        self.assertIsInstance(error, ValueError)
        story.refresh_from_db()
        self.assertTrue(story.needs_ai_update)
        self.assertEqual(story.summary, "")                  # nothing saved

    def test_same_event_must_be_a_real_boolean(self):
        for bad in ("true", "yes", 1, None, [], "maybe"):
            story = self._story(2)
            error = self._run(story, self._good(same_event=bad))
            self.assertIsInstance(error, ValueError, f"accepted {bad!r}")
            story.refresh_from_db()
            self.assertEqual(story.summary, "")

    def test_same_event_false_flags_story_for_review(self):
        from news.services.story_ai_processor import IncoherentStory
        story = self._story(2)
        error = self._run(story, self._good(same_event=False))
        self.assertIsInstance(error, IncoherentStory)
        self.assertEqual(Article.objects.filter(story=story).count(), 2)  # nothing lost

    def test_same_event_true_is_saved(self):
        story = self._story(2)
        self.assertIsNone(self._run(story, self._good(same_event=True)))
        story.refresh_from_db()
        self.assertEqual(story.summary, "A summary.")
        self.assertFalse(story.needs_ai_update)

    def test_single_article_story_does_not_need_same_event(self):
        story = self._story(1)
        self.assertIsNone(self._run(story, self._good()))

    def test_bad_output_never_overwrites_a_good_summary(self):
        bad_entries = [
            self._good(summary=""),
            self._good(summary="   "),
            self._good(summary=123),
            self._good(why_it_matters=""),
            self._good(category="Gossip"),
            self._good(importance_score=101),
            self._good(importance_score=-1),
            self._good(importance_score="high"),
            self._good(importance_score=True),
            self._good(importance_score=float("nan")),
            self._good(summary="x" * 5000),
        ]
        for entry in bad_entries:
            story = self._story(1, summary="GOOD EXISTING SUMMARY")
            error = self._run(story, entry)
            self.assertIsInstance(error, ValueError, f"accepted {entry}")
            story.refresh_from_db()
            self.assertEqual(story.summary, "GOOD EXISTING SUMMARY")

    def test_batch_results_map_to_the_right_stories(self):
        from unittest import mock
        from news.services.story_ai_processor import process_batch
        s1, s2, s3 = self._story(1), self._story(1), self._story(1)
        reply = {"stories": [                      # deliberately out of order
            self._good(story=3, headline="Third", summary="three"),
            self._good(story=1, headline="First", summary="one"),
            self._good(story=2, headline="Second", summary="two"),
        ]}
        with mock.patch("news.services.story_ai_processor.generate_json", return_value=reply):
            results = process_batch([s1, s2, s3])
        self.assertTrue(all(v is None for v in results.values()))
        for story, summary in ((s1, "one"), (s2, "two"), (s3, "three")):
            story.refresh_from_db()
            self.assertEqual(story.summary, summary)

    def test_prompt_schema_includes_same_event_only_when_needed(self):
        from news.services.story_ai_processor import _build_prompt
        self.assertIn('"same_event"', _build_prompt(["=== STORY 1 ==="], {1}))
        self.assertNotIn('"same_event"', _build_prompt(["=== STORY 1 ==="], set()))

    def test_off_topic_story_is_pushed_below_the_feed_threshold(self):
        from news.services.feed_scoring import MIN_FEED_IMPORTANCE
        story = self._story(1)
        self.assertIsNone(self._run(story, self._good(importance_score=70, ai_related=False)))
        story.refresh_from_db()
        self.assertLess(story.importance_score, MIN_FEED_IMPORTANCE)

    def test_missing_ai_related_flag_changes_nothing(self):
        story = self._story(1)
        self.assertIsNone(self._run(story, self._good(importance_score=70)))
        story.refresh_from_db()
        self.assertEqual(story.importance_score, 70)



class UndatedArticleTests(TestCase):
    RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
    {items}</channel></rss>"""

    def _fetch(self, items_xml):
        from unittest import mock
        from news.services import rss_collector as rc
        response = mock.Mock(content=self.RSS.format(items=items_xml).encode())
        response.raise_for_status = lambda: None
        with mock.patch.object(rc.requests, "get", return_value=response):
            return rc.fetch_feed({"name": "TestFeed", "url": "https://t.test/feed"})

    def test_undated_entries_are_kept_but_capped(self):
        from news.services.rss_collector import UNDATED_LIMIT
        now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        items = "".join(
            f"<item><title>Undated {i}</title><link>https://t.test/u{i}</link></item>"
            for i in range(UNDATED_LIMIT + 5))
        items += (f"<item><title>Dated</title><link>https://t.test/d</link>"
                  f"<pubDate>{now}</pubDate></item>")
        entries = self._fetch(items)
        self.assertEqual(len(entries), UNDATED_LIMIT + 1)

    def test_collect_saves_undated_without_inventing_a_date(self):
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        entry = {"title": "No date here", "link": "https://t.test/nodate", "summary": "s"}
        with mock.patch("news.management.commands.collect_news.RSS_SOURCES",
                        [{"name": "TestFeed", "url": "x", "kind": "press"}]), \
             mock.patch("news.management.commands.collect_news.fetch_feed",
                        return_value=[entry]):
            call_command("collect_news", stdout=StringIO(), stderr=StringIO())
        article = Article.objects.get(url="https://t.test/nodate")
        self.assertIsNone(article.published_at)               # NOT invented

    def test_undated_article_gets_own_story_and_is_not_processed_or_shown(self):
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        article = Article.objects.create(
            title="Undated", source="X", url="https://t.test/undated", published_at=None)
        story, created, _ = create_or_assign_story(article)
        self.assertTrue(created)
        self.assertIsNone(story.first_published_at)
        with mock.patch("news.management.commands.process_stories.process_batch") as pb:
            call_command("process_stories", stdout=StringIO(), stderr=StringIO())
        pb.assert_not_called()                                # no Gemini quota spent

    def test_later_date_is_filled_in_without_inventing_one(self):
        from io import StringIO
        from unittest import mock
        from django.core.management import call_command
        article = Article.objects.create(
            title="Late date", source="X", url="https://t.test/late", published_at=None)
        story, _, _ = create_or_assign_story(article)
        real_date = datetime(2026, 10, 2, 9, tzinfo=timezone.utc)
        entry = {"title": "Late date", "link": "https://t.test/late",
                 "published_parsed": real_date.timetuple()}
        with mock.patch("news.management.commands.collect_news.RSS_SOURCES",
                        [{"name": "X", "url": "x", "kind": "press"}]), \
             mock.patch("news.management.commands.collect_news.fetch_feed",
                        return_value=[entry]):
            call_command("collect_news", stdout=StringIO(), stderr=StringIO())
        article.refresh_from_db(); story.refresh_from_db()
        self.assertEqual(article.published_at, real_date)
        self.assertEqual(story.first_published_at, real_date)


class RegroupSafetyTests(TestCase):
    def setUp(self):
        d = lambda days: T0 + timedelta(days=days)
        # S1: a correct group (launch + developer post) that also holds an undated article
        self.s1 = Story.objects.create(title="GPT-5", summary="KEEP ME",
                                       needs_ai_update=False, first_published_at=d(0))
        self.a1 = Article.objects.create(title="Introducing GPT-5", source="OpenAI",
                                         url="https://r.test/1", published_at=d(0), story=self.s1)
        self.a2 = Article.objects.create(title="Introducing GPT-5 for developers", source="OpenAI",
                                         url="https://r.test/2", published_at=d(0.1), story=self.s1)
        self.u1 = Article.objects.create(title="Mystery post", source="OpenAI",
                                         url="https://r.test/3", published_at=None, story=self.s1)
        # S2: two unrelated customer stories wrongly merged
        self.s2 = Story.objects.create(title="Merged", summary="WRONG SUMMARY",
                                       needs_ai_update=False, first_published_at=d(1))
        self.b1 = Article.objects.create(title="How Radisson Hotels uses OpenAI to transform guest service",
                                         source="OpenAI", url="https://r.test/4", published_at=d(1), story=self.s2)
        self.b2 = Article.objects.create(title="How Jump Trading uses OpenAI for research",
                                         source="OpenAI", url="https://r.test/5", published_at=d(1.1), story=self.s2)
        # an undated article that is in no story at all
        self.u2 = Article.objects.create(title="Orphan undated", source="X",
                                         url="https://r.test/6", published_at=None, story=None)

    def snapshot(self):
        return (Story.objects.count(),
                {a.id: a.story_id for a in Article.objects.all()},
                {s.id: (s.summary, s.needs_ai_update) for s in Story.objects.all()})

    def run_cmd(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("regroup_stories", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_dry_run_changes_nothing_and_reports_undated(self):
        before = self.snapshot()
        report = self.run_cmd()
        self.assertEqual(self.snapshot(), before)
        self.assertIn("DRY RUN", report)
        self.assertIn("2 undated", report)
        self.assertIn("Accounting check", report)

    def test_apply_preserves_every_article_and_accounts_for_undated(self):
        total = Article.objects.count()
        self.run_cmd("--apply")
        self.assertEqual(Article.objects.count(), total)
        self.assertFalse(Article.objects.filter(story__isnull=True).exists())

        # the wrongly merged story is split into two separate stories
        self.b1.refresh_from_db(); self.b2.refresh_from_db()
        self.assertNotEqual(self.b1.story_id, self.b2.story_id)
        self.assertFalse(Story.objects.filter(id=self.s2.id).exists())

        # undated articles: own story, no invented date, not mixed with dated ones
        for u in (self.u1, self.u2):
            u.refresh_from_db()
            self.assertIsNone(u.published_at)
            self.assertIsNone(u.story.first_published_at)
            self.assertEqual(u.story.articles.count(), 1)

    def test_unchanged_group_keeps_summary_changed_group_is_flagged(self):
        self.run_cmd("--apply")
        self.s1.refresh_from_db()
        self.a1.refresh_from_db(); self.a2.refresh_from_db()
        self.assertEqual(self.a1.story_id, self.s1.id)
        self.assertEqual(self.a2.story_id, self.s1.id)
        self.assertEqual(self.s1.summary, "KEEP ME")          # group unchanged: kept
        self.assertTrue(self.s1.needs_ai_update)              # lost an undated member
        # newly created stories need AI
        self.assertTrue(Story.objects.exclude(id=self.s1.id).filter(needs_ai_update=True).exists())

    def test_apply_is_atomic_on_failure(self):
        from unittest import mock
        before = self.snapshot()
        real_create = Story.objects.create
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real_create(*args, **kwargs)

        with mock.patch.object(Story.objects, "create", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                self.run_cmd("--apply")
        self.assertEqual(self.snapshot(), before)             # nothing half-applied

    def test_second_apply_is_a_no_op(self):
        self.run_cmd("--apply")
        after_first = self.snapshot()
        self.run_cmd("--apply")
        self.assertEqual(self.snapshot()[0], after_first[0])


class NearDuplicateToolTests(TestCase):
    def test_lists_missed_pairs_and_changes_nothing(self):
        from io import StringIO
        from django.core.management import call_command
        now = datetime.now(timezone.utc)
        for i, (title, src) in enumerate([
            ("Bluesky's new Attie tool lets anyone build a social app with AI", "TechCrunch"),
            ("Bluesky updates Attie so users can create apps and games", "The Verge"),
        ]):
            story = Story.objects.create(title=title, first_published_at=now)
            Article.objects.create(title=title, source=src, url=f"https://nd.test/{i}",
                                   published_at=now, story=story)
        before = Story.objects.count()
        out = StringIO()
        call_command("find_near_duplicates", "--min-shared", "2", stdout=out)
        self.assertEqual(Story.objects.count(), before)
        self.assertIn("Read-only", out.getvalue())
        self.assertIn("attie", out.getvalue().lower())   # the missed pair is listed


class FeedRetryTests(TestCase):
    RSS = b"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title></channel></rss>"

    def test_timeout_is_retried_once_then_succeeds(self):
        from unittest import mock
        import requests
        from news.services import rss_collector as rc
        ok = mock.Mock(content=self.RSS)
        ok.raise_for_status = lambda: None
        with mock.patch.object(rc.requests, "get",
                               side_effect=[requests.Timeout("slow"), ok]) as get:
            rc.fetch_feed({"name": "Slow", "url": "https://slow.test/feed"})
        self.assertEqual(get.call_count, 2)

    def test_two_timeouts_raise_feed_error(self):
        from unittest import mock
        import requests
        from news.services import rss_collector as rc
        with mock.patch.object(rc.requests, "get", side_effect=requests.Timeout("slow")):
            with self.assertRaises(rc.FeedError):
                rc.fetch_feed({"name": "Slow", "url": "https://slow.test/feed"})


class RequeueFailedTests(TestCase):
    def _story(self, n_articles, failures=3):
        story = Story.objects.create(title=f"S{n_articles}", ai_failures=failures,
                                     needs_ai_update=True,
                                     first_published_at=datetime.now(timezone.utc))
        for i in range(n_articles):
            Article.objects.create(title=f"a{i}", source=f"s{i}",
                                   url=f"https://rq.test/{story.pk}/{i}",
                                   published_at=datetime.now(timezone.utc), story=story)
        return story

    def run_cmd(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("requeue_failed", *args, stdout=out)
        return out.getvalue()

    def test_default_lists_and_changes_nothing(self):
        single, multi = self._story(1), self._story(2)
        report = self.run_cmd()
        self.assertIn("Nothing changed", report)
        single.refresh_from_db(); multi.refresh_from_db()
        self.assertEqual((single.ai_failures, multi.ai_failures), (3, 3))

    def test_apply_requeues_only_single_article_stories(self):
        single, multi = self._story(1), self._story(2)
        self.run_cmd("--apply")
        single.refresh_from_db(); multi.refresh_from_db()
        self.assertEqual(single.ai_failures, 0)
        self.assertEqual(multi.ai_failures, 3)       # possibly a mixed event: left for review


class RankingTuningTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.now = datetime.now(timezone.utc)

    def _story(self, title, importance, hours_ago, n_sources=1, n=0):
        story = Story.objects.create(
            title=title, summary="s", why_it_matters="w", category="Models",
            importance_score=importance, needs_ai_update=False,
            first_published_at=self.now - timedelta(hours=hours_ago))
        for i in range(n_sources):
            Article.objects.create(
                title=f"{title} {i}", source=f"Source{i}",
                url=f"https://rt.test/{n}/{title}/{i}".replace(" ", "-"),
                published_at=self.now - timedelta(hours=hours_ago), story=story)
        return story

    def _titles(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return [s["title"] for s in response.json()["results"]]

    def test_fresh_story_beats_week_old_bigger_story_in_top_stories(self):
        self._story("Six days old, score 80", 80, 6 * 24)
        self._story("Eleven hours old, score 60", 60, 11)
        self.assertEqual(self._titles("/api/feed/?sort=top")[0], "Eleven hours old, score 60")

    def test_a_huge_two_day_old_story_can_still_compete(self):
        self._story("Two days old, score 95", 95, 47)
        self._story("Fresh, score 30", 30, 2)
        self.assertEqual(self._titles("/api/feed/?sort=top")[0], "Two days old, score 95")

    def test_most_important_sort_still_uses_importance(self):
        self._story("Old and huge", 95, 5 * 24)
        self._story("Fresh and small", 40, 1)
        self.assertEqual(self._titles("/api/feed/?sort=important")[0], "Old and huge")

    def test_trending_is_a_short_list_of_the_last_two_days(self):
        for i in range(25):
            self._story(f"Fresh {i}", 60, 3, n=i)
        self._story("Three days old and huge", 95, 72, n=99)
        response = self.client.get("/api/trending/").json()
        self.assertEqual(response["count"], 20)                      # capped
        self.assertEqual(response["total_pages"], 2)
        all_titles = self._titles("/api/trending/?page=1") + self._titles("/api/trending/?page=2")
        self.assertEqual(len(all_titles), 20)
        self.assertNotIn("Three days old and huge", all_titles)      # outside 48h

    def test_trending_hides_low_importance_and_rewards_coverage(self):
        self._story("Low importance", 20, 1)
        self._story("Single source", 60, 3)
        self._story("Covered by four sources", 60, 3, n_sources=4, n=7)
        titles = self._titles("/api/trending/")
        self.assertNotIn("Low importance", titles)
        self.assertEqual(titles[0], "Covered by four sources")


class CustomerStoryDetectionTests(TestCase):
    def test_customer_story_is_not_folded_into_the_launch_group(self):
        items = [
            fake("Safety overview: GPT-6 Astra", "OpenAI", 0),
            fake("GPT-6 Astra: A new generation of intelligence", "OpenAI", 0),
            fake("Legora reviewed 41 documents in minutes with GPT-6 Astra", "OpenAI", 0),
        ]
        sizes = sorted(len(g) for g in group_articles(items))
        self.assertEqual(sizes, [1, 2])

    def test_launch_companion_posts_still_merge(self):
        items = [
            fake("Introducing GPT-5", "OpenAI", 0),
            fake("Medical research with GPT-5", "OpenAI", 0),
        ]
        self.assertEqual(len(group_articles(items)), 1)

    def test_outcome_style_customer_headlines_are_detected(self):
        from news.services.story_matcher import is_customer_story
        for title in (
            "Legora reviewed 41 documents in minutes with GPT-6 Astra",
            "Franchisee reconciles cash in 94% less time with ChatGPT Work",
            "Asana cuts model costs 76x in browser agent tests using OpenAI",
        ):
            self.assertTrue(is_customer_story(title), title)
        for title in ("Introducing GPT-5", "Medical research with GPT-5",
                      "GPT-6 Astra: A new generation of intelligence"):
            self.assertFalse(is_customer_story(title), title)


class ProductionReadinessTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_endpoint_reports_ok_and_is_not_cached(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-cache", response["Cache-Control"])

    def test_health_endpoint_reports_a_broken_database(self):
        from unittest import mock
        with mock.patch("news.views.connection.ensure_connection",
                        side_effect=RuntimeError("db down")):
            response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 503)

    def test_public_data_endpoints_are_cacheable_for_a_minute(self):
        for path in ("/api/feed/", "/api/stories/", "/api/trending/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn("max-age=60", response["Cache-Control"], path)
            self.assertIn("public", response["Cache-Control"], path)

    def test_admin_url_comes_from_settings(self):
        from django.conf import settings
        self.assertTrue(settings.ADMIN_URL.endswith("/"))


class TrendingFallbackTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.now = datetime.now(timezone.utc)

    def _story(self, title, hours_ago, n=0):
        story = Story.objects.create(
            title=title, summary="s", why_it_matters="w", category="Models",
            importance_score=60, needs_ai_update=False,
            first_published_at=self.now - timedelta(hours=hours_ago))
        Article.objects.create(
            title=title, source="X", url=f"https://tf.test/{n}",
            published_at=self.now - timedelta(hours=hours_ago), story=story)

    def _titles(self):
        return [s["title"] for s in self.client.get("/api/trending/").json()["results"]]

    def test_quiet_period_widens_the_window_so_the_page_is_not_empty(self):
        self._story("Three days old", 72, n=1)
        self._story("Four days old", 96, n=2)
        titles = self._titles()
        self.assertIn("Three days old", titles)
        self.assertIn("Four days old", titles)

    def test_busy_period_keeps_the_strict_48_hour_window(self):
        for i in range(10):
            self._story(f"Fresh {i}", 5, n=10 + i)
        self._story("Three days old", 72, n=1)
        self.assertNotIn("Three days old", self._titles())

    def test_even_the_fallback_has_a_limit(self):
        self._story("Eight days old", 8 * 24, n=1)
        self.assertNotIn("Eight days old", self._titles())
