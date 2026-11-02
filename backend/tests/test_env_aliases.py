import env_aliases
import sim_embeddings


def test_each_new_name_lands_on_the_name_the_code_reads():
    got = env_aliases.with_aliases({
        "TWITTER_LLM_API_KEY": "t", "TWITTER_LLM_MODEL_NAME": "tm",
        "REDDIT_LLM_BASE_URL": "r",
        "MAIN_LLM_API_KEY": "m",
        "TWITTER_RERANKER_BASE_URL": "e", "TWITTER_RERANKER_BATCH": "8",
    })
    assert (got["LLM_API_KEY"], got["LLM_MODEL_NAME"]) == ("t", "tm")
    assert got["LLM_BOOST_BASE_URL"] == "r"
    assert got["LLM_PREP_API_KEY"] == "m"
    assert (got["LLM_EMBEDDING_BASE_URL"], got["LLM_EMBEDDING_BATCH"]) == ("e", "8")


def test_old_names_keep_working_and_a_new_name_wins_when_both_are_set():
    assert env_aliases.with_aliases({"LLM_BOOST_API_KEY": "old"})["LLM_BOOST_API_KEY"] == "old"
    got = env_aliases.with_aliases({"LLM_API_KEY": "old", "TWITTER_LLM_API_KEY": "new"})
    assert got["LLM_API_KEY"] == "new"


def test_a_blank_new_name_does_not_erase_the_old_one():
    assert env_aliases.with_aliases({"LLM_API_KEY": "old", "TWITTER_LLM_API_KEY": "  "})["LLM_API_KEY"] == "old"


def test_apply_changes_the_given_environment_in_place():
    env = {"MAIN_LLM_MODEL_NAME": "big"}
    env_aliases.apply(env)
    assert env["LLM_PREP_MODEL_NAME"] == "big"


def test_the_reranker_settings_read_the_new_names():
    got = sim_embeddings.settings({"TWITTER_RERANKER_BASE_URL": "https://x/v1", "TWITTER_RERANKER_API_KEY": "k"})
    assert got["base_url"] == "https://x/v1" and got["api_key"] == "k"
