"""CSV import: parsing, URL validation, duplicate detection."""
from __future__ import annotations

import pytest

import database as db
from services.outreach import importer


# --- parsing (no database) -------------------------------------------------

def test_parses_a_header_csv_with_both_columns():
    csv_text = (
        "username,profile_url\n"
        "alice,https://www.tiktok.com/@alice\n"
        "bob,https://www.tiktok.com/@bob\n"
    )
    parsed = importer.parse_csv(csv_text)
    assert [e["username"] for e in parsed["entries"]] == ["alice", "bob"]
    assert parsed["invalid"] == []


def test_derives_the_url_from_a_username_only_file():
    parsed = importer.parse_csv("username\nalice\n@Bob\n")
    assert parsed["entries"] == [
        {"username": "alice", "profile_url": "https://www.tiktok.com/@alice"},
        {"username": "bob", "profile_url": "https://www.tiktok.com/@bob"},
    ]


def test_derives_the_username_from_a_url_only_file():
    parsed = importer.parse_csv(
        "profile_url\nhttps://www.tiktok.com/@alice\n"
        "https://www.tiktok.com/@bob/video/123\n"
    )
    assert [e["username"] for e in parsed["entries"]] == ["alice", "bob"]


def test_accepts_a_headerless_list():
    parsed = importer.parse_csv("alice\nbob\n")
    assert [e["username"] for e in parsed["entries"]] == ["alice", "bob"]


def test_column_order_and_case_do_not_matter():
    parsed = importer.parse_csv("Profile URL,Username\nhttps://www.tiktok.com/@alice,alice\n")
    assert parsed["entries"] == [
        {"username": "alice", "profile_url": "https://www.tiktok.com/@alice"}
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/@alice",       # off-platform host
        "javascript:alert(1)",                    # not http(s)
        "https://www.tiktok.com/",                # no handle
        "not a url at all",
    ],
)
def test_rejects_urls_that_are_not_platform_profiles(url):
    parsed = importer.parse_csv(f"profile_url\n{url}\n")
    assert parsed["entries"] == []
    assert len(parsed["invalid"]) == 1


def test_rejects_a_username_that_disagrees_with_its_url():
    parsed = importer.parse_csv(
        "username,profile_url\nalice,https://www.tiktok.com/@bob\n"
    )
    assert parsed["entries"] == []
    assert "does not match" in parsed["invalid"][0]["reason"]


def test_rejects_an_illegal_username():
    parsed = importer.parse_csv("username\nno spaces allowed\na\n")
    assert parsed["entries"] == []
    assert len(parsed["invalid"]) == 2


def test_invalid_rows_report_their_line_number():
    parsed = importer.parse_csv("username\nalice\n!!!\n")
    assert parsed["invalid"][0]["line"] == 3


def test_a_username_column_holding_a_url_still_works():
    parsed = importer.parse_csv("username\nhttps://www.tiktok.com/@alice\n")
    assert parsed["entries"][0]["username"] == "alice"


def test_bytes_input_and_a_utf8_bom_are_handled():
    parsed = importer.parse_csv("﻿username\nalice\n".encode("utf-8"))
    assert [e["username"] for e in parsed["entries"]] == ["alice"]


def test_unknown_platform_is_rejected():
    with pytest.raises(importer.ImportError_):
        importer.parse_csv("username\nalice\n", platform="myspace")


# --- persistence -----------------------------------------------------------

async def test_import_summary_counts_imported_duplicates_invalid_ready(
    database, campaign_factory
):
    campaign = await campaign_factory()
    csv_text = (
        "username,profile_url\n"
        "alice,\n"
        "bob,\n"
        "alice,\n"                                  # duplicate within the file
        "carol,https://evil.example.com/@carol\n"   # invalid URL
    )
    summary = await importer.import_targets(database, campaign["id"], csv_text)
    assert summary == {
        "imported": 4,
        "duplicates": 1,
        "invalid": 1,
        "ready": 2,
        "invalid_rows": summary["invalid_rows"],
        "invalid_truncated": 0,
    }
    assert len(summary["invalid_rows"]) == 1


async def test_reimporting_the_same_list_adds_nothing(database, campaign_factory):
    campaign = await campaign_factory()
    csv_text = "username\nalice\nbob\n"
    await importer.import_targets(database, campaign["id"], csv_text)
    second = await importer.import_targets(database, campaign["id"], csv_text)
    assert second["ready"] == 0
    assert second["duplicates"] == 2
    targets = await db.get_outreach_targets(database, campaign["id"])
    assert len(targets) == 2


async def test_import_updates_the_campaign_counters(database, campaign_factory):
    campaign = await campaign_factory()
    await importer.import_targets(database, campaign["id"], "username\nalice\nbob\n")
    row = dict(await db.get_outreach_campaign(database, campaign["id"]))
    assert row["total_targets"] == 2
    assert row["queued_count"] == 2
    assert row["processed_count"] == 0


async def test_duplicate_usernames_are_impossible_at_the_database_level(
    database, campaign_factory
):
    """The unique constraint, not just the Python check, enforces dedup."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy import text

    campaign = await campaign_factory()
    await importer.import_targets(database, campaign["id"], "username\nalice\n")
    with pytest.raises(IntegrityError):
        await database.session.execute(
            text(
                "INSERT INTO outreach_targets (campaign_id, username, profile_url, status) "
                "VALUES (:c, 'alice', 'https://www.tiktok.com/@alice', 'queued')"
            ),
            {"c": campaign["id"]},
        )
    await database.session.rollback()


async def test_targets_of_different_campaigns_do_not_collide(
    database, campaign_factory
):
    first = await campaign_factory(name="A")
    second = await campaign_factory(name="B")
    a = await importer.import_targets(database, first["id"], "username\nalice\n")
    b = await importer.import_targets(database, second["id"], "username\nalice\n")
    assert a["ready"] == 1 and b["ready"] == 1
