import json
import math
import sqlite3

import pytest

from app.services import ensemble_aggregator as agg
from app.services.ensemble_aggregator import (
    CAVEAT_TEMPLATE,
    behavior_metrics,
    build_summary,
    describe,
    percentile,
    poll_metrics,
    render_markdown,
    replicate_metrics,
    stance_mapping,
    summarize,
    topic_matcher,
    write_summary,
)

Q_PROB = {"id": "q1", "text": "Will it trade higher?", "type": "probability"}
Q_CHOICE = {
    "id": "q2", "text": "Your stance?", "type": "choice", "options": ["bullish", "neutral", "bearish"],
    "stance_map": {"bullish": "supportive", "neutral": "neutral", "bearish": "opposing"},
}
Q_NUMBER = {"id": "q3", "text": "Expected move?", "type": "number", "unit": "%"}
QUESTIONS = [Q_PROB, Q_CHOICE, Q_NUMBER]

AGENTS = [
    {"agent_id": 0, "entity_name": "Alice", "stance": "supportive", "influence_weight": 3.0},
    {"agent_id": 1, "entity_name": "Bob", "stance": "opposing", "influence_weight": 1.0},
    {"agent_id": 2, "entity_name": "Cara", "stance": "neutral", "influence_weight": 1.0},
    {"agent_id": 3, "entity_name": "Dan", "stance": "observer", "influence_weight": 1.0},
]


def row(agent_id, q1=None, q2=None, q3=None, ok=True):
    stance = AGENTS[agent_id]["stance"]
    answers = {k: v for k, v in (("q1", q1), ("q2", q2), ("q3", q3)) if v is not None}
    return {"agent_id": agent_id, "agent_name": AGENTS[agent_id]["entity_name"], "stance_initial": stance,
            "answers": answers if ok else {}, "reason": "", "raw": "{}", "parse_ok": ok}


POLL_1 = [row(0, 80, "bullish", 2.0), row(1, 20, "bearish", -1.0), row(2, 50, "neutral", 0.0), row(3, ok=False)]
POLL_2 = [row(0, 60, "neutral", 1.0), row(1, 30, "bearish", -2.0), row(2, 40, "bullish", 0.5), row(3, 90, "bullish", 3.0)]
POLL_3 = [row(0, 100, "bullish", 5.0), row(1, 10, "bearish", -4.0), row(2, 55, "neutral", 1.0), row(3, 5, "bearish", 0.0)]
INFLUENCE = {a["agent_id"]: a["influence_weight"] for a in AGENTS}


# --- statistics ------------------------------------------------------------------

def test_percentile_interpolates_linearly():
    data = [1.0, 2.0, 3.0, 4.0]
    assert percentile(data, 0.0) == 1.0 and percentile(data, 1.0) == 4.0
    assert percentile(data, 0.5) == 2.5
    assert percentile(data, 0.1) == pytest.approx(1.3)
    assert percentile(data, 0.9) == pytest.approx(3.7)
    assert percentile([7.0], 0.9) == 7.0
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_describe_reports_the_documented_statistics():
    stats = describe([42.5, 50.0, 55.0])
    assert stats["n"] == 3
    assert stats["mean"] == pytest.approx(49.1666667)
    assert stats["min"] == 42.5 and stats["max"] == 55.0 and stats["median"] == 50.0
    assert stats["p10"] == pytest.approx(44.0) and stats["p90"] == pytest.approx(54.0)
    # sample standard deviation (n - 1)
    assert stats["std"] == pytest.approx(math.sqrt(79.1666667 / 2), rel=1e-5)


def test_describe_handles_one_value_and_none_values():
    one = describe([5])
    assert one["std"] == 0.0 and one["mean"] == 5.0 and one["n"] == 1
    assert describe([None, 3, None, 5])["n"] == 2
    empty = describe([])
    assert empty["n"] == 0 and all(empty[k] is None for k in ("mean", "std", "min", "p10", "median", "p90", "max"))
    assert describe([None, None])["mean"] is None
    assert describe([float("nan"), 1.0])["n"] == 1


