# -*- coding: utf-8 -*-
"""Appels HTTP vers l'API JSON /api/kodi/* du serveur AllDebrid Downloader.

Volontairement en stdlib pur (urllib) : un addon installé hors dépôt (via
zip) ne peut pas résoudre automatiquement une dépendance comme
script.module.requests, il faudrait la sideloader séparément et la
maintenir à jour manuellement pour un simple GET JSON authentifié.
"""
import base64
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

import xbmcaddon

ADDON = xbmcaddon.Addon()
TIMEOUT = 8  # secondes


class ApiError(Exception):
    """Erreur réseau ou serveur (hors authentification)."""


class AuthError(ApiError):
    """401 renvoyé par le serveur — mauvais nom d'utilisateur/mot de passe."""


def _base_url():
    server = ADDON.getSettingString('server').strip()
    port = ADDON.getSettingInt('port')
    scheme = 'https' if ADDON.getSettingBool('use_https') else 'http'
    return '{0}://{1}:{2}'.format(scheme, server, port)


def _auth_header():
    user = ADDON.getSettingString('app_username')
    pwd = ADDON.getSettingString('app_password')
    token = base64.b64encode('{0}:{1}'.format(user, pwd).encode('utf-8')).decode('ascii')
    return 'Basic {0}'.format(token)


def _get(path, query=None):
    url = _base_url() + path
    if query:
        url += '?' + urllib.parse.urlencode(query)

    req = urllib.request.Request(
        url,
        headers={'Authorization': _auth_header(), 'Accept': 'application/json'},
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
        return json.loads(body)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError('401 Unauthorized') from exc
        raise ApiError('HTTP {0}'.format(exc.code)) from exc
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        raise ApiError(str(exc)) from exc


def ping():
    return _get('/api/kodi/ping')


def browse(path):
    return _get('/api/kodi/browse', {'path': path})


def movie_info(tmdb_id):
    return _get('/api/kodi/movie-info', {'tmdb_id': tmdb_id})
