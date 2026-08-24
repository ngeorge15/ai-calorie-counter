"""Sync semantics — the parts that fail silently if they're wrong."""
import datetime as dt


def _meal(client_id, **overrides):
    base = {
        "client_id": client_id,
        "name": "Chicken bowl",
        "calories": 400,
        "eaten_at": "2026-08-24T12:30:00+00:00",
        "meal_type": "lunch",
        "source": "manual",
    }
    base.update(overrides)
    return base


def _sync(client, auth, changes=None, since=None):
    body = {"changes": changes or []}
    if since:
        body["since"] = since
    response = client.post("/api/meals/sync", json=body, headers=auth)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_push_then_pull_roundtrip(client, auth):
    result = _sync(client, auth, [_meal("meal-0001-aaaa")])
    assert result["applied"] == ["meal-0001-aaaa"]

    listing = client.get("/api/meals", headers=auth).get_json()
    assert [m["name"] for m in listing["meals"]] == ["Chicken bowl"]


def test_repeated_push_is_idempotent(client, auth):
    """A retried push after a network hiccup must not duplicate the meal."""
    meal = _meal("meal-0001-aaaa", updated_at="2026-08-24T12:30:00+00:00")
    _sync(client, auth, [meal])
    _sync(client, auth, [meal])

    listing = client.get("/api/meals", headers=auth).get_json()
    assert len(listing["meals"]) == 1


def test_stale_edit_loses_to_newer_server_copy(client, auth):
    """Last-write-wins: an older edit arriving late must not clobber."""
    _sync(client, auth, [_meal("meal-0001-aaaa", calories=600,
                               updated_at="2026-08-24T12:45:00+00:00")])

    result = _sync(client, auth, [_meal("meal-0001-aaaa", calories=400,
                                        updated_at="2026-08-24T12:30:00+00:00")])

    assert result["applied"] == []
    assert len(result["conflicts"]) == 1
    # The server hands back its winning copy so the client can converge.
    assert result["conflicts"][0]["calories"] == 600


def test_fast_client_clock_cannot_skip_server_changes(client, auth, app):
    """The clock-domain rule, enforced.

    A phone running an hour fast pushes a meal stamped in the future. If the
    pull cursor came from that client clock, every server change written in the
    intervening hour would become permanently invisible. The cursor must come
    from the server, so nothing is skipped.
    """
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()

    result = _sync(client, auth, [_meal("meal-fast-aaaa", updated_at=future)])
    cursor = result["server_time"]

    # A change lands server-side now — an hour BEHIND the client's stamp.
    from app.db import get_db
    from app.timeutil import utcnow
    get_db().meals.insert_one({
        "user_id": get_db().users.find_one()["_id"],
        "client_id": "meal-other-device",
        "name": "Apple", "calories": 95,
        "eaten_at": "2026-08-24T15:00:00+00:00",
        "deleted": False,
        "updated_at": utcnow(),
        "server_updated_at": utcnow(),
    })

    pulled = _sync(client, auth, since=cursor)
    names = {m["client_id"] for m in pulled["changes"]}
    assert "meal-other-device" in names, (
        "server change was skipped — cursor is using the client clock"
    )


def test_delete_propagates_as_tombstone(client, auth):
    """A hard delete would never reach the other device."""
    _sync(client, auth, [_meal("meal-0001-aaaa")])
    assert client.delete("/api/meals/meal-0001-aaaa", headers=auth).status_code == 200

    assert client.get("/api/meals", headers=auth).get_json()["meals"] == []

    # But it must still appear in sync, flagged, so other devices learn of it.
    pulled = _sync(client, auth)
    tombstone = next(m for m in pulled["changes"] if m["client_id"] == "meal-0001-aaaa")
    assert tombstone["deleted"] is True
