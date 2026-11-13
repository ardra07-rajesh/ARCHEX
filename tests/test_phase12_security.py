from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.database.session import SessionLocal
from app.database.models import Experiment, SecurityAuditEvent, User
from sqlalchemy import delete, select

client = TestClient(app)


def register(email: str, name: str):
    response = client.post("/api/v1/auth/register", json={
        "email": email, "display_name": name, "password": "SecureResearch2026"
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_registration_login_and_password_hashing():
    result = register("phase12-user@example.test", "Research User")
    assert result["token_type"] == "bearer"
    assert result["user"]["role"] == "researcher"
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "phase12-user@example.test"))
        assert user and user.password_hash != "SecureResearch2026"
        assert user.password_hash.startswith("pbkdf2_sha256$")
    login = client.post("/api/v1/auth/login", json={"email":"phase12-user@example.test","password":"SecureResearch2026"})
    assert login.status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Authorization":f"Bearer {login.json()['access_token']}"}).status_code == 200


def test_invalid_login_does_not_disclose_account_existence():
    a = client.post("/api/v1/auth/login", json={"email":"missing@example.test","password":"wrong"})
    b = client.post("/api/v1/auth/login", json={"email":"phase12-user@example.test","password":"wrong"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"]["code"] == b.json()["detail"]["code"] == "invalid_credentials"


def test_research_records_are_isolated_between_authenticated_users():
    one = register("owner-one@example.test", "Owner One")
    two = register("owner-two@example.test", "Owner Two")
    h1 = {"Authorization":f"Bearer {one['access_token']}"}
    h2 = {"Authorization":f"Bearer {two['access_token']}"}
    created = client.post("/api/v1/research/experiments", headers=h1, json={
        "name":"Private experiment", "simulation":"cpu", "config":{"program":"HALT"}
    })
    assert created.status_code == 200, created.text
    experiment_id = created.json()["id"]
    assert client.get(f"/api/v1/research/experiments/{experiment_id}", headers=h1).status_code == 200
    assert client.get(f"/api/v1/research/experiments/{experiment_id}", headers=h2).status_code == 404
    assert client.get("/api/v1/research/experiments", headers=h2).json()["total"] == 0


def test_auth_required_blocks_unauthenticated_api_but_keeps_login_public(monkeypatch):
    monkeypatch.setattr(settings, "auth_required", True)
    assert client.get("/api/v1/dashboard/summary").status_code == 401
    assert client.get("/api/v1/auth/config").status_code == 200
    assert client.post("/api/v1/auth/login", json={"email":"missing@example.test","password":"wrong"}).status_code == 401
    monkeypatch.setattr(settings, "auth_required", False)


def test_viewer_role_is_read_only():
    account = register("phase12-viewer@example.test", "Read Only")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "phase12-viewer@example.test"))
        user.role = "viewer"; db.commit()
    response = client.post("/api/v1/architecture/simulate", headers={"Authorization":f"Bearer {account['access_token']}"}, json={"program":"HALT"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "read_only_role"


def test_reports_and_assistant_conversations_are_owner_scoped():
    one = register("research-owner@example.test", "Research Owner")
    two = register("research-outsider@example.test", "Research Outsider")
    h1 = {"Authorization":f"Bearer {one['access_token']}"}
    h2 = {"Authorization":f"Bearer {two['access_token']}"}
    exp = client.post("/api/v1/research/experiments", headers=h1, json={
        "name":"Owned CPU", "simulation":"cpu", "config":{"program":"HALT","num_registers":8,"forwarding":True,"max_cycles":100,"memory_size_words":64,"clock_mhz":100}
    }).json()
    assert client.post("/api/v1/reports/generate", headers=h2, json={"experiment_id":exp["id"],"format":"json"}).status_code == 404
    report = client.post("/api/v1/reports/generate", headers=h1, json={"experiment_id":exp["id"],"format":"json"})
    assert report.status_code == 200, report.text
    rid = report.json()["id"]
    assert client.get(f"/api/v1/reports/{rid}", headers=h1).status_code == 200
    assert client.get(f"/api/v1/reports/{rid}", headers=h2).status_code == 404
    conversation = client.post("/api/v1/assistant/conversations", headers=h1, json={"title":"Private thread"}).json()
    assert client.get(f"/api/v1/assistant/conversations/{conversation['id']}", headers=h2).status_code == 404


def test_admin_can_manage_roles_and_review_audit():
    admin = register("phase12-admin@example.test", "Admin Candidate")
    target = register("phase12-target@example.test", "Target Researcher")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "phase12-admin@example.test"))
        user.role = "admin"; db.commit()
    headers = {"Authorization":f"Bearer {admin['access_token']}"}
    users = client.get("/api/v1/auth/admin/users", headers=headers)
    assert users.status_code == 200 and any(row["email"] == "phase12-target@example.test" for row in users.json())
    target_id = next(row["id"] for row in users.json() if row["email"] == "phase12-target@example.test")
    changed = client.patch(f"/api/v1/auth/admin/users/{target_id}?role=viewer", headers=headers)
    assert changed.status_code == 200 and changed.json()["role"] == "viewer"
    audit = client.get("/api/v1/auth/admin/audit", headers=headers)
    assert audit.status_code == 200 and isinstance(audit.json(), list)
