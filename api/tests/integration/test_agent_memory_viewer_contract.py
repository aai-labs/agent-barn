"""The memory viewer against the pinned Hindsight 0.10.2 list endpoint, not a stand-in.

These prove what the stand-in tests assume: the tag filter applies before `total` is
counted, search and pagination run inside that filter, and an absent bank is a 404.
"""

from uuid import uuid4

from hamcrest import assert_that, contains_inanyorder, empty, equal_to, greater_than, has_entries, has_item, is_not
from sqlmodel import Session, select

from api.domains.agent_memory.models import AgentMemoryGrant, AgentMemoryPurge
from api.domains.agent_memory.purge import MemoryPurger
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.hindsight_view_backend import hindsight_listing, pinned_hindsight_is_running, retain_in_bank
from api.tests.helpers.memory_backend import memory_viewer_is_served
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.agent_memory import agent_memory_api_setup, memory_is_enabled, purge_tasks_are_clean, two_agents


def test_purge_removes_private_and_shared_documents_without_touching_another_agent_or_bank():
    with given(_setup(two_agents(), purge_tasks_are_clean())) as context:
        bank = _bank(context)
        foreign_bank = f"org-{uuid4()}"
        tag = f"agent:{context.billing.id}"
        for scope in ["private", "team"]:
            retain_in_bank(
                context,
                bank,
                f"Billing {scope} secret",
                [f"author:{context.billing.id}", "scope:team"] if scope == "team" else [tag],
                document_id=f"{tag}:{scope}:seed",
                observation_scopes="per_tag",
            )
        retain_in_bank(
            context,
            bank,
            "Triage stays",
            [f"agent:{context.triage.id}"],
            document_id=f"agent:{context.triage.id}:private:seed",
        )
        retain_in_bank(context, foreign_bank, "Other bank stays", [tag], document_id=f"{tag}:private:seed")
        assert_that(hindsight_listing(context, bank, tag)["total"], greater_than(0))
        with when("Billing is deleted and the cleanup job runs"):
            deleted = context.client.delete(
                f"/api/v1/organizations/{{organization_id}}/agents/{context.billing.id}",
                headers={"Authorization": f"Bearer {context.access_token}"},
            )
            assert_that(deleted.status_code, equal_to(204))
            assert_that(context.injector.get(MemoryPurger).run_once(), equal_to(1))
        with then("only Billing's memories in its Organization are gone"):
            assert_that(hindsight_listing(context, bank, tag), has_entries(total=0, items=empty()))
            assert_that(hindsight_listing(context, bank, f"agent:{context.triage.id}")["total"], greater_than(0))
            assert_that(hindsight_listing(context, foreign_bank, tag)["total"], greater_than(0))
            with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
                task = session.exec(select(AgentMemoryPurge)).one()
                assert_that(task.last_cleaned_at, is_not(equal_to(None)))


_ITEMS = "/api/v1/organizations/{organization_id}/agents/{agent_id}/memory/items"


def _list(context, agent_id, **params):
    return context.client.get(
        _ITEMS.replace("{agent_id}", str(agent_id)),
        params=params,
        headers={"Authorization": f"Bearer {context.access_token}"},
    )


def _bank(context) -> str:
    return f"org-{context.organization.id}"


def _two_agents_share_a_bank():
    def step(context):
        bank = _bank(context)
        context.injector.get(PostgresRepositoryDelegate).save(
            AgentMemoryGrant(organization_id=context.organization.id, agent_id=context.billing.id)
        )
        retain_in_bank(context, bank, "Billing prefers tea", [f"agent:{context.billing.id}"])
        retain_in_bank(context, bank, "Billing 100%_sure", [f"agent:{context.billing.id}", "scope:team"])
        retain_in_bank(context, bank, "Triage prefers coffee", [f"agent:{context.triage.id}"])

    return step


def _setup(*steps):
    return agent_memory_api_setup(pinned_hindsight_is_running(), memory_viewer_is_served(), *steps)


def test_items_and_total_cover_private_and_currently_granted_organization_scopes():
    with given(_setup(two_agents(), _two_agents_share_a_bank())) as context:
        with when("each Agent's memories are viewed through both HTTP boundaries"):
            billing = _list(context, context.billing.id, page_size=50).json()
            triage = _list(context, context.triage.id, page_size=50).json()
            billing_private = hindsight_listing(context, _bank(context), f"agent:{context.billing.id}", match="exact")
            billing_team = hindsight_listing(context, _bank(context), "scope:team")
            billing_upstream = {
                "items": billing_private["items"] + billing_team["items"],
                "total": billing_private["total"] + billing_team["total"],
            }
            triage_upstream = hindsight_listing(context, _bank(context), f"agent:{context.triage.id}", match="exact")

        with then("totals and rows cover exactly the permitted private and Organization scopes"):
            assert_that(billing["total"], equal_to(billing_upstream["total"]))
            assert_that(triage["total"], equal_to(triage_upstream["total"]))
            assert_that(billing["total"], greater_than(0))
            assert_that(
                [item["id"] for item in billing["items"]],
                contains_inanyorder(*[row["id"] for row in billing_upstream["items"]]),
            )
            assert_that([item["id"] for item in billing["items"]], is_not(has_item(triage["items"][0]["id"])))
            assert_that(any("coffee" in item["text"] for item in billing["items"]), equal_to(False))
            assert_that(any("tea" in item["text"] for item in triage["items"]), equal_to(False))

        with then("memories written with the Organization tag are labelled shared"):
            assert_that({item["shared"] for item in billing["items"]}, equal_to({True, False}))
            assert_that({item["shared"] for item in triage["items"]}, equal_to({False}))


