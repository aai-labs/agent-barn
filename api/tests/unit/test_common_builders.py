from uuid import UUID

from hamcrest import assert_that, equal_to, has_entries, none

from api.domains.agents.builders import build_pvc
from api.domains.agents.builders.common import build_service

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_NS = "agent-farm"


def test_build_pvc_sets_storage_class_when_provided():
    pvc = build_pvc(_AGENT_ID, _ORG_ID, _NS, "rook-ceph-block-main")
    assert_that(pvc.spec.storage_class_name, equal_to("rook-ceph-block-main"))


def test_build_pvc_omits_storage_class_when_none():
    pvc = build_pvc(_AGENT_ID, _ORG_ID, _NS)
    assert_that(pvc.spec.storage_class_name, none())


def test_build_pvc_treats_empty_string_as_cluster_default():
    pvc = build_pvc(_AGENT_ID, _ORG_ID, _NS, "")
    assert_that(pvc.spec.storage_class_name, none())


def test_labels_include_stable_agent_component_label():
    service = build_service(_AGENT_ID, _ORG_ID, _NS)
    assert_that(
        service.metadata.labels,
        has_entries(
            {
                "app": f"agent-{_AGENT_ID}",
                "org-id": str(_ORG_ID),
                "agentfarm.io/component": "agent",
            }
        ),
    )
    pvc = build_pvc(_AGENT_ID, _ORG_ID, _NS)
    assert_that(pvc.metadata.labels, has_entries({"agentfarm.io/component": "agent"}))


def test_service_selector_stays_on_app_label_only():
    service = build_service(_AGENT_ID, _ORG_ID, _NS)
    assert_that(service.spec.selector, equal_to({"app": f"agent-{_AGENT_ID}"}))
