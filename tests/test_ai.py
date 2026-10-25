"""The optional "Bring your own Claude" features, with a fake client: the real API is never called."""
import json
from types import SimpleNamespace

import pytest

from inbox_ledger import ai, cli
from inbox_ledger.parsing import RawMessage

from .helpers import card


def alert(id: str, merchant: str = "BLUE DOOR CAFE", amount: str = "42.50", date="2026-10-20T08:00:00Z"):
    body = (f"Dear customer, AED {amount} was spent on your Emirates card ending 1234 at {merchant} on 20/10/2026 "
            "12:05. Visit https://bank.example/track?id=99 for details. Do not reply to this email. "
            "Unsubscribe here. Reference 123456789012")
    return RawMessage(id, date, "alerts@exampleBank.com", "Card transaction alert", body)


def newsletter(id: str):
    return RawMessage(id, "2026-10-21T08:00:00Z", "news@exampleBank.com", "Our October newsletter",
                      "Read our latest tips about saving. See you next month!")


def result(alias, **kw):
    base = dict(id=alias, is_transaction=True, kind="card_purchase", direction="out", amount=42.5, currency="AED",
                merchant_or_counterparty="BLUE DOOR CAFE", account_last4="1234", occurred_at="2026-10-20T12:05",
                confidence=0.95)
    return {**base, **kw}


