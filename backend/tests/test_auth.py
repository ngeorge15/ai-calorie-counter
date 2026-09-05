def test_register_and_login(client):
    creds = {"email": "N@Example.com ", "password": "hunter2hunter2"}

    registered = client.post("/api/auth/register", json=creds)
    assert registered.status_code == 201
    assert registered.get_json()["token"]

    logged_in = client.post("/api/auth/login", json=creds)
    assert logged_in.status_code == 200
    assert logged_in.get_json()["user_id"] == registered.get_json()["user_id"]


def test_duplicate_email_rejected(client):
    creds = {"email": "n@example.com", "password": "hunter2hunter2"}
    client.post("/api/auth/register", json=creds)
    assert client.post("/api/auth/register", json=creds).status_code == 409


def test_wrong_password_is_indistinguishable_from_unknown_user(client):
    client.post("/api/auth/register",
                json={"email": "n@example.com", "password": "hunter2hunter2"})

    wrong = client.post("/api/auth/login",
                        json={"email": "n@example.com", "password": "wrongwrong"})
    unknown = client.post("/api/auth/login",
                          json={"email": "nobody@example.com", "password": "wrongwrong"})

    # Identical status and body, or the endpoint becomes an email enumerator.
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json() == unknown.get_json()


def test_short_password_rejected_with_reason(client):
    response = client.post("/api/auth/register",
                           json={"email": "n@example.com", "password": "short"})
    assert response.status_code == 422
    assert response.get_json()["detail"][0]["loc"] == ["password"]


def test_meals_require_auth(client):
    assert client.get("/api/meals").status_code == 401


def test_login_rate_limit_triggers_after_repeated_attempts(client):
    creds = {"email": "n@example.com", "password": "hunter2hunter2"}
    client.post("/api/auth/register", json=creds)

    # /login is capped at 10/minute (see app/routes/auth.py). Burn the budget
    # with wrong-password attempts, the shape a brute-force attempt takes.
    wrong = {"email": creds["email"], "password": "wrongwrong"}
    for _ in range(10):
        response = client.post("/api/auth/login", json=wrong)
        assert response.status_code == 401

    limited = client.post("/api/auth/login", json=wrong)
    assert limited.status_code == 429
    body = limited.get_json()
    assert body["error"] == "too many requests"


def test_login_still_works_under_normal_use(client):
    creds = {"email": "n@example.com", "password": "hunter2hunter2"}
    client.post("/api/auth/register", json=creds)

    # A handful of logins (e.g. across devices) should never come close to
    # the 10/minute limit.
    for _ in range(3):
        response = client.post("/api/auth/login", json=creds)
        assert response.status_code == 200


def test_register_rate_limit_triggers_after_repeated_attempts(client):
    # /register is capped at 5/hour per IP (see app/routes/auth.py). Each
    # call uses a distinct email so the limiter — not the duplicate-email
    # check — is what produces the 429.
    for i in range(5):
        response = client.post(
            "/api/auth/register",
            json={"email": f"user{i}@example.com", "password": "hunter2hunter2"},
        )
        assert response.status_code == 201

    limited = client.post(
        "/api/auth/register",
        json={"email": "user-overflow@example.com", "password": "hunter2hunter2"},
    )
    assert limited.status_code == 429
    assert limited.get_json()["error"] == "too many requests"
