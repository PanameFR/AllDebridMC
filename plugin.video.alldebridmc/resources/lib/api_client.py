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


class ValidationError(ApiError):
    """400 renvoyé par le serveur, avec un message affichable directement
    à l'utilisateur (ex : élément absent de la source Pastebin)."""


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


def _raise_for_http_error(exc):
    if exc.code == 401:
        raise AuthError('401 Unauthorized') from exc
    if exc.code == 400:
        try:
            body = json.loads(exc.read().decode('utf-8'))
            message = body.get('error') if isinstance(body, dict) else None
        except (ValueError, AttributeError):
            message = None
        raise ValidationError(message or 'HTTP 400') from exc
    raise ApiError('HTTP {0}'.format(exc.code)) from exc


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
        _raise_for_http_error(exc)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        raise ApiError(str(exc)) from exc


def _post(path, data=None):
    url = _base_url() + path
    encoded = urllib.parse.urlencode({k: v for k, v in (data or {}).items() if v is not None}).encode('utf-8')

    req = urllib.request.Request(
        url, data=encoded, method='POST',
        headers={
            'Authorization': _auth_header(), 'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
        return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        _raise_for_http_error(exc)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        raise ApiError(str(exc)) from exc


def ping():
    return _get('/api/kodi/ping')


def browse(path):
    return _get('/api/kodi/browse', {'path': path})


def movie_info(tmdb_id):
    return _get('/api/kodi/movie-info', {'tmdb_id': tmdb_id})


# ---- listes (partagées avec la page web /lists du serveur) ----------------

def list_lists():
    return _get('/api/kodi/lists').get('lists', [])


def list_items(list_id):
    return _get('/api/kodi/lists/{0}'.format(list_id))


def create_list(name):
    return _post('/api/kodi/lists', {'name': name})['id']


def rename_list(list_id, name):
    _post('/api/kodi/lists/{0}/rename'.format(list_id), {'name': name})


def delete_list(list_id):
    _post('/api/kodi/lists/{0}/delete'.format(list_id))


def move_list(list_id, direction):
    _post('/api/kodi/lists/{0}/move'.format(list_id), {'direction': direction})


def add_list_item(list_id, media_type, tmdb_id, source, local_path=None):
    _post('/api/kodi/lists/{0}/items'.format(list_id), {
        'media_type': media_type, 'tmdb_id': tmdb_id, 'source': source, 'local_path': local_path,
    })


def remove_list_item(list_id, media_type, tmdb_id):
    _post('/api/kodi/lists/{0}/items/remove'.format(list_id), {'media_type': media_type, 'tmdb_id': tmdb_id})


def move_list_item(list_id, media_type, tmdb_id, direction):
    _post('/api/kodi/lists/{0}/items/move'.format(list_id), {
        'media_type': media_type, 'tmdb_id': tmdb_id, 'direction': direction,
    })


def search_vstream_catalog(query, categories=None):
    params = {'q': query}
    if categories:
        params['categories'] = ','.join(categories)
    return _get('/api/kodi/lists/search-vstream', params).get('results', [])


# ---- reprise de lecture synchronisée (watch_progress.py sur le serveur) ---

def get_watch_progress(path):
    return _get('/api/kodi/watch-progress', {'path': path}).get('progress')


def post_watch_progress(path, position, duration, device):
    _post('/api/kodi/watch-progress', {
        'path': path, 'position': position, 'duration': duration, 'device': device,
    })


def clear_watch_progress(path):
    _post('/api/kodi/watch-progress/clear', {'path': path})


def list_watch_progress(status):
    return _get('/api/kodi/watch-progress/list', {'status': status}).get('items', [])


def post_watch_progress_vstream(tmdb_id, position, duration, device, resume_key=None, season=None, episode=None):
    payload = {
        'source': 'vstream', 'tmdb_id': tmdb_id,
        'position': position, 'duration': duration, 'device': device, 'resume_key': resume_key,
    }
    if season is not None and episode is not None:
        payload['season'] = season
        payload['episode'] = episode
    _post('/api/kodi/watch-progress', payload)


def get_watch_progress_vstream(tmdb_id, season=None, episode=None):
    params = {'source': 'vstream', 'tmdb_id': tmdb_id}
    if season is not None and episode is not None:
        params['season'] = season
        params['episode'] = episode
    return _get('/api/kodi/watch-progress', params).get('progress')


def clear_watch_progress_vstream(tmdb_id, season=None, episode=None):
    payload = {'source': 'vstream', 'tmdb_id': tmdb_id}
    if season is not None and episode is not None:
        payload['season'] = season
        payload['episode'] = episode
    _post('/api/kodi/watch-progress/clear', payload)


# ---- sauvegarde/restauration Kodi (kodi_backup.py sur le serveur) ---------

BACKUP_TIMEOUT = 60  # secondes - un chunk peut prendre du temps sur un reseau lent


def backup_upload_chunk(session_id, device, chunk_index, is_last, data):
    query = urllib.parse.urlencode({
        'session_id': session_id, 'device': device,
        'chunk_index': chunk_index, 'is_last': '1' if is_last else '0',
    })
    url = _base_url() + '/api/kodi/backup/upload?' + query

    req = urllib.request.Request(
        url, data=data, method='POST',
        headers={
            'Authorization': _auth_header(), 'Accept': 'application/json',
            'Content-Type': 'application/octet-stream',
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=BACKUP_TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
        return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        _raise_for_http_error(exc)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        raise ApiError(str(exc)) from exc


def backup_list():
    return _get('/api/kodi/backup/list').get('backups', [])


def backup_download(name, dest_path, progress_callback=None):
    """Telecharge en flux (lecture par blocs, jamais tout charge en memoire
    d'un coup - contrairement a l'ecriture, lire une reponse HTTP par blocs
    est un usage stdlib standard) vers dest_path (chemin reel deja resolu
    par l'appelant, pas un special:// Kodi)."""
    url = _base_url() + '/api/kodi/backup/download?' + urllib.parse.urlencode({'name': name})
    req = urllib.request.Request(url, headers={'Authorization': _auth_header()})

    try:
        with urllib.request.urlopen(req, timeout=BACKUP_TIMEOUT) as resp:
            total = int(resp.headers.get('Content-Length') or 0)
            written = 0
            with open(dest_path, 'wb') as fh:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    if progress_callback:
                        progress_callback(written, total)
    except urllib.error.HTTPError as exc:
        _raise_for_http_error(exc)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        raise ApiError(str(exc)) from exc
