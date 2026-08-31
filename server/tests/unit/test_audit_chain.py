import json

from sqlalchemy import update

from yantra_server.db.base import Database
from yantra_server.db.models import AuditRow
from yantra_server.observe.audit_chain import AuditChain


def test_empty_chain_verifies(audit: AuditChain) -> None:
    result = audit.verify()
    assert result.ok and result.entries == 0
    assert audit.head() is None


def test_append_links_and_verifies(audit: AuditChain) -> None:
    first = audit.append("user", "tool.write", {"path": "a.txt"})
    second = audit.append("system", "render", {"doc": "report.docx"})
    assert second.prev_hash == first.hash
    assert second.seq == first.seq + 1
    result = audit.verify()
    assert result.ok and result.entries == 2
    head = audit.head()
    assert head is not None and head.hash == second.hash


def test_payload_tamper_detected(audit: AuditChain, db: Database) -> None:
    audit.append("user", "e1", {"k": 1})
    audit.append("user", "e2", {"k": 2})
    with db.session() as s:
        s.execute(update(AuditRow).where(AuditRow.seq == 1).values(payload={"k": 999}))
    result = audit.verify()
    assert not result.ok
    assert result.first_bad_seq == 1
    assert result.detail == "payload tampered"


def test_link_tamper_detected(audit: AuditChain, db: Database) -> None:
    audit.append("user", "e1", {})
    audit.append("user", "e2", {})
    with db.session() as s:
        s.execute(update(AuditRow).where(AuditRow.seq == 2).values(prev_hash="0" * 64))
    assert not audit.verify().ok


def test_export_jsonl_roundtrip(audit: AuditChain) -> None:
    audit.append("user", "e1", {"x": "y"})
    audit.append("user", "e2", {})
    lines = list(audit.export())
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["event"] == "e1"
    assert parsed[1]["prev_hash"] == parsed[0]["hash"]
    assert [json.loads(line)["seq"] for line in audit.export(from_seq=2)] == [2]


def test_concurrent_appends_stay_consistent(audit: AuditChain) -> None:
    import threading

    def worker(n: int) -> None:
        for i in range(10):
            audit.append("t", f"ev-{n}-{i}", {"n": n, "i": i})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    result = audit.verify()
    assert result.ok and result.entries == 40
