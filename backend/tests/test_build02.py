"""Meaningful API and domain scenarios for the BUILD 02 intelligence foundation."""
from app.services.questions import score_question
from app.models.question import QuestionCategory, QuestionPriority


def project(client, name="Build 02"):
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def intent(client, project_id, raw="Create a landing page for my SaaS."):
    response = client.post(f"/api/v1/projects/{project_id}/intent", json={"raw_request": raw})
    assert response.status_code == 201, response.text
    return response.json()


def direction_ready_intent(client, project_id):
    result = intent(client, project_id, "Create a luxury fragrance ecommerce website for luxury fragrance consumers. Users should discover and purchase the fragrance.")
    update = client.put(f"/api/v1/projects/{project_id}/intent", json={"required_features":["product discovery", "product comparison", "checkout"]})
    assert update.status_code == 200, update.text
    return update.json()


def test_create_intent_keeps_original_request(client):
    pid = project(client)
    result = intent(client, pid)
    assert result["raw_request"] == "Create a landing page for my SaaS."
    assert result["project_type"] == "landing page"
    assert result["status"] == "needs_questions"
    assert client.get(f"/api/v1/projects/{pid}/intent").status_code == 200


def test_extracts_known_noir_fields_without_provider(client):
    pid = project(client)
    result = intent(client, pid, "Create a luxury fragrance website for NOIR with a cinematic black and champagne-gold aesthetic. I want users to discover the fragrance and eventually purchase it.")
    assert result["project_type"] == "ecommerce website"
    assert result["business_or_product_goal"] == "Brand or product discovery and purchase"
    assert result["desired_user_action"] == "Discover the product, evaluate it, then purchase"
    assert "fragrance" in result["industry"]
    assert any("NOIR" in item for item in result["brand_requirements"])
    assert "cinematic" in result["visual_preferences"]
    assert result["primary_audience"] == "Luxury fragrance consumers"


def test_unknown_goal_audience_and_action_remain_unknown(client):
    pid = project(client)
    result = intent(client, pid, "Build a website.")
    assert result["business_or_product_goal"] is None
    assert result["primary_audience"] is None
    assert result["desired_user_action"] is None
    assert result["completeness"] < 1

def test_inferred_audience_is_not_counted_as_confirmed_completeness(client):
    pid = project(client)
    result = intent(client, pid, "Create a luxury fragrance website for NOIR.")
    assert result["primary_audience"] == "Luxury fragrance consumers"
    assert result["provenance"]["field_sources"]["primary_audience"]["source_type"] == "inferred"
    assert "primary audience" in client.post(f"/api/v1/projects/{pid}/intent/analyze").json()["missing_information"]


def test_analyze_generates_a_small_idempotent_question_set(client):
    pid = project(client)
    intent(client, pid)
    generated = client.get(f"/api/v1/projects/{pid}/questions/open").json()
    first = client.post(f"/api/v1/projects/{pid}/intent/analyze")
    second = client.post(f"/api/v1/projects/{pid}/intent/analyze")
    assert first.status_code == second.status_code == 200
    assert 1 <= len(generated) <= 4
    assert first.json()["generated_questions"] == 0
    assert second.json()["generated_questions"] == 0
    questions = client.get(f"/api/v1/projects/{pid}/questions/open").json()
    assert len(questions) <= 4
    assert len({q["question"] for q in questions}) == len(questions)
    assert all("border radius" not in q["question"].lower() for q in questions)


def test_question_priorities_follow_deterministic_impact(client):
    pid = project(client)
    intent(client, pid)
    rows = client.get(f"/api/v1/projects/{pid}/questions/open").json()
    scores = [row["impact_score"] for row in rows]
    assert scores == sorted(scores, reverse=True)
    score, priority, _ = score_question(QuestionCategory.GOAL)
    assert score >= 90 and priority == QuestionPriority.CRITICAL
    score, priority, _ = score_question(QuestionCategory.BRANDING)
    assert 45 <= score < 70 and priority == QuestionPriority.MEDIUM


