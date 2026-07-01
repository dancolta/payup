"""Story E1 : NL intent parsing."""

from bot.intents import parse_intent

BATCH = [
    {"n": 1, "customer": "Acme Studio"},
    {"n": 2, "customer": "Bryce Co"},
    {"n": 3, "customer": "Delta Labs"},
]


def test_send_specific_numbers():
    i = parse_intent("send 1 and 3", BATCH)
    assert i.kind == "send" and i.ids == (1, 3) and not i.all


def test_send_comma_list():
    i = parse_intent("send 1,2", BATCH)
    assert i.kind == "send" and i.ids == (1, 2)


def test_send_all():
    i = parse_intent("send all", BATCH)
    assert i.kind == "send" and i.all is True


def test_skip_by_name():
    i = parse_intent("skip Delta", BATCH)
    assert i.kind == "skip" and i.ids == (3,)


def test_send_by_name():
    i = parse_intent("send acme", BATCH)
    assert i.kind == "send" and i.ids == (1,)


def test_show_overdue():
    assert parse_intent("show overdue", BATCH).kind == "show_overdue"
    assert parse_intent("what's overdue?", BATCH).kind == "show_overdue"


def test_help():
    assert parse_intent("help", BATCH).kind == "help"


def test_junk_is_unknown():
    assert parse_intent("lol thanks", BATCH).kind == "unknown"


def test_bare_send_is_unknown_not_implicit():
    # "send" with no target must NOT become an implicit send-all
    i = parse_intent("send", BATCH)
    assert i.kind == "unknown"


def test_conflicting_send_and_skip_is_unknown():
    assert parse_intent("send 1 but skip 2", BATCH).kind == "unknown"


def test_out_of_range_numbers_ignored():
    # 9 is not a valid row -> no resolvable target -> unknown
    assert parse_intent("send 9", BATCH).kind == "unknown"


def test_empty_is_unknown():
    assert parse_intent("", BATCH).kind == "unknown"


def test_negated_send_is_unknown():
    # "do not send all" must NOT send everything.
    assert parse_intent("do not send all", BATCH).kind == "unknown"
    assert parse_intent("don't send anything", BATCH).kind == "unknown"
    assert parse_intent("cancel, do not send 1", BATCH).kind == "unknown"


def test_question_send_is_unknown():
    # A question is not a command.
    assert parse_intent("should I send all?", BATCH).kind == "unknown"
    assert parse_intent("can you send 1 and 3?", BATCH).kind == "unknown"


def test_stopword_in_name_not_matched():
    # "and" in "send 1 and 3" must not select a customer named "Smith and Sons".
    batch = BATCH + [{"n": 4, "customer": "Smith and Sons"}]
    i = parse_intent("send 1 and 3", batch)
    assert i.kind == "send" and i.ids == (1, 3)


def test_draft_specific_numbers():
    i = parse_intent("draft 1 and 3", BATCH)
    assert i.kind == "draft" and i.ids == (1, 3) and not i.all


def test_draft_all():
    i = parse_intent("draft all", BATCH)
    assert i.kind == "draft" and i.all is True


def test_draft_by_name():
    i = parse_intent("draft Delta", BATCH)
    assert i.kind == "draft" and i.ids == (3,)


def test_bare_draft_is_unknown():
    # "draft" with no target must NOT become an implicit draft-all.
    assert parse_intent("draft", BATCH).kind == "unknown"


def test_negated_or_question_draft_is_unknown():
    assert parse_intent("do not draft all", BATCH).kind == "unknown"
    assert parse_intent("should I draft 1?", BATCH).kind == "unknown"


def test_send_and_draft_combo_is_unknown():
    assert parse_intent("send 1 and draft 3", BATCH).kind == "unknown"


def test_strips_slack_mention():
    # An @mention prefix (Slack markup) must not break a command.
    i = parse_intent("<@U12345> send all", BATCH)
    assert i.kind == "send" and i.all is True


def test_edit_template_trigger_no_tier():
    i = parse_intent("edit template", BATCH)
    assert i.kind == "edit_template" and i.tier is None


def test_edit_template_trigger_variants():
    for phrase in ("edit templates", "edit the reminders", "change my wording", "update reminder copy"):
        assert parse_intent(phrase, BATCH).kind == "edit_template", phrase


def test_edit_template_names_tier_up_front():
    assert parse_intent("edit template gentle", BATCH).tier == "gentle"
    assert parse_intent("edit template for the final reminder", BATCH).tier == "final"


def test_edit_template_with_mention_prefix():
    i = parse_intent("<@U0BC> edit template", BATCH)
    assert i.kind == "edit_template" and i.tier is None


def test_edit_trigger_is_never_a_send():
    # The editor trigger must never be read as a send/chase.
    assert parse_intent("edit the reminders", BATCH).kind == "edit_template"
    assert parse_intent("change my reminder wording", BATCH).kind == "edit_template"
