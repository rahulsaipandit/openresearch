from agents.stock.document_insights import DocumentInsightsAgent, _find_best_span, _union_bbox
from schemas.document_insights import ParsedDocument, ParsedPage, ParsedTextItem


def _item(text, x, y, w=50.0, h=10.0):
    return ParsedTextItem(text=text, x=x, y=y, width=w, height=h)


def test_find_best_span_exact_single_item_match():
    page = ParsedPage(
        page=1, width=600, height=800, text="irrelevant",
        text_items=[_item("Revenue grew 63% year over year", 10, 100), _item("Other line", 10, 120)],
    )
    items, ratio = _find_best_span(page, "revenue grew 63%")
    assert ratio == 1.0
    assert len(items) == 1
    assert items[0].text == "Revenue grew 63% year over year"


def test_find_best_span_multi_item_window_match():
    page = ParsedPage(
        page=2, width=600, height=800, text="irrelevant",
        text_items=[
            _item("Operating", 10, 200),
            _item("margin", 65, 200),
            _item("expanded", 105, 200),
            _item("to 43.3%", 165, 200),
            _item("Unrelated next line", 10, 220),
        ],
    )
    items, ratio = _find_best_span(page, "Operating margin expanded to 43.3%")
    assert ratio >= 0.6
    assert [it.text for it in items] == ["Operating", "margin", "expanded", "to 43.3%"]


def test_find_best_span_no_match_returns_empty():
    page = ParsedPage(
        page=3, width=600, height=800, text="irrelevant",
        text_items=[_item("Completely different content here", 10, 100)],
    )
    items, ratio = _find_best_span(page, "something totally unrelated to the page xyz123")
    assert items == []
    assert ratio < 0.6


def test_find_best_span_empty_quote_or_items():
    page = ParsedPage(page=1, width=600, height=800, text="x", text_items=[])
    assert _find_best_span(page, "anything") == ([], 0.0)

    page2 = ParsedPage(page=1, width=600, height=800, text="x", text_items=[_item("hello", 0, 0)])
    assert _find_best_span(page2, "") == ([], 0.0)


def test_union_bbox_covers_all_items():
    items = [_item("a", 10, 20, w=30, h=10), _item("b", 50, 15, w=20, h=15)]
    x, y, w, h = _union_bbox(items)
    assert x == 10
    assert y == 15
    assert w == (70 - 10)   # max(x+width) - min(x) = max(40, 70) - 10
    assert h == (30 - 15)   # max(y+height) - min(y) = max(30, 30) - 15


def test_build_citations_uses_matched_span_when_confident():
    agent = object.__new__(DocumentInsightsAgent)
    doc = ParsedDocument(
        source_file="test.pdf",
        pages=[
            ParsedPage(
                page=1, width=600, height=800, text="Revenue grew 63% year over year.",
                text_items=[_item("Revenue grew 63% year over year.", 10, 100)],
            )
        ],
    )
    citations = agent._build_citations(doc, "earnings-call.pdf", [{"page": 1, "quote": "Revenue grew 63%"}])
    assert len(citations) == 1
    c = citations[0]
    assert c.document_name == "earnings-call.pdf"
    assert c.page == 1
    assert c.x == 10 and c.y == 100
    assert c.excerpt == "Revenue grew 63%"


def test_build_citations_falls_back_to_page_anchor_without_match():
    agent = object.__new__(DocumentInsightsAgent)
    doc = ParsedDocument(
        source_file="test.pdf",
        pages=[
            ParsedPage(
                page=2, width=600, height=800, text="Some page text that is fairly long overall.",
                text_items=[_item("First item on the page", 5, 5)],
            )
        ],
    )
    citations = agent._build_citations(doc, "report.pdf", [{"page": 2, "quote": "nothing matches this at all xyz"}])
    assert len(citations) == 1
    c = citations[0]
    assert c.x == 5 and c.y == 5
    assert c.excerpt == "Some page text that is fairly long overall."


def test_build_citations_skips_unknown_page():
    agent = object.__new__(DocumentInsightsAgent)
    doc = ParsedDocument(source_file="test.pdf", pages=[ParsedPage(page=1, width=1, height=1, text="x", text_items=[])])
    citations = agent._build_citations(doc, "doc.pdf", [{"page": 99, "quote": "whatever"}])
    assert citations == []
