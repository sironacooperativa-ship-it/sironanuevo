import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import urlencode
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect

ANELE = 'https://grupo-anele.onrender.com'
SIRONA = 'https://sironanuevo-1.onrender.com'

def accounts():
    try:
        return json.loads(os.environ.get('APP_BRIDGE_ACCOUNTS', '[]'))
    except ValueError:
        return []

def enabled(user):
    return bool(os.environ.get('APP_BRIDGE_SECRET') and user.is_authenticated and user.is_active and any(a['sironaId'] == user.pk for a in accounts()))

def context(request):
    return {'anele_bridge_enabled': enabled(request.user)}

def service(data):
    secret = os.environ.get('APP_BRIDGE_SECRET', '')
    if not secret:
        raise ValueError('Conexión no configurada.')
    body = json.dumps(data, separators=(',', ':')).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
    req = Request(ANELE + '/api/bridge', data=body, headers={'Content-Type': 'application/json', 'X-Bridge-Time': stamp, 'X-Bridge-Signature': signature}, method='POST')
    with urlopen(req, timeout=20) as response:
        return json.loads(response.read(4096))

def valid(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)

def secured(response):
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response

def error():
    return secured(HttpResponse('No se pudo conectar. Volvé a la app y usá el botón nuevamente. Si tu cuenta está inactiva o bloqueada, pedí al administrador que revise tu acceso.', status=403))

def start(request):
    if not os.environ.get('APP_BRIDGE_SECRET'):
        return error()
    state = secrets.token_hex(32)
    request.session['anele_bridge_state'] = state
    return secured(redirect(ANELE + '/api/bridge?' + urlencode({'step': 'authorize', 'state': state})))

@login_required
def authorize(request):
    state = request.GET.get('state', '')
    if not enabled(request.user) or not valid(state):
        return error()
    try:
        code = service({'action': 'issue', 'sironaId': request.user.pk, 'state': state})['code']
        return secured(redirect(ANELE + '/api/bridge?' + urlencode({'step': 'callback', 'code': code, 'state': state})))
    except (ValueError, KeyError, URLError, TimeoutError):
        return error()

def callback(request):
    state = request.GET.get('state', '')
    saved = request.session.pop('anele_bridge_state', '')
    if not valid(state) or not saved or not secrets.compare_digest(state, saved):
        return error()
    try:
        data = service({'action': 'consume', 'code': request.GET.get('code', ''), 'state': state})
        if not any(a['sironaId'] == data['sironaId'] and a['aneleId'] == data['aneleId'] for a in accounts()):
            return error()
        user = get_user_model().objects.filter(pk=data['sironaId'], is_active=True).first()
        if user is None:
            return error()
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        request.session['modo_admin'] = False
        request.session['modo_vendedor'] = bool(getattr(getattr(user, 'perfil_acceso', None), 'solo_vendedor', False))
        request.session.pop('logout_pending_at', None)
        return secured(redirect('home'))
    except (ValueError, KeyError, URLError, TimeoutError):
        return error()