# --- polls ------------------------------------------------------------------------

def test_probability_choice_and_number_reductions():
    metrics = poll_metrics(POLL_1, QUESTIONS, INFLUENCE)
    assert metrics["agents_total"] == 4 and metrics["agents_ok"] == 3
    assert metrics["parse_rate"] == 0.75

    q1 = metrics["questions"]["q1"]
    assert q1["n"] == 3 and q1["mean"] == 50.0 and q1["median"] == 50.0
    assert q1["influence_weighted_mean"] == pytest.approx((80 * 3 + 20 + 50) / 5)

    q2 = metrics["questions"]["q2"]
    assert q2["counts"] == {"bullish": 1, "neutral": 1, "bearish": 1}
    assert q2["shares"]["bullish"] == pytest.approx(1 / 3)

    q3 = metrics["questions"]["q3"]
    assert q3["median"] == 0.0 and q3["mean"] == pytest.approx(1 / 3) and q3["unit"] == "%"


def test_the_weighted_mean_uses_each_agents_influence():
    metrics = poll_metrics(POLL_2, QUESTIONS, INFLUENCE)
    assert metrics["questions"]["q1"]["influence_weighted_mean"] == pytest.approx((60 * 3 + 30 + 40 + 90) / 6)
    assert metrics["questions"]["q1"]["mean"] == 55.0
    assert metrics["questions"]["q3"]["median"] == 0.75
    flat = poll_metrics(POLL_2, QUESTIONS, {})
    assert flat["questions"]["q1"]["influence_weighted_mean"] == pytest.approx(55.0)


def test_unparsed_agents_are_excluded_from_statistics_but_counted_in_the_parse_rate():
    rows = [row(0, 10, "bullish", 1.0), row(1, 90, "bearish", 2.0, ok=False)]
    metrics = poll_metrics(rows, QUESTIONS, INFLUENCE)
    assert metrics["questions"]["q1"]["n"] == 1 and metrics["questions"]["q1"]["mean"] == 10.0
    assert metrics["parse_rate"] == 0.5


def test_a_poll_with_no_usable_answer_has_empty_statistics():
    rows = [row(0, ok=False), row(1, ok=False)]
    metrics = poll_metrics(rows, QUESTIONS, INFLUENCE)
    assert metrics["parse_rate"] == 0.0
    assert metrics["questions"]["q1"]["mean"] is None
    assert metrics["questions"]["q2"]["shares"] == {"bullish": None, "neutral": None, "bearish": None}
    assert poll_metrics([], QUESTIONS, INFLUENCE)["parse_rate"] is None


def test_stance_drift_counts_agents_who_switched():
    drift = poll_metrics(POLL_2, QUESTIONS, INFLUENCE)["stance_drift"]
    assert drift["applicable"] is True and drift["question"] == "q2"
    # Alice supportive -> neutral and Cara neutral -> supportive switched; Bob did not;
    # Dan is an observer and has no stance to drift from.
    assert drift["agents_considered"] == 3 and drift["switched"] == 2
    assert drift["switched_share"] == pytest.approx(2 / 3)
    assert drift["matrix"] == {"supportive": {"neutral": 1}, "opposing": {"opposing": 1}, "neutral": {"supportive": 1}}
    assert poll_metrics(POLL_1, QUESTIONS, INFLUENCE)["stance_drift"]["switched"] == 0


def test_drift_is_not_applicable_without_a_stance_question():
    drift = poll_metrics(POLL_1, [Q_PROB, Q_NUMBER], INFLUENCE)["stance_drift"]
    assert drift == {"applicable": False}
    unmappable = {"id": "q2", "text": "?", "type": "choice", "options": ["red", "blue"]}
    assert poll_metrics(POLL_1, [unmappable], INFLUENCE)["stance_drift"] == {"applicable": False}


