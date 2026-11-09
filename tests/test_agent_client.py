"""Provider boundaries and source checks, using only synthetic mock responses."""

import asyncio
import json
from copy import deepcopy
from threading import Event, Thread

import httpx
import pytest
from swarmcircuit_server.demo.agents import (
    LIMITATIONS,
    LiveConfig,
    LiveFailure,
    call_model,
    check_draft,
    draft_document,
)
from swarmcircuit_server.demo.fixtures import analyze


def sample_draft():
    return {
        "facts": analyze(),
        "limitations": list(LIMITATIONS),
        "rationale": "The quarterly figures support revenue growth within the sample.",
    }


def provider_body(value, **extra):
    return {
        "model": "provider-reported-test-model",
        "choices": [{"message": {"content": json.dumps(value)}}],
        **extra,
    }


def model_config():
    return LiveConfig("https://models.example/v1", "requested-test-model", "test-only-api-key")


def test_writer_request_sends_only_explicit_facts_and_retains_provider_reported_usage():
    config = model_config()
    seen = []
    payload = {"computed_csv_facts": analyze(), "public_notes": "Synthetic public note."}

    def respond(request):
        seen.append(json.loads(request.content))
        assert request.url == "https://models.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer " + config.key
        assert config.key not in request.content.decode()
        return httpx.Response(
            200,
            json=provider_body(
                sample_draft(), usage={"prompt_tokens": 43, "completion_tokens": 21}
            ),
        )

    reply = call_model(config, "writer", payload, Event(), httpx.MockTransport(respond))
    assert reply.value == sample_draft()
    assert json.loads(seen[0]["messages"][1]["content"]) == payload
    assert (reply.input_tokens, reply.output_tokens) == (43, 21)
    assert reply.response_model == "provider-reported-test-model"
    assert seen[0]["model"] == "requested-test-model"
    assert config.key not in repr(config)


@pytest.mark.parametrize(
    "usage",
    [
        None,
        [],
        "unavailable",
        {"prompt_tokens": True, "completion_tokens": False},
        {"prompt_tokens": -1, "completion_tokens": -9},
    ],
)
def test_missing_or_malformed_usage_stays_unknown_instead_of_becoming_zero(usage):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json=provider_body(sample_draft(), usage=usage))
    )
    reply = call_model(model_config(), "writer", {}, Event(), transport)
    assert reply.input_tokens is None and reply.output_tokens is None


def test_partial_usage_retains_only_the_known_measurement():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200, json=provider_body(sample_draft(), usage={"prompt_tokens": 0})
        )
    )
    reply = call_model(model_config(), "writer", {}, Event(), transport)
    assert reply.input_tokens == 0
    assert reply.output_tokens is None


@pytest.mark.parametrize("location", ["rationale", "response_model"])
def test_provider_cannot_echo_server_credentials_into_retained_outputs(location):
    config = model_config()
    draft = sample_draft()
    body = provider_body(draft)
    if location == "rationale":
        draft["rationale"] = "Provider echoed " + config.key
        body = provider_body(draft)
    else:
        body["model"] = "echo-" + config.key
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    with pytest.raises(LiveFailure) as error:
        call_model(config, "writer", {}, Event(), transport)
    assert error.value.code == "invalid_model_output"
    assert config.key not in str(error.value)


def test_reviewer_response_uses_its_own_schema_and_real_supplied_draft():
    draft = sample_draft()
    draft["facts"]["revenue_growth_percent"] = "99.9"
    review = {
        "verdict": "revise",
        "issues": ["The revenue growth claim disagrees with the supplied CSV facts."],
        "rationale": "The source calculation supports 39.15 percent.",
    }
    payload = {"actual_writer_draft": draft, "computed_csv_facts": analyze()}
    captured = []

    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=provider_body(review))

    reply = call_model(model_config(), "reviewer", payload, Event(), httpx.MockTransport(respond))
    assert reply.value == review
    assert json.loads(captured[0]["messages"][1]["content"]) == payload
    # A syntactically valid reviewer must not be confused with a writer draft.
    with pytest.raises(LiveFailure, match="invalid_model_output"):
        call_model(
            model_config(),
            "reviewer",
            payload,
            Event(),
            httpx.MockTransport(lambda _: httpx.Response(200, json=provider_body(sample_draft()))),
        )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": "This is not structured output."}}]},
    ],
)
def test_malformed_provider_content_has_a_known_failure_without_fabricated_result(body):
    with pytest.raises(LiveFailure, match="invalid_model_output"):
        call_model(
            model_config(),
            "writer",
            {},
            Event(),
            httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
        )


def test_provider_refusal_and_timeout_have_sanitized_failure_codes():
    config = model_config()
    transport = httpx.MockTransport(
        lambda _: httpx.Response(401, json={"error": "Rejected secret " + config.key})
    )
    with pytest.raises(LiveFailure) as error:
        call_model(config, "writer", {}, Event(), transport)
    assert error.value.code == "provider_unavailable"
    assert config.key not in str(error.value)

    def timeout(_):
        raise httpx.ReadTimeout("Synthetic provider timeout")

    with pytest.raises(LiveFailure, match="provider_timeout"):
        call_model(config, "writer", {}, Event(), httpx.MockTransport(timeout))


def test_stopping_an_in_flight_request_closes_it_without_a_model_result():
    started, closed, stop = Event(), Event(), Event()
    errors = []

    async def waiting_provider(_):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    def run():
        try:
            call_model(model_config(), "writer", {}, stop, httpx.MockTransport(waiting_provider))
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run, daemon=True)
    thread.start()
    try:
        assert started.wait(3), "The mock provider request did not start"
    finally:
        stop.set()
        thread.join(timeout=3)
    assert not thread.is_alive(), "Cancellation left the provider worker running"
    assert closed.is_set()
    assert len(errors) == 1 and isinstance(errors[0], LiveFailure)
    assert errors[0].code == "interrupted"


def test_source_checker_accepts_equivalent_finite_numeric_representations():
    draft = sample_draft()
    draft["facts"].update(
        first_quarter_revenue="120000.00",
        last_quarter_revenue="166980.0",
        revenue_growth_percent="39.1500",
    )
    assert check_draft(draft, analyze()) == []


@pytest.mark.parametrize("reported", ["NaN", "Infinity", "-Infinity", "1e999999", "wrong"])
def test_source_checker_rejects_non_finite_or_unsupported_quantitative_claims(reported):
    draft = sample_draft()
    draft["facts"]["revenue_growth_percent"] = reported
    assert check_draft(draft, analyze())


def test_source_checker_rejects_wrong_values_counts_and_unsupported_claim_fields():
    original = sample_draft()
    assert check_draft(original, analyze()) == []
    for key, value in (
        ("revenue_growth_percent", "38.15"),
        ("customer_quarters", True),
        ("quarters", 4.0),
        ("profit_growth_percent", "39.15"),
    ):
        draft = deepcopy(original)
        draft["facts"][key] = value
        assert check_draft(draft, analyze())
    draft = deepcopy(original)
    draft["limitations"] = [LIMITATIONS[0]] * 3
    assert check_draft(draft, analyze())


def test_free_form_rationale_remains_evidence_instead_of_a_certified_claim():
    draft = sample_draft()
    draft["rationale"] = "Unsupported prose: profit rose 400 percent."
    # The checker deliberately covers only typed source quantities and limitation labels.
    assert check_draft(draft, analyze()) == []
    evidence = draft_document("Writer evidence", draft)
    assert "not independently fact-checked" in evidence
    assert draft["rationale"] in evidence