def test_answer_updates_target_intent_field_and_provenance(client):
    pid = project(client)
    intent(client, pid)
    question = next(q for q in client.get(f"/api/v1/projects/{pid}/questions/open").json() if q["intent_field"] == "desired_user_action")
    result = client.post(f"/api/v1/projects/{pid}/questions/{question['id']}/answer", json={"answer": "Start a free trial"})
    assert result.status_code == 200 and result.json()["status"] == "answered"
    updated = client.get(f"/api/v1/projects/{pid}/intent").json()
    assert updated["desired_user_action"] == "Start a free trial"
    assert updated["provenance"]["field_sources"]["desired_user_action"]["source_type"] == "user_answer"

def test_business_outcome_question_appears_when_action_is_known_but_goal_is_not(client):
    pid = project(client)
    intent(client, pid, "Create a website that lets visitors sign up.")
    questions = client.get(f"/api/v1/projects/{pid}/questions/open").json()
    assert any(q["intent_field"] == "business_or_product_goal" for q in questions)

def test_goal_question_unblocks_only_after_missing_outcome_is_clarified(client):
    pid = project(client)
    intent(client, pid)
    action_question = next(q for q in client.get(f"/api/v1/projects/{pid}/questions/open").json() if q["intent_field"] == "desired_user_action")
    client.post(f"/api/v1/projects/{pid}/questions/{action_question['id']}/answer", json={"answer":"Start a free trial"})
    generated = client.post(f"/api/v1/projects/{pid}/intent/analyze").json()
    assert "business or product goal" in generated["missing_information"]
    assert any(q["intent_field"] == "business_or_product_goal" for q in client.get(f"/api/v1/projects/{pid}/questions/open").json())


def test_intent_update_recomputes_completeness(client):
    pid = project(client)
    initial = intent(client, pid)
    response = client.put(f"/api/v1/projects/{pid}/intent", json={"primary_audience": "Independent designers"})
    assert response.status_code == 200
    assert response.json()["completeness"] > initial["completeness"]
    assert response.json()["provenance"]["field_sources"]["primary_audience"]["created_by"] == "user"


def test_new_intent_supersedes_old_open_questions(client):
    pid = project(client)
    intent(client, pid)
    before = client.get(f"/api/v1/projects/{pid}/questions/open").json()
    assert before
    intent(client, pid, "Create a portfolio site.")
    all_questions = client.get(f"/api/v1/projects/{pid}/questions").json()
    assert any(q["status"] == "superseded" for q in all_questions)


def test_research_plan_is_built_from_known_commerce_intent(client):
    pid = project(client)
    intent(client, pid, "Build a luxury fragrance ecommerce website for users to discover and purchase fragrance.")
    response = client.post(f"/api/v1/projects/{pid}/research-plan")
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["status"] == "draft"
    areas = {query["research_area"] for query in plan["queries"]}
    assert {"Product discovery", "Checkout usability", "Accessibility"} <= areas
    assert len(plan["queries"]) >= 8


def test_research_evidence_defaults_to_untrusted_and_has_provenance(client):
    pid = project(client)
    intent(client, pid)
    response = client.post(f"/api/v1/projects/{pid}/research", json={"title":"Reference page", "claim":"The page uses product comparison.", "source_type":"user_reference", "source_url":"https://example.test/ref", "evidence":"Observed comparison table."})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["trust"] == "untrusted"
    assert data["provenance"]["source_type"] == "user_provided_research"
    assert data["provenance"]["source_reference"] == "https://example.test/ref"
    assert client.get(f"/api/v1/projects/{pid}/research").json()[0]["id"] == data["id"]


def test_client_cannot_assign_research_evidence_trust(client):
    pid = project(client)
    intent(client, pid)
    response = client.post(f"/api/v1/projects/{pid}/research", json={"title":"Standard", "claim":"A test claim", "source_type":"accessibility_standard", "evidence":"A relevant passage", "trust":"authoritative", "confidence":0.9})
    assert response.status_code == 201 and response.json()["trust"] == "untrusted"


