from shared.enums import Policy
from worker.normalize import decide_route


def test_auto_routes_to_publish():
    assert decide_route(Policy.auto, False) == "publish"


def test_queue_routes_to_draft():
    assert decide_route(Policy.queue, False) == "draft"


def test_duplicate_short_circuits_regardless_of_policy():
    assert decide_route(Policy.auto, True) == "duplicate"
    assert decide_route(Policy.queue, True) == "duplicate"
