"""Feedback page (/feedback) contracts — feature m2-feedback-page.

VAL-ST-009: /feedback renders as a designed trust page —
  * verified reviews render through the shared review_card partial, fed by
    the feedback() route from approved DB rows only;
  * the rating summary is derived from those same rows (no static figures);
  * the proof/verification cards are styled on the card system (every class
    referenced by the template exists in the built stylesheet — zero
    unstyled-class references).
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(ROOT, "templates")
BUILT_CSS = os.path.join(ROOT, "static", "css", "style.css")


def _template(rel="feedback.html"):
    with open(os.path.join(TEMPLATES_DIR, rel), encoding="utf-8") as fh:
        return fh.read()


def _add_review(db, Review, user_id, product_id, rating, status, body, days_ago=0):
    from datetime import datetime, timedelta

    review = Review(
        user_id=user_id,
        product_id=product_id,
        rating=rating,
        title="Title",
        body=body,
        status=status,
        created_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.session.add(review)
    return review


def test_feedback_renders_approved_reviews_via_shared_partial(client, db, make_user, make_product):
    from models import Review

    user = make_user("reviewer")
    product = make_product()
    _add_review(db, Review, user.id, product.id, 5, "approved", "Approved body text", days_ago=2)
    _add_review(db, Review, user.id, product.id, 4, "pending", "Pending body text", days_ago=1)
    _add_review(db, Review, user.id, product.id, 1, "rejected", "Rejected body text", days_ago=1)
    db.session.commit()

    html = client.get("/feedback").get_data(as_text=True)

    # Shared partial markup (partials/review_card.html), not a page-local copy.
    assert "review-card-stars" in html
    assert "review-card-footer" in html
    assert "Approved body text" in html
    # Pending/rejected reviews never render publicly.
    assert "Pending body text" not in html
    assert "Rejected body text" not in html
    # Newest approved first (the days_ago=2 row is the only approved one here).
    assert "Verified buyer" in html


def test_feedback_rating_summary_comes_from_db_only(client, db, make_user, make_product):
    from models import Review

    user = make_user("reviewer")
    product = make_product()
    _add_review(db, Review, user.id, product.id, 5, "approved", "Five star body")
    _add_review(db, Review, user.id, product.id, 4, "approved", "Four star body")
    db.session.commit()

    html = client.get("/feedback").get_data(as_text=True)

    assert "rating-summary" in html
    assert "4.5" in html            # (5 + 4) / 2 — computed, never static
    assert "2 verified reviews" in html


def test_feedback_empty_state_and_no_summary_without_reviews(client, db):
    html = client.get("/feedback").get_data(as_text=True)

    # Intentional empty state through the shared partial.
    assert "No verified reviews yet" in html
    assert "Ask buyers in Discord" in html
    # No summary (and no fabricated rating figures) when the DB has no reviews.
    assert "rating-summary" not in html
    assert "/ 5" not in html


def test_feedback_template_uses_shared_partial_and_no_inline_styles():
    src = _template()
    assert 'include "partials/review_card.html"' in src
    assert 'include "partials/empty_state.html"' in src
    assert "<style" not in src
    # No inline style= attributes (design law: page-scoped CSS only).
    assert "style=" not in src


def test_feedback_every_class_reference_is_styled():
    """Zero unstyled-class references: every literal class token the template
    writes must exist in the built stylesheet (VAL-ST-009)."""
    with open(BUILT_CSS, encoding="utf-8") as fh:
        built = fh.read()

    tokens = set()
    for attr in re.findall(r'class="([^"]*)"', _template()):
        for token in attr.split():
            if "{{" in token or "{%" in token:
                continue  # Jinja-composed classes come from partials (covered)
            tokens.add(token)

    assert tokens, "scan found no classes — template changed?"
    unstyled = sorted(t for t in tokens if (".%s" % t) not in built)
    assert not unstyled, "classes missing from built style.css: %s" % unstyled
