"""Tests for phase9.unmatched_clustering (milestone 10).

No DB, no phase7 teaching loop involved -- just the pure grouping step
that sits in front of it.
"""
from phase9.unmatched_clustering import cluster_unmatched_lines, find_cluster_for_line, skeleton_of


def _u(raw_line, line_number, context_path):
    return {"raw_line": raw_line, "line_number": line_number, "context_path": context_path}


def test_similar_shaped_lines_in_same_context_cluster_together():
    unmatched = [
        _u("ip access-group VLAN-MGMT in", 10, "interfaces"),
        _u("ip access-group CORE-RESTRICT in", 22, "interfaces"),
        _u("ip access-group DMZ-ACL in", 31, "interfaces"),
    ]
    clusters = cluster_unmatched_lines(unmatched)
    assert len(clusters) == 1
    assert clusters[0].count == 3
    assert clusters[0].context_category == "interfaces"


def test_different_shapes_do_not_merge():
    unmatched = [
        _u("ip access-group VLAN-MGMT in", 10, "interfaces"),
        _u("management api http-commands", 40, "management"),
    ]
    clusters = cluster_unmatched_lines(unmatched)
    assert len(clusters) == 2


def test_fortios_shared_regex_gotcha_stays_separated_by_context():
    """Section 6 of the Phase 9 plan: `set server \\S+` matches both
    syslog and NTP lines in FortiOS. Same skeleton, different block --
    clustering must not merge them, or teaching one would silently
    generalize over the other."""
    unmatched = [
        _u("set server 10.0.0.5", 5, "log_syslogd_setting"),
        _u("set server 10.0.0.6", 6, "log_syslogd_setting"),
        _u("set server 10.0.0.5", 40, "system_ntp"),
        _u("set server 10.0.0.9", 41, "system_ntp"),
    ]
    clusters = cluster_unmatched_lines(unmatched)
    assert len(clusters) == 2
    contexts = {c.context_category for c in clusters}
    assert contexts == {"log_syslogd_setting", "system_ntp"}
    for c in clusters:
        assert c.count == 2


def test_result_ordered_largest_cluster_first():
    unmatched = [
        _u("no shutdown lacp", 1, "interfaces"),
        _u("no shutdown lacp", 2, "interfaces"),
        _u("snmp-server user v3 auth", 3, "snmp"),
    ]
    clusters = cluster_unmatched_lines(unmatched)
    assert clusters[0].count == 2
    assert clusters[0].skeleton == skeleton_of("no shutdown lacp")


def test_find_cluster_for_line():
    unmatched = [_u("ip access-group VLAN-MGMT in", 10, "interfaces")]
    clusters = cluster_unmatched_lines(unmatched)
    found = find_cluster_for_line(clusters, "ip access-group VLAN-MGMT in")
    assert found is not None
    assert find_cluster_for_line(clusters, "totally different line") is None


def test_empty_input_yields_no_clusters():
    assert cluster_unmatched_lines([]) == []


def test_blank_lines_are_skipped():
    unmatched = [_u("   ", 1, "interfaces"), _u("ip access-group VLAN-MGMT in", 2, "interfaces")]
    clusters = cluster_unmatched_lines(unmatched)
    assert len(clusters) == 1
    assert clusters[0].count == 1