def test_stance_mapping_prefers_the_explicit_map_then_known_synonyms():
    assert stance_mapping(Q_CHOICE)["bullish"] == "supportive"
    synonyms = {"id": "q", "text": "t", "type": "choice", "options": ["Bullish", "Neutral", "Bearish"]}
    assert stance_mapping(synonyms) == {"Bullish": "supportive", "Neutral": "neutral", "Bearish": "opposing"}
    assert stance_mapping({"id": "q", "text": "t", "type": "choice", "options": ["support", "oppose"]}) == {
        "support": "supportive", "oppose": "opposing"}
    # one unknown option: do not guess
    assert stance_mapping({"id": "q", "text": "t", "type": "choice", "options": ["bullish", "banana"]}) is None
    assert stance_mapping(Q_PROB) is None


# --- behaviour --------------------------------------------------------------------

def jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def act(agent_id, round_num, action_type, **args):
    phase = args.pop("phase", None)
    record = {"round": round_num, "timestamp": "t", "agent_id": agent_id, "agent_name": f"A{agent_id}",
              "action_type": action_type, "action_args": args, "result": None, "success": True}
    if phase:
        record["phase"] = phase
    return record


EVENT = {"event_type": "round_start", "round": 1, "timestamp": "t", "simulated_hour": 1}

TWITTER_RECORDS = [
    {"event_type": "simulation_start", "timestamp": "t", "platform": "twitter"},
    EVENT,
    act(0, 0, "CREATE_POST", content="Initial post"),
    act(0, 0, "FOLLOW", followee_id=1, phase="setup"),
    act(1, 1, "CREATE_POST", content="A1 post mentions Demerger"),
    act(2, 1, "LIKE_POST", post_id=1),
    act(3, 1, "DO_NOTHING"),
    act(0, 1, "CREATE_POST", content="Initial post", post_id=1),  # legacy replay of the round-0 post
    act(1, 2, "CREATE_COMMENT", content="comment about margin data"),
    act(0, 2, "REPOST", post_id=1),
    act(2, 2, "FOLLOW", follow_id=9),
    act(3, 2, "QUOTE_POST", quote_content="quote about margin data"),
    act(0, 2, "CREATE_POST", content="Injected", phase="injected", event_id="evt_1"),
    act(3, 3, "INTERVIEW", phase="poll"),
    {"event_type": "simulation_end", "timestamp": "t", "platform": "twitter"},
]
REDDIT_RECORDS = [
    act(0, 1, "CREATE_POST", content="Reddit post"),
    act(1, 1, "DISLIKE_POST", post_id=1),
    act(2, 2, "CREATE_COMMENT", content="reddit comment"),
]


def make_db(path, posts, comments=()):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE post (post_id INTEGER PRIMARY KEY, user_id INT, original_post_id INT, content TEXT, "
                "quote_content TEXT, created_at TEXT, num_likes INT, num_dislikes INT, num_shares INT, num_reports INT)")
    con.execute("CREATE TABLE comment (comment_id INTEGER PRIMARY KEY, post_id INT, user_id INT, content TEXT, "
                "created_at TEXT, num_likes INT, num_dislikes INT)")
    for post_id, user_id, original, content, likes, shares in posts:
        con.execute("INSERT INTO post VALUES (?, ?, ?, ?, NULL, 't', ?, 0, ?, 0)",
                    (post_id, user_id, original, content, likes, shares))
    for comment_id, post_id in comments:
        con.execute("INSERT INTO comment VALUES (?, ?, 1, 'c', 't', 0, 0)", (comment_id, post_id))
    con.commit()
    con.close()


def make_config(max_rounds=3, **overrides):
    config = {
        "agent_configs": AGENTS,
        "event_config": {"hot_topics": ["Demerger", "margin data"]},
        "run": {"max_rounds": max_rounds},
    }
    config.update(overrides)
    return config


