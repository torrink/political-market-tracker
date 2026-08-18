import csv

import pytest

from universe_loader import load_universe, match_entity

FIELDS = ["ticker", "company_name", "aliases", "cik", "uei", "sector",
          "benchmark_etf", "market_cap_musd", "notes"]


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            full = {field: "" for field in FIELDS}
            full.update(row)
            writer.writerow(full)
    return str(path)


@pytest.fixture
def ur_energy_csv(tmp_path):
    return _write_csv(tmp_path / "universe.csv", [
        {"ticker": "URG", "company_name": "Ur-Energy Inc",
         "aliases": "Ur-Energy Inc|Ur-Energy USA Inc", "sector": "nuclear_smr"},
        {"ticker": "AR", "company_name": "Antero Resources Corporation",
         "aliases": "Antero Resources Corporation", "sector": "energy"},
    ])


def test_load_universe_row_count():
    rows = load_universe()
    assert len(rows) == 50


def test_load_universe_sector_counts():
    rows = load_universe()
    counts = {}
    for row in rows:
        counts[row["sector"]] = counts.get(row["sector"], 0) + 1
    assert counts == {
        "defense": 15,
        "nuclear_smr": 10,
        "critical_minerals": 12,
        "semiconductors": 8,
        "energy": 5,
    }


def test_aliases_split_into_list():
    rows = load_universe()
    lmt = next(r for r in rows if r["ticker"] == "LMT")
    assert isinstance(lmt["aliases"], list)
    assert "Lockheed Martin Corporation" in lmt["aliases"]
    assert len(lmt["aliases"]) > 1


def test_cik_is_ten_digit_zero_padded():
    rows = load_universe()
    for row in rows:
        assert len(row["cik"]) == 10
        assert row["cik"].isdigit()


def test_word_boundary_does_not_match_substring(ur_energy_csv):
    text = "Congress is Defending Our Energy Act of 2026 passed committee today."
    assert match_entity(text, path=ur_energy_csv) == []


def test_word_boundary_matches_whole_phrase(ur_energy_csv):
    text = "Ur-Energy Inc announced a new supply agreement with the DOE."
    assert match_entity(text, path=ur_energy_csv) == ["URG"]


def test_matches_case_insensitively(ur_energy_csv):
    text = "the ur-energy inc facility in wyoming expanded production."
    assert match_entity(text, path=ur_energy_csv) == ["URG"]


def test_matches_alias_not_just_primary_name(ur_energy_csv):
    text = "Ur-Energy USA Inc filed a new environmental permit."
    assert match_entity(text, path=ur_energy_csv) == ["URG"]


def test_multiple_companies_in_one_text(ur_energy_csv):
    text = "Both Ur-Energy Inc and Antero Resources Corporation were mentioned in the filing."
    assert set(match_entity(text, path=ur_energy_csv)) == {"URG", "AR"}


def test_no_match_returns_empty_list(ur_energy_csv):
    assert match_entity("This text mentions no tracked companies at all.", path=ur_energy_csv) == []


def test_real_universe_ur_energy_word_boundary():
    # same case against the real shipped CSV, not just the isolated fixture
    text = "The committee is Defending Our Energy Act, unrelated to any mining company."
    assert "URG" not in match_entity(text)

    text = "Ur-Energy Inc's Lost Creek ISR facility resumed operations."
    assert "URG" in match_entity(text)
