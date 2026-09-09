"""
Tests for the domain "answer a question" skills (Stock, Real Estate — §10 of
docs/openresearch-integration-requirements.md). Single-tenant, no
candidate_id — verifies routing/extraction + grounded-answer generation with
mocked LLM/pipeline dependencies (no network, no real LLM calls).
"""

from unittest.mock import MagicMock

from agents.realestate.realestate_answer_skill import RealEstateAnswerSkill
from agents.stock.stock_answer_skill import StockAnswerSkill
from schemas.query import QueryRouterResult, ResolvedCompany
from schemas.realestate import RealEstateBrief
from schemas.stock import ResearchBrief


def _fake_research_brief(ticker="AAPL", company_name="Apple") -> ResearchBrief:
    return MagicMock(
        spec=ResearchBrief,
        ticker=ticker,
        company_name=company_name,
        verdict="Buy",
        price_target_low=100.0,
        price_target_high=150.0,
        summary="Strong iPhone momentum.",
        bull_case=["Services growth"],
        bear_case=["China risk"],
        key_risks=["Supply chain"],
    )


def _fake_realestate_brief(city="Austin", state="TX") -> RealEstateBrief:
    return MagicMock(
        spec=RealEstateBrief,
        city=city,
        state=state,
        demand_verdict="moderate_inflow",
        investment_signal="Buy",
        confidence=0.72,
        summary="Steady population growth.",
        dominant_pull_factors=["Job growth"],
        dominant_push_factors=["Cost of living"],
        key_risks=["Flood risk"],
        rental_analysis=None,
    )


# ── StockAnswerSkill ──────────────────────────────────────────────────────────

def test_stock_answer_clarification_needed_short_circuits():
    llm = MagicMock()
    router = MagicMock()
    router.route.return_value = QueryRouterResult(
        intent="unknown", clarification_needed=True, clarification_question="Which company?"
    )
    skill = StockAnswerSkill(llm, router, stock_pipeline=MagicMock())

    result = skill.apply(question="what do you think?")

    assert result.answer_text == "Which company?"
    llm.create_multimodal.assert_not_called()


def test_stock_answer_watchlist_add_uses_watchlist_store_not_llm():
    llm = MagicMock()
    router = MagicMock()
    router.route.return_value = QueryRouterResult(
        intent="watchlist_add",
        resolved=[ResolvedCompany(name="Apple", ticker="AAPL")],
    )
    watchlist_store = MagicMock()
    skill = StockAnswerSkill(llm, router, stock_pipeline=MagicMock(), watchlist_store=watchlist_store)

    result = skill.apply(question="add apple to my watchlist")

    watchlist_store.add.assert_called_once_with("AAPL")
    assert "AAPL" in result.answer_text
    assert result.matched_sources[0].id == "AAPL"
    llm.create_multimodal.assert_not_called()


def test_stock_answer_single_analysis_grounds_llm_in_research_brief():
    llm = MagicMock()
    llm.create_multimodal.return_value = ("Apple looks like a Buy given strong services growth.", False)
    router = MagicMock()
    router.route.return_value = QueryRouterResult(
        intent="single_analysis",
        resolved=[ResolvedCompany(name="Apple", ticker="AAPL")],
        depth="quick",
    )
    pipeline = MagicMock()
    pipeline.run.return_value = _fake_research_brief()
    skill = StockAnswerSkill(llm, router, stock_pipeline=pipeline)

    result = skill.apply(question="Is Apple a good buy right now?")

    pipeline.run.assert_called_once()
    assert pipeline.run.call_args.args[0].ticker == "AAPL"
    assert pipeline.run.call_args.args[0].depth == "quick"
    assert "Buy" in result.answer_text
    assert result.matched_sources[0].id == "AAPL"
    assert result.images_ignored is False

    # The research brief's actual content reached the LLM prompt, not just a generic ask.
    prompt = llm.create_multimodal.call_args.kwargs["messages"][0]["content"]
    assert "Strong iPhone momentum" in prompt
    assert "Is Apple a good buy right now?" in prompt


def test_stock_answer_comparison_researches_both_tickers():
    llm = MagicMock()
    llm.create_multimodal.return_value = ("Apple edges out Microsoft on growth.", False)
    router = MagicMock()
    router.route.return_value = QueryRouterResult(
        intent="comparison",
        resolved=[ResolvedCompany(name="Apple", ticker="AAPL"), ResolvedCompany(name="Microsoft", ticker="MSFT")],
    )
    pipeline = MagicMock()
    pipeline.run.side_effect = [
        _fake_research_brief("AAPL", "Apple"),
        _fake_research_brief("MSFT", "Microsoft"),
    ]
    skill = StockAnswerSkill(llm, router, stock_pipeline=pipeline)

    result = skill.apply(question="Apple vs Microsoft, which is the better buy?")

    assert pipeline.run.call_count == 2
    assert {s.id for s in result.matched_sources} == {"AAPL", "MSFT"}


def test_stock_answer_images_ignored_flag_propagates():
    llm = MagicMock()
    llm.create_multimodal.return_value = ("Text-only answer.", False)  # model couldn't use the image
    router = MagicMock()
    router.route.return_value = QueryRouterResult(
        intent="single_analysis", resolved=[ResolvedCompany(name="Apple", ticker="AAPL")]
    )
    pipeline = MagicMock()
    pipeline.run.return_value = _fake_research_brief()
    skill = StockAnswerSkill(llm, router, stock_pipeline=pipeline)

    from schemas.answer_common import ImageAttachment

    result = skill.apply(
        question="what's on this chart?",
        images=[ImageAttachment(media_type="image/png", data="AAAA")],
    )

    assert result.images_ignored is True


# ── RealEstateAnswerSkill ─────────────────────────────────────────────────────

def test_realestate_answer_asks_for_location_when_extraction_fails():
    llm = MagicMock()
    llm.create.return_value = "not valid json"  # extraction fails -> fallback RealEstateQueryExtraction()
    skill = RealEstateAnswerSkill(llm, realestate_pipeline=MagicMock())

    result = skill.apply(question="is now a good time to invest?")

    assert "city and state" in result.answer_text.lower()
    skill.realestate_pipeline.run.assert_not_called()


def test_realestate_answer_extracts_location_then_grounds_llm():
    llm = MagicMock()
    llm.create.return_value = '{"city": "Austin", "state": "TX", "address": null, "bedrooms": null, "bathrooms": null, "sqft": null, "purchase_price": null}'
    llm.create_multimodal.return_value = ("Austin shows moderate inflow with steady job growth.", False)
    pipeline = MagicMock()
    pipeline.run.return_value = _fake_realestate_brief()
    skill = RealEstateAnswerSkill(llm, realestate_pipeline=pipeline)

    result = skill.apply(question="Is Austin, TX a good place to invest in real estate?")

    pipeline.run.assert_called_once()
    called_input = pipeline.run.call_args.args[0]
    assert called_input.city == "Austin"
    assert called_input.state == "TX"
    assert "inflow" in result.answer_text.lower() or "growth" in result.answer_text.lower()
    assert result.matched_sources[0].title == "Austin, TX"

    prompt = llm.create_multimodal.call_args.kwargs["messages"][0]["content"]
    assert "Steady population growth" in prompt
    assert "Is Austin, TX a good place to invest" in prompt
