import re

html = open(r'evidence\polish\admin-unnest-form\served-settings.html', encoding='utf-8').read()
html = re.sub(r'<!--.*?-->', '', html, flags=re.S)  # strip comments before tag scanning

forms = re.findall(r'<form\b[^>]*>', html)
print('FORM_OPEN_TAGS:', len(forms))
for f in forms:
    print('  ', f)

depth = 0
maxdepth = 0
nested = []
for m in re.finditer(r'<form\b[^>]*>|</form>', html):
    if m.group(0).startswith('</'):
        depth -= 1
    else:
        depth += 1
        if depth > 1:
            nested.append(m.group(0))
    maxdepth = max(maxdepth, depth)
print('MAX_FORM_DEPTH:', maxdepth)
print('NESTED_FORMS:', nested)
print('HAS_TEST_FORM_ID:', 'id="chairfbi-test-form"' in html)
print('ACTION_CHAIRFBI_TEST:', html.count('action="/admin/settings/chairfbi-test"'))
print('BTN_FORM_ATTR:', 'form="chairfbi-test-form"' in html)
print('CSRF_TOKEN_INPUTS:', len(re.findall(r'name="csrf_token" value="[0-9a-f]{64}"', html)))
print('VISIBLE_CHAIRFBI_INPUTS:', len(re.findall(r'name="chairfbi_api_(?:token|base)" value="', html)))
print('HIDDEN_CHAIRFBI_BINDINGS:', len(re.findall(r'name="chairfbi_api_(?:token|base)" :value=', html)))
print('SAVE_BUTTON:', 'Save settings' in html)
print('OUTER_FORM_HAS_ENCTYPE:', bool(re.search(r'<form method="POST" enctype="multipart/form-data">', html)))
for name in ['ivno_api_key', 'payfast_merchant_id', 'loader_token', 'discord_public_url',
             'license_api_token', 'smtp_host', 'loader_public_file', 'loader_private_file',
             'license_api_auth_scheme', 'upload_loader_public', 'upload_loader_private']:
    print('FIELD', name, ':', ('name="%s"' % name) in html)
