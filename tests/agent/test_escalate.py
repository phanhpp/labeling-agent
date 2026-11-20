from app.agent.clean import clean_posting
from app.agent.escalate import render_posting
from app.agent.llm import cost_usd


def test_render_posting_lists_quotable_fields_then_context_then_empty_fields():
    text = render_posting(
        clean_posting(
            {
                "title": "Clerk",
                "location": "US, NY",
                "telecommuting": "1",
                "has_company_logo": "0",
                "industry": "Retail",
            }
        )
    )
    assert text.startswith("Title: Clerk\nCompany profile: \n")
    assert "Context, not to be quoted: Industry: Retail; Telecommuting: yes; Has company logo: no" in text
    assert (
        "Empty fields: company_profile, description, requirements, benefits, salary_range, company_logo"
        in text
    )
    assert "US, NY" not in text  # location is for analysts only


def test_render_posting_escapes_angle_brackets():
    text = render_posting(clean_posting({"description": "salary < 5k > none"}))
    assert "salary &lt; 5k &gt; none" in text


def test_cost_counts_cache_reads_and_writes_at_their_own_price():
    usage = {
        "input_tokens": 2000,
        "output_tokens": 500,
        "input_token_details": {"cache_read": 1500, "cache_creation": 0},
    }
    # 500 plain input x $2 + 1500 cache reads x $0.10 + 500 output x $10, per million tokens
    assert cost_usd("claude-sonnet-5-5", usage) == round((500 * 2 + 1500 * 0.10 + 500 * 10) / 1e6, 6)
    assert cost_usd("unknown-model", usage) == 0.0