def make_replicate(root, simulation_id, *, poll=None, twitter=(), reddit=(), db=None, config=None):
    sim_dir = root / simulation_id
    sim_dir.mkdir(parents=True)
    (sim_dir / "simulation_config.json").write_text(json.dumps(config or make_config()), encoding="utf-8")
    if poll is not None:
        (sim_dir / "final_poll.json").write_text(json.dumps(poll), encoding="utf-8")
    if twitter:
        jsonl(sim_dir / "twitter" / "actions.jsonl", twitter)
    if reddit:
        jsonl(sim_dir / "reddit" / "actions.jsonl", reddit)
    if db:
        make_db(str(sim_dir / "twitter_simulation.db"), *db)
    return sim_dir


DB_POSTS = [
    (1, 1, None, "A1 post mentions Demerger", 3, 1),   # Bob: 3 likes + 1 share + 2 comments = 6
    (2, 0, None, "Initial post", 5, 2),                # Alice: 7
    (3, 0, None, "Injected", 100, 50),                 # scripted event post: ignored
    (4, 2, 2, "RT", 9, 9),                             # a repost row: not an authored post
]
DB_COMMENTS = [(1, 1), (2, 1)]


def test_behaviour_counts_skip_setup_injected_poll_and_legacy_replays(tmp_path):
    sim_dir = make_replicate(tmp_path, "sim_a", twitter=TWITTER_RECORDS, reddit=REDDIT_RECORDS,
                             db=(DB_POSTS, DB_COMMENTS))
    metrics = behavior_metrics(str(sim_dir), make_config(), rounds=3)

    assert metrics["total_actions"] == 11 and metrics["active_actions"] == 10
    assert metrics["posts"] == 4  # initial, A1's post, reddit post, one quote
    assert metrics["comments"] == 2 and metrics["likes"] == 1 and metrics["dislikes"] == 1
    assert metrics["reposts"] == 1 and metrics["follows"] == 1  # the setup follow is not counted
    assert metrics["actions_per_round"] == [5, 5, 0]


def test_posts_are_attributed_to_stance_groups(tmp_path):
    sim_dir = make_replicate(tmp_path, "sim_a", twitter=TWITTER_RECORDS, reddit=REDDIT_RECORDS)
    shares = behavior_metrics(str(sim_dir), make_config())["stance_group_post_share"]
    assert shares["supportive"] == 0.5 and shares["opposing"] == 0.25
    assert shares["observer"] == 0.25 and shares["neutral"] == 0.0


def test_engagement_is_read_from_the_database_ignoring_scripted_and_repost_rows(tmp_path):
    sim_dir = make_replicate(tmp_path, "sim_a", twitter=TWITTER_RECORDS, db=(DB_POSTS, DB_COMMENTS))
    metrics = behavior_metrics(str(sim_dir), make_config())
    assert metrics["engagement_total"] == 13
    assert metrics["top_agents"] == [
        {"agent_id": 0, "agent_name": "Alice", "engagement": 7},
        {"agent_id": 1, "agent_name": "Bob", "engagement": 6},
    ]
    group = metrics["stance_group_engagement_share"]
    assert group["supportive"] == pytest.approx(7 / 13) and group["opposing"] == pytest.approx(6 / 13)


def test_hot_topic_mentions_are_counted_per_round_case_insensitively(tmp_path):
    sim_dir = make_replicate(tmp_path, "sim_a", twitter=TWITTER_RECORDS, reddit=REDDIT_RECORDS)
    mentions = behavior_metrics(str(sim_dir), make_config(), rounds=3)["hot_topic_mentions"]
    assert mentions["Demerger"] == {"total": 1, "by_round": [1, 0, 0]}
    assert mentions["margin data"] == {"total": 2, "by_round": [0, 2, 0]}


