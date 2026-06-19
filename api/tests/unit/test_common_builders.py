from uuid import UUID

from hamcrest import assert_that, equal_to, none

from api.domains.agents.builders import build_pvc

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