def test_search_and_pagination_stay_inside_the_agents_filter():
    with given(_setup(two_agents(), _two_agents_share_a_bank())) as context:
        with when("Billing's memories are searched for another Agent's text and paged"):
            foreign_term = _list(context, context.billing.id, search="coffee").json()
            own_term = _list(context, context.billing.id, search="tea").json()
            full = _list(context, context.billing.id, page_size=50).json()
            first = _list(context, context.billing.id, page=1, page_size=2).json()
            second = _list(context, context.billing.id, page=2, page_size=2).json()

        with then("another Agent's text matches nothing and the total does not leak"):
            assert_that(foreign_term, has_entries(total=0, items=empty()))
            assert_that(own_term["total"], greater_than(0))
            assert_that(any("tea" in item["text"] for item in own_term["items"]), equal_to(True))

        with then("pages keep the same filtered total and do not overlap"):
            assert_that(first["total"], equal_to(full["total"]))
            assert_that(second["total"], equal_to(full["total"]))
            assert_that(len(first["items"]), equal_to(2))
            assert_that({i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}, empty())


def test_search_wildcards_match_literally_against_the_real_endpoint():
    with given(_setup(two_agents(), _two_agents_share_a_bank())) as context:
        # A percent-only fact distinguishes an escaped underscore from a wildcard.
        # A lone underscore may legitimately match generated observation context.
        retain_in_bank(context, _bank(context), "Billing 50% discount", [f"agent:{context.billing.id}"])
        with when("a search consists of SQL wildcard characters"):
            percent = _list(context, context.billing.id, search="%").json()
            paired = _list(context, context.billing.id, search="%_").json()
            literal = _list(context, context.billing.id, search="100%_sure").json()

        with then("only memories containing those characters are found"):
            assert_that(percent["total"], greater_than(paired["total"]))
            assert_that(paired["total"], equal_to(literal["total"]))
            assert_that(any("100%_sure" in item["text"] for item in literal["items"]), equal_to(True))
            assert_that(any("coffee" in item["text"] for item in literal["items"]), equal_to(False))


def test_an_organization_that_never_retained_has_an_empty_page():
    with given(_setup(there_is_an_agent())) as context:
        with when("the Organization's bank does not exist in the real backend"):
            response = _list(context, context.agent.id)

        with then("the page is empty rather than an error"):
            assert_that(response.json(), has_entries(total=0, items=empty()))


def test_organization_viewer_scopes_items_total_search_and_paging_to_shared_memories():
    with given(_setup(two_agents(), _two_agents_share_a_bank())) as context:
        bank = _bank(context)
        retain_in_bank(context, bank, "Triage shared convention", [f"agent:{context.triage.id}", "scope:team"])
        retain_in_bank(context, f"org-{uuid4()}", "Foreign organization shared secret", ["scope:team"])
        url = "/api/v1/organizations/{organization_id}/memory/items"
        auth = {"Authorization": f"Bearer {context.access_token}"}
        page = context.client.get(url, params={"page_size": 50}, headers=auth)
        assert_that(page.status_code, equal_to(200))
        body = page.json()
        expected = hindsight_listing(context, bank, "scope:team")
        assert_that(body["total"], equal_to(expected["total"]))
        assert_that([row["shared"] for row in body["items"]], equal_to([True] * len(body["items"])))
        text = " ".join(row["text"] for row in body["items"])
        for private in ("prefers tea", "prefers coffee", "Foreign organization shared secret"):
            assert_that(private in text, equal_to(False))
        first = context.client.get(url, params={"page_size": 1}, headers=auth).json()
        second = context.client.get(url, params={"page_size": 1, "page": 2}, headers=auth).json()
        assert_that(first["total"], equal_to(body["total"]))
        assert_that(first["items"][0]["id"], is_not(equal_to(second["items"][0]["id"])))
        found = context.client.get(url, params={"search": "100%_sure", "page_size": 50}, headers=auth).json()
        assert_that(found["total"], greater_than(0))
        assert_that(all("100%_sure" in row["text"] for row in found["items"]), equal_to(True))