def test_behaviour_of_a_run_without_logs_is_all_zero(tmp_path):
    sim_dir = make_replicate(tmp_path, "sim_empty")
    metrics = behavior_metrics(str(sim_dir), make_config(), rounds=2)
    assert metrics["total_actions"] == 0 and metrics["actions_per_round"] == [0, 0]
    assert metrics["stance_group_post_share"]["supportive"] is None
    assert metrics["top_agents"] == []


def test_a_corrupt_database_or_log_line_does_not_break_aggregation(tmp_path):
    sim_dir = make_replicate(tmp_path, "sim_a", twitter=TWITTER_RECORDS)
    (sim_dir / "twitter_simulation.db").write_bytes(b"not sqlite")
    with open(sim_dir / "twitter" / "actions.jsonl", "a", encoding="utf-8") as handle:
        handle.write("this is not json\n")
    metrics = behavior_metrics(str(sim_dir), make_config())
    assert metrics["engagement_total"] == 0 and metrics["total_actions"] == 8


# --- replicates -------------------------------------------------------------------

def test_replicate_metrics_combines_poll_and_behaviour(tmp_path):
    make_replicate(tmp_path, "sim_a", poll=POLL_2, twitter=TWITTER_RECORDS)
    entry = replicate_metrics({"index": 1, "simulation_id": "sim_a", "seed": 99}, QUESTIONS, str(tmp_path))
    assert entry["status"] == "ok" and entry["index"] == 1 and entry["seed"] == 99
    assert entry["poll"]["questions"]["q1"]["mean"] == 55.0
    assert entry["behavior"]["total_actions"] == 8


def test_replicate_without_a_poll_file_still_yields_behaviour(tmp_path):
    make_replicate(tmp_path, "sim_a", twitter=TWITTER_RECORDS)
    entry = replicate_metrics({"index": 1, "simulation_id": "sim_a", "seed": 1}, QUESTIONS, str(tmp_path))
    assert entry["poll"] is None and entry["behavior"]["posts"] == 3


def test_a_missing_replicate_directory_is_reported_not_raised(tmp_path):
    entry = replicate_metrics({"index": 2, "simulation_id": "sim_gone", "seed": 1}, QUESTIONS, str(tmp_path))
    assert entry["status"] == "missing"


# --- across replicates --------------------------------------------------------------

@pytest.fixture
def ensemble_dirs(tmp_path):
    sims = tmp_path / "sims"
    for i, poll in enumerate([POLL_1, POLL_2, POLL_3], start=1):
        make_replicate(sims, f"sim_x__r0{i}", poll=poll, twitter=TWITTER_RECORDS, reddit=REDDIT_RECORDS,
                       db=(DB_POSTS, DB_COMMENTS))
    ensemble = {
        "ensemble_id": "ens_test", "base_simulation_id": "sim_x", "n_replicates": 3, "max_rounds": 3,
        "base_seed": 5,
        "replicates": [
            {"index": i, "simulation_id": f"sim_x__r0{i}", "seed": 100 + i, "status": "completed"}
            for i in (1, 2, 3)
        ],
    }
    return ensemble, str(sims), tmp_path


