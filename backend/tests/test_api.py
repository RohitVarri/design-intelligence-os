"""End-to-end API tests for core BUILD 01 workflows."""
def test_health_and_openapi_startup(client):
    health = client.get("/health")
    assert health.status_code == 200 and health.json() == {"status": "ok"}
    docs = client.get("/openapi.json")
    assert docs.status_code == 200
    assert "/api/v1/projects" in docs.json()["paths"]

def test_project_design_versions_restore_decisions_memory_and_laws(client):
    project = client.post("/api/v1/projects", json={"name": "Studio"})
    assert project.status_code == 201, project.text
    pid = project.json()["id"]
    initial = client.post(f"/api/v1/projects/{pid}/design")
    assert initial.status_code == 201, initial.text
    assert initial.json()["state"]["pages"] == []
    initial_version = initial.json()["current_version_id"]
    state = {"pages": [{"name": "Home", "title": "Welcome"}], "components": [], "design_tokens": {"color": {"primary": "#123456"}}, "ux_navigation": {}, "assets": [], "design_laws": [], "metadata": {}}
    updated = client.put(f"/api/v1/projects/{pid}/design", json={"state": state, "change_summary": "Add homepage"})
    assert updated.status_code == 200, updated.text
    latest = updated.json()["current_version_id"]
    assert latest != initial_version
    compared = client.get(f"/api/v1/projects/{pid}/versions/compare/{initial_version}/{latest}")
    assert compared.status_code == 200, compared.text
    assert "pages" in compared.json()["changes"]
    restored = client.post(f"/api/v1/projects/{pid}/versions/{initial_version}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["state"]["pages"] == []
    versions = client.get(f"/api/v1/projects/{pid}/versions").json()
    assert len(versions) == 3
    decision = client.post(f"/api/v1/projects/{pid}/decisions", json={"source": "user", "title": "Keep it simple", "rationale": "User request"})
    assert decision.status_code == 201 and decision.json()["source"] == "user"
    memory = client.post(f"/api/v1/projects/{pid}/memory", json={"category": "brand", "content": "Use warm colors", "trust": "user_approved"})
    assert memory.status_code == 201
    assert client.get(f"/api/v1/projects/{pid}/memory").json()[0]["trust"] == "user_approved"
    law = client.post(f"/api/v1/projects/{pid}/laws", json={"title": "Contrast", "rule": "Maintain legibility"})
    assert law.status_code == 201
    changed_law = client.patch(f"/api/v1/projects/{pid}/laws/{law.json()['id']}", json={"active": False})
    assert changed_law.status_code == 200 and changed_law.json()["active"] is False
    current = client.get(f"/api/v1/projects/{pid}/design").json()
    assert current["state"]["design_laws"][0]["active"] is False
    assert len(client.get(f"/api/v1/projects/{pid}/versions").json()) == 5

def test_surgical_edit_preserves_other_state(client):
    pid = client.post("/api/v1/projects", json={"name": "Edit"}).json()["id"]
    client.post(f"/api/v1/projects/{pid}/design")
    full = {"pages": [{"title": "Original", "layout": "grid"}], "components": [], "design_tokens": {}, "ux_navigation": {}, "assets": [], "design_laws": [], "metadata": {}}
    client.put(f"/api/v1/projects/{pid}/design", json={"state": full, "change_summary": "seed"})
    response = client.patch(f"/api/v1/projects/{pid}/design/edit", json={"path": "pages.0.title", "value": "Changed", "change_summary": "Rename title"})
    assert response.status_code == 200, response.text
    assert response.json()["state"]["pages"][0] == {"title": "Changed", "layout": "grid"}
    assert response.json()["state"]["components"] == []

def test_missing_project_returns_404(client):
    import uuid
    response = client.post(f"/api/v1/projects/{uuid.uuid4()}/design")
    assert response.status_code == 404