def test_requirement_sources_and_provenance_are_distinct(client):
    pid = project(client)
    intent(client, pid, "Create a cinematic website for NOIR.")
    user_req = client.post(f"/api/v1/projects/{pid}/requirements", json={"requirement":"Use cinematic imagery", "category":"visual", "source":"user", "rationale":"Named in request"})
    inferred = client.post(f"/api/v1/projects/{pid}/requirements", json={"requirement":"Use a persistent conversion CTA", "category":"UX", "source":"inferred", "rationale":"Common flow hypothesis"})
    assert user_req.status_code == inferred.status_code == 201
    assert user_req.json()["source"] == "user"
    assert user_req.json()["provenance"]["source_type"] == "user_submitted_requirement"
    assert inferred.json()["source"] == "inferred"
    assert inferred.json()["provenance"]["source_type"] == "user_submitted_inference"
    assert len(client.get(f"/api/v1/projects/{pid}/requirements").json()) == 2


def test_research_requirement_requires_real_project_evidence(client):
    pid = project(client)
    intent(client, pid)
    response = client.post(f"/api/v1/projects/{pid}/requirements", json={"requirement":"Apply pattern", "category":"UX", "source":"research", "rationale":"Research candidate"})
    assert response.status_code == 422


def test_research_evidence_becomes_a_proposed_requirement_candidate(client):
    pid = project(client)
    intent(client, pid)
    evidence = client.post(f"/api/v1/projects/{pid}/research", json={"title":"Finding", "claim":"Relevant pattern", "evidence":"Observed evidence", "related_requirement":"Review this pattern for relevance"}).json()
    response = client.post(f"/api/v1/projects/{pid}/requirements", json={"requirement":evidence["related_requirement"], "category":"UX", "source":"research", "evidence_id":evidence["id"], "rationale":"Evidence-derived candidate"})
    assert response.status_code == 201
    assert response.json()["status"] == "proposed"
    assert response.json()["provenance"]["source_id"] == evidence["id"]


def test_requirement_generation_labels_extraction_and_is_idempotent(client):
    pid = project(client)
    intent(client, pid, "Create a luxury fragrance website for NOIR. Use a cinematic black aesthetic.")
    first = client.post(f"/api/v1/projects/{pid}/requirements/generate")
    second = client.post(f"/api/v1/projects/{pid}/requirements/generate")
    assert first.status_code == 201
    assert any(row["source"] == "user" for row in first.json())
    assert second.json() == []


def test_direction_engine_proposes_multiple_hypotheses_without_selection(client):
    pid = project(client)
    direction_ready_intent(client, pid)
    response = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True})
    assert response.status_code == 201, response.text
    directions = response.json()
    assert len(directions) == 3
    assert {row["status"] for row in directions} == {"proposed"}
    assert len({row["name"] for row in directions}) == 3
    assert client.get(f"/api/v1/projects/{pid}/directions").status_code == 200
    assert client.get(f"/api/v1/projects/{pid}/directions/{directions[0]['id']}").status_code == 200

def test_direction_hypotheses_reference_reliable_research_without_auto_promoting_it(client):
    pid = project(client)
    direction_ready_intent(client, pid)
    evidence = client.post(f"/api/v1/projects/{pid}/research", json={"title":"Research note", "claim":"A study claim", "source_type":"research_paper", "evidence":"Evidence text", "trust":"reliable", "relevance":0.9}).json()
    reviewed = client.post(f"/api/v1/projects/{pid}/research/{evidence['id']}/review", json={"eligible":True,"rationale":"Reviewed for this project"})
    assert reviewed.status_code == 200 and reviewed.json()["trust"] == "reviewed"
    generated = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True})
    assert generated.status_code == 201
    direction = generated.json()[0]
    assert evidence["id"] in direction["supporting_research_ids"]
    assert direction["status"] == "proposed"
    assert direction["visual_language"]["research_context"][0]["trust"] == "reviewed"