def test_summary_distributions_across_replicates(ensemble_dirs):
    ensemble, sims, _ = ensemble_dirs
    summary = build_summary(ensemble, QUESTIONS, sims)

    assert summary["n_replicates_ok"] == 3 and summary["n_replicates_with_poll"] == 3
    q1 = summary["polls"]["q1"]
    assert q1["agent_mean"]["mean"] == pytest.approx((50 + 55 + 42.5) / 3)
    assert q1["agent_mean"]["median"] == 50.0 and q1["agent_mean"]["min"] == 42.5 and q1["agent_mean"]["max"] == 55.0
    assert q1["agent_mean"]["p10"] == pytest.approx(44.0) and q1["agent_mean"]["p90"] == pytest.approx(54.0)
    assert q1["agent_median"]["median"] == 50.0  # medians 50, 50, 32.5
    assert q1["influence_weighted_mean"]["mean"] == pytest.approx((62.0 + 340 / 6 + 370 / 6) / 3)
    assert q1["share_of_replicates_mean_above_50"] == pytest.approx(1 / 3)

    q2 = summary["polls"]["q2"]
    assert q2["options"]["bullish"]["mean"] == pytest.approx((1 / 3 + 0.5 + 0.25) / 3)
    assert sum(q2["most_common_in_replicates"].values()) == 3
    assert summary["polls"]["q3"]["median"]["median"] == 0.5  # medians 0, 0.75, 0.5

    assert summary["parse_rate"]["min"] == 0.75 and summary["parse_rate"]["max"] == 1.0
    drift = summary["stance_drift"]
    assert drift["applicable"] and drift["question"] == "q2"
    assert drift["switched_agents"]["mean"] == pytest.approx(2 / 3) and drift["switched_agents"]["max"] == 2

    behaviour = summary["behavior"]
    assert behaviour["total_actions"]["mean"] == 11 and behaviour["total_actions"]["std"] == 0.0
    assert behaviour["actions_per_round_mean"] == [5, 5, 0]
    assert behaviour["top_agents"][0] == {"agent_id": 0, "agent_name": "Alice", "replicates": 3, "share_of_replicates": 1.0}
    assert summary["hot_topics"]["margin data"]["mean"] == 2
    assert [r["index"] for r in summary["replicates"]] == [1, 2, 3]
    assert summary["replicates"][0]["parse_rate"] == 0.75


def test_most_common_option_per_replicate(ensemble_dirs):
    ensemble, sims, _ = ensemble_dirs
    # replicate 1: all options tied (earlier option wins ties) -> bullish; 2: bullish; 3: bearish
    modal = build_summary(ensemble, QUESTIONS, sims)["polls"]["q2"]["most_common_in_replicates"]
    assert modal == {"bullish": 2, "neutral": 0, "bearish": 1}


def test_only_completed_replicates_are_aggregated(ensemble_dirs):
    ensemble, sims, _ = ensemble_dirs
    ensemble["replicates"][1]["status"] = "failed"
    ensemble["replicates"][2]["status"] = "stopped"
    summary = build_summary(ensemble, QUESTIONS, sims)
    assert summary["n_replicates_ok"] == 1
    assert summary["polls"]["q1"]["agent_mean"]["n"] == 1
    assert summary["caveat"].startswith("These are distributions of *simulated participants' views* across 1 stochastic runs")


def test_summary_without_questions_has_behaviour_only(ensemble_dirs):
    ensemble, sims, _ = ensemble_dirs
    summary = build_summary(ensemble, [], sims)
    assert summary["polls"] == {} and summary["stance_drift"] == {"applicable": False}
    assert summary["behavior"]["posts"]["n"] == 3 and summary["n_replicates_with_poll"] == 0


def test_a_missing_replicate_is_excluded_from_the_statistics(ensemble_dirs):
    ensemble, sims, _ = ensemble_dirs
    ensemble["replicates"][0]["simulation_id"] = "sim_nowhere"
    summary = build_summary(ensemble, QUESTIONS, sims)
    assert summary["n_replicates_ok"] == 2
    assert any(r["status"] == "missing" for r in summary["replicates"])


def test_summarize_with_no_ok_replicates_is_empty_but_well_formed():
    summary = summarize({"ensemble_id": "e", "n_replicates": 2}, QUESTIONS,
                        [{"status": "missing", "index": 1, "simulation_id": "s"}])
    assert summary["n_replicates_ok"] == 0
    assert summary["polls"]["q1"]["agent_mean"]["n"] == 0
    render_markdown(summary)  # must not raise


# --- rendering and files ---------------------------------------------------------------

