from app.services import memory_service


def test_get_or_create_user_is_idempotent():
    u1 = memory_service.get_or_create_user("123", "Sam", "sam_trades")
    u2 = memory_service.get_or_create_user("123", "Sam", "sam_trades")
    assert u1.id == u2.id
    assert u1.onboarding_stage == "new"


def test_update_profile_merges_lists_without_duplicates():
    user = memory_service.get_or_create_user("456", "Ana", "ana_invests")
    memory_service.update_profile(user.id, {"sectors_followed": ["AI", "semiconductors"]})
    memory_service.update_profile(user.id, {"sectors_followed": ["semiconductors", "biotech"]})

    updated = memory_service.get_user_by_id(user.id)
    assert set(updated.profile()["sectors_followed"]) == {"AI", "semiconductors", "biotech"}


def test_add_learned_fact_deduplicates_and_caps():
    user = memory_service.get_or_create_user("789", "Lee", "lee_cfo")
    memory_service.add_learned_fact(user.id, "Prefers concise summaries")
    memory_service.add_learned_fact(user.id, "Prefers concise summaries")  # duplicate
    memory_service.add_learned_fact(user.id, "Follows quarterly earnings closely")

    updated = memory_service.get_user_by_id(user.id)
    facts = updated.profile()["learned_facts"]
    assert facts.count("Prefers concise summaries") == 1
    assert "Follows quarterly earnings closely" in facts


def test_mark_onboarded_sets_stage_and_briefing_hour():
    user = memory_service.get_or_create_user("111", "Cy", "cy")
    memory_service.mark_onboarded(user.id, briefing_hour=9)

    updated = memory_service.get_user_by_id(user.id)
    assert updated.onboarding_stage == "done"
    assert updated.briefing_hour_local == 9
