"""3A: a missing value is recovered only from its own quote, only when exactly one unambiguous number fits."""
import pytest

from valuefix import missing, recover


def it(k, q, v=None, t="update"):
    return {"k": k, "q": q, "v": v, "t": t, "e": "", "a": "event"}


@pytest.mark.parametrize("k, q, want", [
    ("price_per_head", "karahi box ab Rs 700 per head", 700),             # price (Roman Urdu)
    ("price", "Hall B now costs Rs 1,80,000", 180000),                     # South Asian grouping (lakh)
    ("budget_total", "budget Rs 12,50,000 all in", 1250000),
    ("budget_total", "budget Rs 1,250,000 all in", 1250000),
    ("expense", "printing bill came in at Rs 15,000", 15000),
    ("students", "we now expect 140 students", 140),                       # attendee count
    ("staff", "Eight staff will be on duty", None),                        # number word: no digits, no guess
    ("break_min", "keep a 20-minute prayer break", 20),                    # break duration
    ("break_min", "prayer break of 1 hour", 60),                           # hours -> minutes
    ("break_min", "keep a prayer break of 20", None),                      # duration without unit: no guess
    ("duration_min", "a 4-hour hackathon", 240),
    ("at_time", "lunch must start at 13:00 sharp", "13:00"),              # deadline / clock time
    ("start_time", "doors open at 9 am", "09:00"),
    ("at_time", "lunch at 1:30 pm", "13:30"),
])
def test_recovers_one_unambiguous_value(k, q, want):
    got = recover(it(k, q))
    assert (got[0] if got else None) == want


@pytest.mark.parametrize("k, q", [
    ("price_per_head", "standard Rs 1,200, basic Rs 800"),                # two numbers
    ("students", "120 students in teams of 4"),                            # two numbers
    ("budget_total", "budget is Rs 1.2 lakh"),                             # scale word
    ("budget_total", "around 50k"),                                        # scale suffix
    ("price", "10% discount on the hall"),                                 # percent where an amount is expected
    ("students", "check in at 9:30 for 150 students"),                     # a clock time next to a count
    ("at_time", "lunch at 13:00 for 45 minutes"),                          # time plus another number
    ("price_per_head", ""),                                                # no quote at all
])
def test_never_guesses_when_ambiguous(k, q):
    assert recover(it(k, q)) is None


def test_percent_field_accepts_percent():
    assert recover(it("percent_charge", "10% service charge on food"))[0] == 10


def test_missing_only_flags_value_fields_without_usable_values():
    assert missing(it("price_per_head", "x", v=None))
    assert missing(it("at_time", "x", v="soon"))
    assert not missing(it("price_per_head", "x", v=700))
    assert not missing(it("feature", "x", v=None))                         # not a value field
    assert not missing(it("price_per_head", "x", v=None, t="suggestion"))  # suggestions are never planned


# regression from benchmark run (pack A, a_u3): "delivery charge waived" read as delivery_fee with no value
@pytest.mark.parametrize("k, q, want", [
    ("delivery_fee", "Good news: delivery charge waived, no delivery fee now.", 0),
    ("delivery_fee", "Delivery free hai", 0),
    ("delivery_fee", "free delivery from tomorrow", 0),
    ("price", "The hall is free of charge for students", 0),
    ("honorarium", "judges will help without any charge", 0),
])
def test_explicit_no_charge_wording_means_zero(k, q, want):
    assert recover(it(k, q))[0] == want


@pytest.mark.parametrize("k, q", [
    ("price", "Hall A is free on Monday"),                     # free = available, not a price
    ("price_per_head", "free delivery on all lunch boxes"),     # delivery wording does not price the meal
    ("delivery_fee", "delivery fee waived above Rs 50,000"),    # a number is present: no guessing
    ("students", "entry is free for all students"),             # not a charge field
    ("price", "parking is free"),                               # bare "free" never counts
    # review findings: negations and qualified "no ... charge" must not become a zero price
    ("delivery_fee", "Delivery fee will not be waived"),
    ("delivery_fee", "We cannot waive the delivery charge"),
    ("price_per_head", "Cold drinks included, no extra charge"),
    ("price_per_head", "No service charge on the biryani box"),
    ("price", "no hidden charges, rent confirmed"),
    ("honorarium", "Judges said no fee discussion until Friday"),
    ("price_per_head", "no delivery charge on lunch boxes"),     # delivery wording, not the meal price
])
def test_no_charge_wording_is_not_over_applied(k, q):
    got = recover(it(k, q))
    assert got is None or got[0] != 0


@pytest.mark.parametrize("k, q", [
    ("delivery_fee", "No delivery fee"),
    ("delivery_fee", "no delivery charges from today"),
    ("price", "Seminar hall, no charge."),
    ("delivery_fee", "delivery muft hai"),
])
def test_plain_no_charge_still_means_zero(k, q):
    assert recover(it(k, q))[0] == 0


# review finding (also on the 7ca59c7 baseline): a comma right after a number cut it short (50,000 -> 50)
@pytest.mark.parametrize("k, q, want", [
    ("price", "Hall rent Rs 50,000, generator included", 50000),
    ("delivery_fee", "Delivery Rs 3,000, sandwich later", 3000),
    ("price", "Hall B Rs 1,80,000, AC included", 180000),
    ("students", "120, not 150", None),                       # two numbers: still never guessed
])
def test_comma_after_a_number_does_not_cut_it(k, q, want):
    got = recover(it(k, q))
    assert (got and got[0]) == want if want is not None else got is None
