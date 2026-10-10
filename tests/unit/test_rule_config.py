from application.rule_config import PREFERENCE_KEY, RULE_IDS, RuleConfigService


class Repository:
    def __init__(self, value=None):
        self.value = value
        self.saved = None

    def initialize(self): pass
    def get_preference(self, key):
        assert key == PREFERENCE_KEY
        return self.value
    def set_preference(self, key, value, ts):
        self.saved = (key, value, ts)
        self.value = value


class Clock:
    def now_iso(self): return "2026-10-09T12:00:00+00:00"


def test_all_rules_are_enabled_by_default_and_with_invalid_data():
    assert RuleConfigService(Repository(), Clock()).enabled_ids() == RULE_IDS
    assert RuleConfigService(Repository("not-json"), Clock()).enabled_ids() == RULE_IDS


def test_disabled_rules_are_persisted_and_filtered():
    repository = Repository()
    service = RuleConfigService(repository, Clock())
    expected = tuple(rule_id for rule_id in RULE_IDS if rule_id != "R07")

    assert service.save_enabled(expected) == expected
    assert repository.saved == (PREFERENCE_KEY, '["R07"]', "2026-10-09T12:00:00+00:00")
    assert service.enabled_ids() == expected
    assert {rule.__name__.upper() for rule in service.enabled_rules()} == set(expected)


def test_unknown_rule_is_rejected():
    try:
        RuleConfigService(Repository(), Clock()).save_enabled((*RULE_IDS, "R99"))
    except ValueError as exc:
        assert "R99" in str(exc)
    else:
        raise AssertionError("R99 should have been rejected")
