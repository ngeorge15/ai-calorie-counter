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
