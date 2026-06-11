"""
CSRF doğrulaması başarısız olduğunda kullanıcıya gerçek hatayı gösteren
özel hata sayfası. settings.CSRF_FAILURE_VIEW üzerinden bağlanır.
"""
from django.http import HttpResponse
from django.template import engines

django_engine = engines['django']

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>CSRF Hatası (403)</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; padding: 40px; }
        .box { background: #fff; border-radius: 16px; padding: 32px; max-width: 780px; margin: 0 auto; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
        h1 { color: #ef4444; margin: 0 0 16px; }
        table { width: 100%; border-collapse: collapse; margin-top: 16px; }
        td { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; font-family: monospace; font-size: 13px; }
        td:first-child { font-weight: 600; width: 220px; }
        .alert { background: #fff3cd; padding: 14px; border-radius: 10px; margin: 16px 0; color: #92400e; }
        a { color: #4361ee; text-decoration: none; font-weight: 600; }
    </style>
</head>
<body>
<div class="box">
    <h1>🛡 CSRF Doğrulaması Başarısız (403)</h1>
    <p>Sebep: <strong>{{ reason }}</strong></p>
    <div class="alert">
        Bu sayfa sadece teşhis içindir. Tarayıcınızdaki mevcut <code>csrftoken</code> ve
        <code>sessionid</code> cookie'lerini temizleyip tekrar login olmayı deneyin.
        Eğer Origin/Host beklediğiniz domainle eşleşmiyorsa, proxy ayarlarınızda sorun var demektir.
    </div>
    <table>
        <tr><td>Origin</td><td>{{ origin }}</td></tr>
        <tr><td>Referer</td><td>{{ referer }}</td></tr>
        <tr><td>Host</td><td>{{ host }}</td></tr>
        <tr><td>X-Forwarded-Proto</td><td>{{ x_forwarded_proto }}</td></tr>
        <tr><td>X-Forwarded-Host</td><td>{{ x_forwarded_host }}</td></tr>
        <tr><td>Method</td><td>{{ method }}</td></tr>
        <tr><td>Path</td><td>{{ path }}</td></tr>
        <tr><td>request.is_secure()</td><td>{{ is_secure }}</td></tr>
        <tr><td>request.scheme</td><td>{{ scheme }}</td></tr>
    </table>
    <p style="margin-top:24px;"><a href="/">← Anasayfaya dön</a></p>
</div>
</body>
</html>
"""


def csrf_failure(request, reason=''):
    """Django'nun CSRF_FAILURE_VIEW olarak çağırdığı view."""
    context = {
        'reason': reason,
        'origin': request.META.get('HTTP_ORIGIN', '-'),
        'referer': request.META.get('HTTP_REFERER', '-'),
        'host': request.META.get('HTTP_HOST', '-'),
        'x_forwarded_proto': request.META.get('HTTP_X_FORWARDED_PROTO', '-'),
        'x_forwarded_host': request.META.get('HTTP_X_FORWARDED_HOST', '-'),
        'method': request.method,
        'path': request.path,
        'is_secure': request.is_secure(),
        'scheme': request.scheme,
    }
    rendered = django_engine.from_string(_HTML_TEMPLATE).render(context)
    return HttpResponse(rendered, status=403)