def test_manual_direction_creation_is_proposed(client):
    pid = project(client)
    intent(client, pid)
    response = client.post(f"/api/v1/projects/{pid}/directions", json={"name":"User concept", "description":"A human supplied direction"})
    assert response.status_code == 201
    assert response.json()[0]["status"] == "proposed"


def test_direction_assessment_records_tradeoffs_without_aggregate_score(client):
    pid = project(client)
    direction_ready_intent(client, pid)
    direction = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True}).json()[0]
    response = client.post(f"/api/v1/projects/{pid}/directions/{direction['id']}/assessments", json={"criterion":"accessibility", "observation":"The low-density layout may improve scan paths.", "evidence":"This hypothesis has not yet been user tested.", "confidence":0.4, "tradeoff":"Large image areas need contrast and text alternatives."})
    assert response.status_code == 201
    result = response.json()
    assert result["criterion"] == "accessibility"
    assert result["tradeoff"].startswith("Large image")
    assert "score" not in result


def test_direction_selection_is_an_explicit_state_transition(client):
    pid = project(client)
    direction_ready_intent(client, pid)
    direction = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True}).json()[0]
    selected = client.post(f"/api/v1/projects/{pid}/directions/{direction['id']}/select", json={"confirm":True})
    assert selected.status_code == 200 and selected.json()["status"] == "selected"
    assert client.get(f"/api/v1/projects/{pid}/intent").json()["status"] == "approved"
    state = client.get(f"/api/v1/projects/{pid}/design").json()
    assert state["state"]["direction_selection"]["direction_id"] == direction["id"]


def test_direction_selection_creates_user_decision(client):
    pid = project(client)
    direction_ready_intent(client, pid)
    direction = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True}).json()[0]
    client.post(f"/api/v1/projects/{pid}/directions/{direction['id']}/select", json={"confirm":True})
    decisions = client.get(f"/api/v1/projects/{pid}/decisions").json()
    assert len(decisions) == 1
    assert decisions[0]["source"] == "user"
    assert decisions[0]["provenance"]["source_type"] == "user_selection"


def test_direction_selection_creates_user_approved_memory(client):
    pid = project(client)
    direction_ready_intent(client, pid)
    direction = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True}).json()[0]
    client.post(f"/api/v1/projects/{pid}/directions/{direction['id']}/select", json={"confirm":True})
    memory = client.get(f"/api/v1/projects/{pid}/memory").json()
    assert len(memory) == 1 and memory[0]["trust"] == "user_approved"
    assert memory[0]["provenance"]["source_id"] == direction["id"]


def test_direction_selection_creates_version_and_applied_operation(client):
    pid = project(client)
    direction_ready_intent(client, pid)
    direction = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True}).json()[0]
    client.post(f"/api/v1/projects/{pid}/directions/{direction['id']}/select", json={"confirm":True})
    versions = client.get(f"/api/v1/projects/{pid}/versions").json()
    operations = client.get(f"/api/v1/projects/{pid}/operations").json()
    assert len(versions) == 2
    assert len(operations) == 1
    assert operations[0]["operation_type"] == "select_direction"
    assert operations[0]["status"] == "applied"
    assert operations[0]["actor"] == "user"


def test_ai_operation_is_only_a_proposal_and_does_not_mutate_state(client):
    pid = project(client)
    client.post(f"/api/v1/projects/{pid}/design")
    before = client.get(f"/api/v1/projects/{pid}/design").json()
    op = client.post(f"/api/v1/projects/{pid}/operations", json={"operation_type":"update", "actor":"ai", "target":"design_state.pages.0", "property":"title", "old_value":None, "new_value":"Proposed", "reason":"AI suggestion pending human review", "source":"ai_proposal"})
    assert op.status_code == 201 and op.json()["status"] == "proposed"
    after = client.get(f"/api/v1/projects/{pid}/design").json()
    assert after["state"] == before["state"]
    assert after["current_version_id"] == before["current_version_id"]