def test_markdown_opens_with_the_fixed_caveat(ensemble_dirs):
    ensemble, sims, _ = ensemble_dirs
    markdown = render_markdown(build_summary(ensemble, QUESTIONS, sims))
    first_lines = markdown.splitlines()[:4]
    assert first_lines[0] == "# Ensemble summary: ens_test"
    expected = "> " + CAVEAT_TEMPLATE.format(n=3)
    assert expected in first_lines
    assert "not calibrated probabilities of the real-world event" in markdown
    assert "has not been backtested for this domain" in markdown


def test_markdown_covers_every_section(ensemble_dirs):
    ensemble, sims, _ = ensemble_dirs
    markdown = render_markdown(build_summary(ensemble, QUESTIONS, sims))
    for fragment in ("## Outcome questions", "### q1: Will it trade higher?", "influence-weighted mean",
                     "### q2: Your stance?", "bullish", "### q3: Expected move?", "Median answer (%)",
                     "## Stance drift", "## Behaviour", "Share of posts by starting stance",
                     "## Hot-topic mentions", "## Replicates", "sim_x__r01", "Poll parse rate"):
        assert fragment in markdown, fragment


def test_write_summary_writes_json_and_markdown(ensemble_dirs):
    ensemble, sims, root = ensemble_dirs
    out = root / "ens_test"
    out.mkdir()
    summary = build_summary(ensemble, QUESTIONS, sims)
    write_summary(str(out), summary)
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["n_replicates_ok"] == 3
    assert (out / "summary.md").read_text(encoding="utf-8").startswith("# Ensemble summary")
    assert [p.name for p in out.iterdir() if p.suffix == ".tmp"] == []


def test_the_summary_is_json_serialisable(ensemble_dirs):
    ensemble, sims, _ = ensemble_dirs
    json.dumps(build_summary(ensemble, QUESTIONS, sims))


# --- hot topics: the phrase, or all of its words ----------------------------------------------------

def test_a_topic_matches_the_phrase_or_all_of_its_words_in_any_order():
    mentions = topic_matcher("FTO-11 facility inspection")
    assert mentions("monitoring the fto-11 facility inspection results")  # the phrase
    assert mentions("the inspection of the facility in fto-11 took long")  # every word, any order
    assert not mentions("the fto-11 plant inspection")  # 'facility' is missing
    assert not mentions("nothing relevant here")


def test_a_single_word_or_unspaced_topic_matches_only_as_a_substring():
    assert topic_matcher("Demerger")("a demerger plan") and not topic_matcher("Demerger")("de merger")
    assert topic_matcher("股价反应")("市场对股价反应强烈") and not topic_matcher("股价反应")("股价 反应")


def test_short_words_do_not_make_a_topic_easier_or_harder_to_match():
    mentions = topic_matcher("a risk of delay")  # only 'risk' and 'delay' count
    assert mentions("delay is the main risk") and not mentions("a delay")


def test_a_short_word_with_a_digit_still_counts():
    mentions = topic_matcher("Q3 results")
    assert mentions("results for q3 are out") and not mentions("results are out")


def test_behaviour_metrics_count_a_post_that_has_every_word_of_a_topic(tmp_path):
    records = [
        act(1, 1, "CREATE_POST", content="Injectable approvals and formulations look delayed"),  # 'approvals' contains 'approval'
        act(2, 1, "CREATE_POST", content="Formulations are fine"),
        act(3, 2, "CREATE_COMMENT", content="No news on the injectable formulations approval"),
        act(1, 2, "CREATE_POST", content="Unrelated"),
    ]
    sim_dir = make_replicate(tmp_path, "sim_topics", twitter=records,
                             config=make_config(event_config={"hot_topics": ["injectable formulations approval"]}))
    mentions = behavior_metrics(str(sim_dir), make_config(event_config={"hot_topics": ["injectable formulations approval"]}),
                                rounds=2)["hot_topic_mentions"]
    assert mentions["injectable formulations approval"] == {"total": 2, "by_round": [1, 1]}
