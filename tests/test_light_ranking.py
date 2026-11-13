from __future__ import annotations

from light.sources import Book, _parse_query, compute_relevance_score, rank_results


def _score(title: str, query: str) -> float:
    tokens, phrases, has_phrases = _parse_query(query)
    return compute_relevance_score(title, query, tokens, phrases, has_phrases)


def test_parse_query_strips_stop_words():
    tokens, phrases, has_phrases = _parse_query("who moved my cheese")
    assert tokens == ["moved", "cheese"]
    assert phrases == []
    assert not has_phrases


def test_parse_query_keeps_quoted_phrases():
    tokens, phrases, has_phrases = _parse_query('"to kill a mockingbird"')
    assert phrases == ["to kill a mockingbird"]
    assert tokens == []
    assert has_phrases


def test_exact_match_ranks_first():
    query = "who moved my cheese"
    results = rank_results(
        [
            Book(id="1", title="The Cheese Factory", language="english", source="Z-Library"),
            Book(id="2", title="Who Moved My Cheese?", language="english", source="Z-Library"),
            Book(id="3", title="Moved Cheese", language="english", source="Z-Library"),
        ],
        query,
    )
    assert results[0].title == "Who Moved My Cheese?"


def test_query_containment_beats_keyword_only():
    q = "who moved my cheese"
    contained = _score("Who Moved My Cheese? For Teens", q)
    keyword_only = _score("Moved Cheese", q)
    assert contained > keyword_only


def test_keyword_order_matters():
    q = "who moved my cheese"
    ordered = _score("Moved Cheese", q)
    reversed_ = _score("Cheese Moved", q)
    assert ordered > reversed_


def test_full_keyword_match_beats_partial():
    q = "who moved my cheese"
    full = _score("Moved Cheese: A Story", q)
    partial = _score("The Cheese Factory", q)
    assert full > partial


def test_stemming_matches_verb_forms():
    q = "who moved my cheese"
    assert _score("Moving Cheese", q) > 0
    assert _score("The Moving Cheese", q) > 0


def test_unrelated_titles_score_lowest():
    q = "who moved my cheese"
    unrelated = _score("Out of the Box", q)
    assert unrelated < _score("The Cheese Factory", q)
    assert unrelated == 0.0


def test_quoted_phrase_containment_boosted():
    q = '"atomic habits"'
    phrase = _score("Atomic Habits: An Easy & Proven Way", q)
    no_phrase = _score("The Atomic and Habits Reader", q)
    assert phrase > no_phrase


def test_full_order_ranking_integration():
    query = "who moved my cheese"
    results = rank_results(
        [
            Book(id="1", title="Out of the Box", language="english", source="Z-Library"),
            Book(id="2", title="Who Moved My Cheese?", language="english", source="Z-Library"),
            Book(id="3", title="Cheese Moved", language="english", source="Z-Library"),
            Book(id="4", title="Moved Cheese", language="english", source="Z-Library"),
            Book(id="5", title="The Cheese Factory", language="english", source="Z-Library"),
            Book(id="6", title="Who Moved My Cheese? For Teens", language="english", source="Z-Library"),
        ],
        query,
    )
    titles = [b.title for b in results]
    assert titles[0] == "Who Moved My Cheese?"
    assert titles.index("Who Moved My Cheese? For Teens") < titles.index("Moved Cheese")
    assert titles.index("Moved Cheese") < titles.index("Cheese Moved")
    assert titles.index("Cheese Moved") < titles.index("The Cheese Factory")
    assert titles[-1] == "Out of the Box"
