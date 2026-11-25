from receipts.core import Evidence, ground

EV = [
    Evidence("app.log", 905, 905, "03:42:29 WARN db failover complete: promoted replica-db-3 to primary"),
    Evidence("app.log", 1200, 1200, "08:01:13 WARN db slow query on ledger_entries took 8,423 ms"),
]


def test_uncited_sentence_with_supported_details_gets_a_citation():
    assert ground("The replica replica-db-3 was promoted.", EV) == "The replica replica-db-3 was promoted [1]."


def test_detail_missing_from_evidence_drops_the_sentence_even_if_cited():
    assert ground("It was promoted to primary at 03:45:00 [1].", EV) is None


def test_number_formatting_differences_still_match():
    assert ground("The query took 8423 ms.", EV) == "The query took 8423 ms [2]."


def test_plain_hyphenated_words_are_not_treated_as_identifiers():
    assert ground("The failover was a planned-ish event for replica-db-3.", EV) is not None


def test_uncited_plain_text_answer_found_in_a_quote_is_kept():
    assert ground("Slow query on ledger_entries.", EV) == "Slow query on ledger_entries [2]."
    assert ground("Failover complete, promoted to primary.", EV) == "Failover complete, promoted to primary [1]."


def test_generic_sentence_needs_support_or_a_real_citation():
    assert ground("The cluster was rebooted overnight.", EV) is None
    assert ground("The failover completed successfully [1].", EV) == "The failover completed successfully [1]."
    assert ground("The failover completed successfully [7].", EV) is None
