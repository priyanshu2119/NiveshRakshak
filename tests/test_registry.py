"""Registry mirror + near-miss tests on fixture data (offline)."""
import pytest

from server import db, registry
from server.registry import (mirror_near_names, mirror_near_regnos, normalize_name,
                             normalize_regno, _parse_cards)


@pytest.fixture(scope="module")
def mirror(db_ready):
    db.registry_replace_rows(30, [
        {"name": "ZERODHA BROKING LIMITED", "name_norm": normalize_name("ZERODHA BROKING LIMITED"),
         "reg_no": "INZ000031633", "reg_no_norm": "INZ000031633", "type": "broker-equity"},
        {"name": "TAURUS CORPORATE ADVISORY SERVICES LIMITED",
         "name_norm": normalize_name("TAURUS CORPORATE ADVISORY SERVICES LIMITED"),
         "reg_no": "INZ000012345", "reg_no_norm": "INZ000012345", "type": "broker-equity"},
        {"name": "ANGEL ONE LIMITED", "name_norm": normalize_name("ANGEL ONE LIMITED"),
         "reg_no": "INZ000160437", "reg_no_norm": "INZ000160437", "type": "broker-equity"},
    ])
    registry._names_cache = None
    registry._regnos_cache = None
    registry._cache_loaded_at = 0.0
    return db


def test_normalization():
    assert normalize_name("Zerodha Broking Ltd.") == "ZERODHA BROKING"
    assert normalize_name("  angel   one limited ") == "ANGEL ONE"
    assert normalize_regno(" inz 000031633 ") == "INZ000031633"


def test_near_miss_name_typo(mirror):
    """Scenario 6: one-letter typo must surface as near, never as exact/none."""
    near = mirror_near_names(normalize_name("Zerodha Broking Limted"))
    assert near and near[0]["name"] == "ZERODHA BROKING LIMITED"


def test_near_miss_name_word_swap(mirror):
    near = mirror_near_names(normalize_name("Broking Zerodha"))
    assert near and near[0]["name"] == "ZERODHA BROKING LIMITED"


def test_near_miss_regno_one_digit_off(mirror):
    near = mirror_near_regnos("INZ000031634")   # last digit changed
    assert near and near[0]["reg_no"] == "INZ000031633"


def test_exact_regno_is_not_near(mirror):
    """Exact regno must not appear in near-miss results (it's an exact match)."""
    assert mirror_near_regnos("INZ000031633") == []


def test_unrelated_name_no_near(mirror):
    assert mirror_near_names(normalize_name("Random Chit Fund Company")) == []


def test_card_parser_handles_missing_fields():
    sample = ("<div class='fixed-table-body card-table'><div class='card-table-left'>"
              "<div class='number'><span>1</span></div>"
              "<div class='card-view'><div class='title'><span>Name</span></div>"
              "<div class='value varun-text'><span>ACME CAPITAL LTD</span></div></div>"
              "</div></div>"
              "<div class='pagination'><p>No record(s) available.</p></div>")
    cards = _parse_cards(sample)
    assert len(cards) == 1
    assert cards[0]["name"] == "ACME CAPITAL LTD"
    assert cards[0]["reg_no"] == ""


def test_lookup_nothing_to_look_up():
    r = registry.lookup("", "")
    assert r["state"] == "unavailable" and r["reason"] == "nothing_to_look_up"