class FakeClient:
    """Minimal stand-in for anthropic.Anthropic(): replies are queued; every request is recorded."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        reply = self.replies.pop(0)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=300, output_tokens=40))


@pytest.fixture
def ai_on(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX_LEDGER_DATA", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    (tmp_path / "ai.json").write_text('{"enabled": true}')
    return tmp_path


def test_enabled_needs_key_and_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX_LEDGER_DATA", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not ai.enabled()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert not ai.enabled()  # key alone is not consent
    (tmp_path / "ai.json").write_text('{"enabled": false}')
    assert not ai.enabled()
    (tmp_path / "ai.json").write_text("not json")
    assert not ai.enabled()
    (tmp_path / "ai.json").write_text('{"enabled": true}')
    assert ai.enabled()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert not ai.enabled()  # opt-in alone is not enough either


def test_nothing_is_sent_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX_LEDGER_DATA", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # no ai.json: not opted in
    client = FakeClient(*[{"results": []}] * 3)
    assert ai.extract([alert("a1")], client=client) == {}
    with pytest.raises(ai.AIError):
        ai.draft_profile([alert("a1")], "Example", client=client)
    assert client.calls == []


def test_prompt_is_small_and_redacted(ai_on):
    client = FakeClient({"results": [result("m1")]})
    ai.extract([alert("a1")], client=client)
    sent = json.dumps(client.calls[0])
    for leaked in ("https://", "bank.example", "exampleBank.com", "123456789012", "Unsubscribe", '"a1"', "sender"):
        assert leaked not in sent, leaked
    assert "BLUE DOOR CAFE" in sent and "ending 1234" in sent
    assert client.calls[0]["model"] == "claude-haiku-5-5"
    assert client.calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_model_override(ai_on, monkeypatch):
    monkeypatch.setenv("LEDGER_AI_MODEL", "claude-sonnet-5-5")
    client = FakeClient({"results": [result("m1")]})
    ai.extract([alert("a1")], client=client)
    assert client.calls[0]["model"] == "claude-sonnet-5-5"


def test_extract_cache_rebuild_produces_transactions(ai_on, store):
    store.add_messages([card("c1", "TALABAT DUBAI AE"), alert("a1"), newsletter("n1")])
    assert store.rebuild()["unparsed"] == 2
    todo = ai.candidates(store)
    assert [m.id for m in todo] == ["a1"]  # the newsletter has no amount: it never leaves the machine

    client = FakeClient({"results": [result("m1")]})
    usage = ai.Usage()
    store.ai_put(ai.extract(todo, client=client, usage=usage))
    assert (usage.requests, usage.input_tokens, usage.output_tokens, usage.failed) == (1, 300, 40, 0)

    out = store.rebuild()
    assert out["ai"] == 1 and out["transactions"] == 2 and out["unparsed"] == 1
    t = next(t for t in store.transactions() if t["pattern"] == "ai")
    assert (t["amount"], t["currency"], t["account"], t["direction"]) == (42.5, "AED", "1234", "out")
    assert t["occurred_at"] == "2026-10-20T12:05" and t["merchant"]
    assert t["extra"]["source"] == "ai" and t["extra"]["confidence"] == 0.95

    assert ai.candidates(store) == []  # cached: this email is never sent twice
    ai_calls = len(client.calls)
    store.rebuild()
    assert len(client.calls) == ai_calls  # rebuild never touches the network


def test_negative_and_low_confidence_answers_are_cached_but_not_transactions(ai_on, store):
    store.add_messages([alert("a1"), alert("a2", merchant="MAYBE SHOP")])
    todo = ai.candidates(store)
    client = FakeClient({"results": [
        result("m1", is_transaction=False, kind="none", direction="none", amount=0, currency=""),
        result("m2", confidence=0.2)]})
    store.ai_put(ai.extract(todo, client=client))
    assert set(store.ai_cached()) == {"a1", "a2"} and ai.candidates(store) == []
    assert store.rebuild()["transactions"] == 0


def test_bad_values_are_downgraded_and_missing_answers_retried(ai_on, store):
    store.add_messages([alert("a1"), alert("a2")])
    todo = ai.candidates(store)
    ids = {m.id: f"m{i}" for i, m in enumerate(todo, 1)}  # newest first; both have the same date
    client = FakeClient({"results": [result(ids["a1"], amount=-5)]})  # a2 gets no answer
    usage = ai.Usage()
    got = ai.extract(todo, client=client, usage=usage)
    assert got["a1"]["is_transaction"] is False and "a2" not in got and usage.failed == 1


def test_draft_profile_validates_and_retries(ai_on):
    samples = [alert("a1"), alert("a2", merchant="GREEN GROCER", amount="9.00")]
    bad = "name: Example\nsenders: ['examplebank\\.com$']\ntimezone: Asia/Dubai\npatterns:\n" \
          "  - {name: p, kind: card_purchase, direction: out, regex: 'NEVER MATCHES (?P<amount>[\\d,]*\\.\\d{2})'}\n"
    good = ("```yaml\nname: Example\nsenders: ['examplebank\\.com$']\ntimezone: Asia/Dubai\npatterns:\n"
            "  - name: card_purchase\n    kind: card_purchase\n    direction: out\n"
            "    regex: 'AED (?P<amount>[\\d,]*\\.\\d{2}) was spent on your Emirates card ending (?P<last4>\\d{4}) "
            "at (?P<merchant>.+?) on '\n```")
    client = FakeClient(bad, good)
    text = ai.draft_profile(samples, "Example", client=client)
    assert "```" not in text and len(client.calls) == 2
    retry = client.calls[1]["messages"]
    assert retry[-1]["role"] == "user" and "was not parsed" in retry[-1]["content"]  # the error is fed back
    assert ai.validate_profile(text, samples) is None


def test_draft_profile_gives_up_after_one_retry(ai_on):
    broken = "name: X\npatterns:\n  - {name: p, kind: card_purchase, regex: '(unclosed (?P<amount>\\d+)'}\n"
    client = FakeClient(broken, broken, broken)
    with pytest.raises(ai.AIError) as e:
        ai.draft_profile([alert("a1")], "X", client=client)
    assert len(client.calls) == 2 and e.value.draft == broken


def test_validate_profile_rejects_bad_specs():
    s = [alert("a1")]
    assert "name" in ai.validate_profile("- just a list", s)
    assert "kind" in ai.validate_profile("name: X\npatterns: [{name: p, kind: nope, regex: '(?P<amount>1)'}]", s)
    assert "amount" in ai.validate_profile("name: X\npatterns: [{name: p, kind: transfer, regex: 'x'}]", s)
    assert "sender" in ai.validate_profile(
        "name: X\nsenders: ['other\\.com$']\npatterns: [{name: p, kind: transfer, regex: 'AED (?P<amount>[\\d.]+)'}]", s)


def args(**kw):
    return SimpleNamespace(**{"yes": False, "dry_run": False, "limit": 100, "force": False, "out": None, **kw})


def test_cli_ai_read_refuses_without_confirmation(ai_on, monkeypatch, capsys):
    store = cli.open_store()
    store.add_messages([alert("a1")])
    client = FakeClient({"results": [result("m1")]})
    monkeypatch.setattr(ai, "_client", lambda: client)

    with pytest.raises(SystemExit) as e:  # no tty (pytest) and no --yes
        cli.cmd_ai_read(args())
    assert "Nothing was sent" in str(e.value)

    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *_: "n")  # interactive "no"
    with pytest.raises(SystemExit):
        cli.cmd_ai_read(args())
    assert client.calls == [] and cli.open_store().ai_cached() == {}

    cli.cmd_ai_read(args(dry_run=True))  # dry run shows the text and sends nothing
    assert client.calls == []
    assert "BLUE DOOR CAFE" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda *_: "y")  # interactive "yes"
    cli.cmd_ai_read(args())
    out = capsys.readouterr().out
    assert len(client.calls) == 1 and "1 transactions" in out and "input / 40 output tokens" in out
    assert cli.open_store().transactions()[0]["pattern"] == "ai"


def test_cli_ai_read_yes_flag_and_disabled(ai_on, monkeypatch):
    cli.open_store().add_messages([alert("a1")])
    client = FakeClient({"results": [result("m1")]})
    monkeypatch.setattr(ai, "_client", lambda: client)
    cli.cmd_ai_read(args(yes=True))
    assert len(client.calls) == 1

    (ai_on / "ai.json").write_text('{"enabled": false}')
    with pytest.raises(SystemExit) as e:
        cli.cmd_ai_read(args(yes=True))
    assert "AI is off" in str(e.value) and len(client.calls) == 1


def test_cli_ai_profile_saves_validated_profile(ai_on, monkeypatch):
    cli.open_store().add_messages([alert("a1"), alert("a2", merchant="GREEN GROCER", amount="9.00")])
    good = ("name: Example\nsenders: ['examplebank\\.com$']\ntimezone: Asia/Dubai\npatterns:\n"
            "  - name: card_purchase\n    kind: card_purchase\n    direction: out\n"
            "    regex: 'AED (?P<amount>[\\d,]*\\.\\d{2}) was spent on your Emirates card ending (?P<last4>\\d{4}) "
            "at (?P<merchant>.+?) on '\n")
    client = FakeClient(good)
    monkeypatch.setattr(ai, "_client", lambda: client)
    with pytest.raises(SystemExit):
        cli.cmd_ai_profile(args(bank="Example Bank", sender="examplebank"))
    assert client.calls == [] and not (ai_on / "banks").exists()

    cli.cmd_ai_profile(args(bank="Example Bank", sender="examplebank", yes=True))
    saved = ai_on / "banks" / "example-bank.yaml"
    assert saved.exists() and "Sender: alerts@" in json.dumps(client.calls[0]["messages"])
    assert [t["pattern"] for t in cli.open_store().transactions()] == ["card_purchase"] * 2

    with pytest.raises(SystemExit):  # never overwrite silently
        cli.cmd_ai_profile(args(bank="Example Bank", sender="examplebank", yes=True))