def test_operation_api_rejects_apply_status(client):
    pid = project(client)
    response = client.post(f"/api/v1/projects/{pid}/operations", json={"operation_type":"update", "actor":"ai", "target":"state.pages.0", "reason":"proposal", "source":"ai_proposal", "status":"applied"})
    assert response.status_code == 422


def test_ai_operation_requires_ai_proposal_provenance(client):
    pid = project(client)
    response = client.post(f"/api/v1/projects/{pid}/operations", json={"operation_type":"update", "actor":"ai", "target":"state.pages.0", "reason":"proposal", "source":"research"})
    assert response.status_code == 422

def test_question_create_skip_and_open_filter_endpoints(client):
    pid = project(client)
    intent(client, pid)
    created = client.post(f"/api/v1/projects/{pid}/questions", json={"question":"Which analytics platform is required?", "category":"technical", "reason":"Affects integration design", "answer_type":"text"})
    assert created.status_code == 201
    skipped = client.patch(f"/api/v1/projects/{pid}/questions/{created.json()['id']}", json={"status":"skipped"})
    assert skipped.status_code == 200 and skipped.json()["status"] == "skipped"
    assert all(row["id"] != created.json()["id"] for row in client.get(f"/api/v1/projects/{pid}/questions/open").json())

def test_direction_selection_requires_explicit_confirmation(client):
    pid = project(client)
    direction_ready_intent(client, pid)
    direction = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True}).json()[0]
    response = client.post(f"/api/v1/projects/{pid}/directions/{direction['id']}/select", json={"confirm":False})
    assert response.status_code == 422

def test_direction_can_be_rejected_but_selection_uses_approval_endpoint(client):
    pid = project(client)
    intent(client, pid)
    direction = client.post(f"/api/v1/projects/{pid}/directions", json={"name":"Option", "description":"A user-supplied concept"}).json()[0]
    selected_by_patch = client.patch(f"/api/v1/projects/{pid}/directions/{direction['id']}", json={"status":"selected"})
    assert selected_by_patch.status_code == 422
    rejected = client.patch(f"/api/v1/projects/{pid}/directions/{direction['id']}", json={"status":"rejected"})
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"

def test_openapi_lists_build02_endpoint_groups(client):
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/v1/projects/{project_id}/intent", "/api/v1/projects/{project_id}/intent/analyze",
        "/api/v1/projects/{project_id}/questions", "/api/v1/projects/{project_id}/questions/open",
        "/api/v1/projects/{project_id}/research", "/api/v1/projects/{project_id}/research-plan",
        "/api/v1/projects/{project_id}/requirements", "/api/v1/projects/{project_id}/requirements/generate",
        "/api/v1/projects/{project_id}/directions", "/api/v1/projects/{project_id}/directions/{direction_id}/select",
        "/api/v1/projects/{project_id}/operations",
    }
    assert expected <= paths.keys()

def test_directions_wait_until_high_impact_intent_fields_are_known(client):
    pid = project(client)
    intent(client, pid, "Build a website.")
    response = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True})
    assert response.status_code == 409
    assert "primary audience" in response.json()["detail"]

def test_direction_generation_waits_for_high_impact_feature_confirmation(client):
    pid = project(client)
    intent(client, pid, "Create a luxury fragrance ecommerce website for luxury fragrance consumers. Users should discover and purchase the fragrance.")
    question = next(q for q in client.get(f"/api/v1/projects/{pid}/questions/open").json() if q["intent_field"] == "required_features")
    assert question["priority"] == "high"
    denied = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True})
    assert denied.status_code == 409
    client.put(f"/api/v1/projects/{pid}/intent", json={"required_features":["discovery", "comparison", "checkout"]})
    accepted = client.post(f"/api/v1/projects/{pid}/directions", json={"generate":True})
    assert accepted.status_code == 201
