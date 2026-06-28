from shared.normalize import format_tag_string, render_template


def test_render_template_substitutes_placeholders():
    out = render_template(
        "{{ tags }}\n{{ text }}\n— {{ source_label }}",
        text="Body text",
        source_label="MyChannel",
        tags="#news",
    )
    assert "#news" in out
    assert "Body text" in out
    assert "MyChannel" in out


def test_render_template_handles_empty_fields():
    out = render_template("[{{ tags }}] {{ text }} ({{ source_label }})", text="", source_label="", tags="")
    # Empty vars leave their surrounding literal spaces; collapse for the assert.
    assert " ".join(out.split()) == "[] ()"


def test_render_template_conditional_tags_block():
    body = "{% if tags %}{{ tags }}\n{% endif %}{{ text }}"
    assert render_template(body, text="hi", source_label="x", tags="#t").strip().endswith("hi")
    assert render_template(body, text="hi", source_label="x", tags="").strip() == "hi"


def test_format_tag_string():
    assert format_tag_string(["News", "Tech Talk"]) == "#news #tech_talk"
    assert format_tag_string([]) == ""
