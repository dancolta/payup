"""Story C4 — reply classification (context only, never resolves)."""

from payup.lib.reply import Label, classify_reply


def test_paid_high_confidence():
    label, conf = classify_reply("Hi, I already paid this last week.")
    assert label is Label.PAID
    assert conf >= 0.8


def test_will_pay():
    label, conf = classify_reply("Sorry for the delay, will pay by Friday.")
    assert label is Label.WILL_PAY


def test_dispute_takes_precedence_over_paid():
    # contains "paid" notion but is a dispute -> must not read as paid
    label, _ = classify_reply("This invoice is wrong, I never received the work and won't pay.")
    assert label is Label.DISPUTE


def test_silence_on_empty():
    label, conf = classify_reply("   ")
    assert label is Label.SILENCE


def test_unknown_on_noise():
    label, _ = classify_reply("Thanks, talk soon!")
    assert label is Label.UNKNOWN


def test_ambiguous_paid_is_lower_confidence():
    # vague past-payment hint -> not high confidence
    label, conf = classify_reply("payment should be settled on your end")
    assert label in (Label.PAID, Label.UNKNOWN)
    if label is Label.PAID:
        assert conf < 0.8


def test_classify_returns_only_a_label_no_side_effects():
    # The function returns a pure (Label, float). It must not be coupled to any
    # resolve machinery or to Wave/state: resolve is owned by Wave status alone.
    import inspect

    import payup.lib.reply as reply

    src = inspect.getsource(reply)
    assert "mark_resolved(" not in src
    assert "import wave" not in src and "from .wave" not in src
    assert "import store" not in src and "from .store" not in src