def test_organization_grants_control_shared_memories_in_the_agent_tab_including_its_own_contributions():
    from api.domains.agent_memory.retag_shared import retag_shared_documents
    from api.infrastructure.hindsight.client import HindsightClient

    with given(_setup(two_agents(), memory_is_enabled())) as context:
        bank = _bank(context)
        reader = context.triage
        tag = f"agent:{reader.id}"
        retain_in_bank(context, bank, "Private triage preference", [tag], document_id=f"{tag}:private:seed")
        retain_in_bank(
            context,
            bank,
            "Organization shared convention",
            [tag, "scope:team"],
            document_id=f"{tag}:team:seed",
            observation_scopes="per_tag",
        )
        retain_in_bank(
            context,
            bank,
            "Another Agent shared convention",
            [f"agent:{context.billing.id}", "scope:team"],
            document_id=f"agent:{context.billing.id}:team:seed",
            observation_scopes="per_tag",
        )
        private = _list(context, reader.id, page_size=50)
        assert_that(private.status_code, equal_to(200))
        assert_that(all(not item["shared"] for item in private.json()["items"]), equal_to(True))
        assert_that(any("Organization shared" in item["text"] for item in private.json()["items"]), equal_to(False))

        # Repairs old source tags via Hindsight's supported document update; this
        # invalidates the observations that used to fan out to the author's private tag.
        assert_that(
            retag_shared_documents(context.injector.get(HindsightClient), context.organization.id, batch_size=1),
            equal_to(2),
        )
        assert_that(retag_shared_documents(context.injector.get(HindsightClient), context.organization.id), equal_to(0))
        grant = AgentMemoryGrant(organization_id=context.organization.id, agent_id=reader.id)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        delegate.save(grant)
        full = _list(context, reader.id, page_size=50).json()
        assert_that(
            any(item["shared"] and "Organization shared" in item["text"] for item in full["items"]), equal_to(True)
        )
        assert_that(any(item["shared"] and "Another Agent" in item["text"] for item in full["items"]), equal_to(True))
        first = _list(context, reader.id, page_size=2).json()
        second = _list(context, reader.id, page_size=2, page=2).json()
        assert_that(first["total"], equal_to(full["total"]))
        assert_that(second["total"], equal_to(full["total"]))
        assert_that(
            [item["id"] for item in first["items"] + second["items"]],
            equal_to([item["id"] for item in full["items"][:4]]),
        )
        # The real recall boundary accepts the gateway's compound scopes too.
        from api.domains.agent_memory.gateway_service import MemoryGatewayService

        gateway = context.injector.get(MemoryGatewayService)
        access = gateway.authenticate(f"Bearer {context.memory_key}")
        recall = gateway.forward(
            access,
            "POST",
            "v1/default/banks/forged/memories/recall",
            {"query": "Organization shared convention", "types": ["world", "experience"], "budget": "high"},
        )
        import json

        recalled = json.loads(recall.content)["results"]
        assert_that(any("scope:team" in row["tags"] for row in recalled), equal_to(True))
        delegate.delete(grant)
        access = gateway.authenticate(f"Bearer {context.memory_key}")
        recall = gateway.forward(
            access,
            "POST",
            "v1/default/banks/forged/memories/recall",
            {"query": "Organization shared convention", "types": ["world", "experience"], "budget": "high"},
        )
        assert_that(
            all("scope:team" not in row["tags"] for row in json.loads(recall.content)["results"]), equal_to(True)
        )
        revoked = _list(context, reader.id, page_size=50).json()
        assert_that(all(not item["shared"] for item in revoked["items"]), equal_to(True))
        assert_that(revoked["total"], equal_to(len(revoked["items"])))
        assert_that(any("Private triage preference" in item["text"] for item in revoked["items"]), equal_to(True))
        assert_that(
            any("Organization shared" in item["text"] or "Another Agent" in item["text"] for item in revoked["items"]),
            equal_to(False),
        )
        shared = context.client.get(
            "/api/v1/organizations/{organization_id}/memory/items",
            headers={"Authorization": f"Bearer {context.access_token}"},
        ).json()
        assert_that(any("Organization shared" in item["text"] for item in shared["items"]), equal_to(True))


def test_shared_retagging_removes_legacy_private_observations_and_keeps_organization_facts():
    from api.domains.agent_memory.retag_shared import retag_shared_documents
    from api.infrastructure.hindsight.client import HindsightClient
    from api.tests.helpers.hindsight_view_backend import consolidate_bank

    with given(_setup(two_agents())) as context:
        bank = _bank(context)
        tag = f"agent:{context.triage.id}"
        retain_in_bank(
            context,
            bank,
            "Legacy organization-only project convention",
            [tag, "scope:team"],
            document_id=f"{tag}:team:seed",
            observation_scopes="per_tag",
        )
        consolidate_bank(context, bank)
        legacy = hindsight_listing(context, bank, tag, match="exact")
        assert_that(any(row["fact_type"] == "observation" for row in legacy["items"]), equal_to(True))
        assert_that(retag_shared_documents(context.injector.get(HindsightClient), context.organization.id), equal_to(1))
        assert_that(hindsight_listing(context, bank, tag), has_entries(total=0, items=empty()))
        assert_that(hindsight_listing(context, bank, "scope:team")["total"], greater_than(0))
        consolidate_bank(context, bank)
        assert_that(hindsight_listing(context, bank, tag), has_entries(total=0, items=empty()))
