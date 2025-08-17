import os

def test_post_form_fallback_present():
    template_path = os.path.join('templates', 'post_form.html')
    with open(template_path) as f:
        content = f.read()
    assert 'easyMDE ? easyMDE.value() : bodyEl.value' in content
    assert "bodyEl.addEventListener('input', updatePreview)" in content
