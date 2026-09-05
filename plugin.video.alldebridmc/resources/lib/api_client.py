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
import time
import urllib.error
import urllib.parse
import urllib.request

import xbmc
import xbmcaddon

ADDON = xbmcaddon.Addon()
TIMEOUT = 8  # secondes

# Un seul reessai, apres une courte pause, uniquement pour une panne
# reseau (jamais une erreur HTTP du serveur, deja bien vivant - 401/400/
# etc, voir _raise_for_http_error). Constate en conditions reelles
# (KodiMiniPC) : une machine laissee des heures sur l'ecran hebergeurs
# vStream (rien ne se rafraichit, donc aucun appel reseau de notre part
# pendant tout ce temps hormis le ping de _announce_device) redemandait
# plusieurs rechargements manuels avant qu'une requete aboutisse - typique
# d'une table NAT/ARP perimee (routeur, table de connexion du systeme
# d'exploitation) qu'un premier essai echoue a reveiller mais qu'un
# deuxieme, quelques instants plus tard, reussit. Le ping periodique
# (service.py::_announce_device, toutes les 10 min) reste la premiere
# ligne de defense ; ce reessai couvre le cas ou meme lui tombe pile sur
# une panne transitoire, et evite a l'utilisateur d'avoir a rejouer
# manuellement ce que l'addon peut absorber tout seul.
_RETRY_DELAY = 1.5  # secondes


def _is_transient_network_error(exc):
    return isinstance(exc, (urllib.error.URLError, socket.timeout, ConnectionError)) and not isinstance(
        exc, urllib.error.HTTPError,
    )


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


def _urlopen_with_retry(req, timeout):
    """Un seul reessai apres panne reseau transitoire - voir la note en
    tete de module. Une HTTPError (le serveur a bien repondu, juste avec
    un code d'erreur) n'est JAMAIS reessayee ici : rejouer un POST qui a
    peut-etre deja ete traite cote serveur serait plus risque qu'utile,
    et un 401/400 ne se resoudra pas tout seul en reessayant."""
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        xbmc.log(
            '[alldebridmc] api_client: panne reseau ({0}) sur {1}, nouvel essai dans {2}s'.format(
                exc, req.full_url, _RETRY_DELAY),
            xbmc.LOGWARNING,
        )
        time.sleep(_RETRY_DELAY)
        return urllib.request.urlopen(req, timeout=timeout)


def _get(path, query=None, timeout=None):
    url = _base_url() + path
    if query:
        url += '?' + urllib.parse.urlencode(query)

    req = urllib.request.Request(
        url,
        headers={'Authorization': _auth_header(), 'Accept': 'application/json'},
    )

    try:
        with _urlopen_with_retry(req, timeout or TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
        return json.loads(body)
    except urllib.error.HTTPError as exc:
        _raise_for_http_error(exc)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        raise ApiError(str(exc)) from exc


def _post(path, data=None, timeout=None):
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
        with _urlopen_with_retry(req, timeout or TIMEOUT) as resp:
            body = resp.read().decode('utf-8')
        return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        _raise_for_http_error(exc)
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        raise ApiError(str(exc)) from exc


def ping(device=None, addon_version=None, kodi_version=None):
    """Sert a la fois de test de connexion et d'annonce de l'appareil : le
    serveur retient nom/versions pour les afficher sur sa page Reglages
    (voir record_device dans kodi_api.py). Tous les parametres sont
    optionnels - sans eux, c'est un ping simple, exactement comme avant."""
    params = {
        k: v for k, v in (
            ('device', device),
            ('addon_version', addon_version),
            ('kodi_version', kodi_version),
        ) if v
    }
    return _get('/api/kodi/ping', params or None)


BROWSE_TIMEOUT = 25  # secondes - le disque du MediaCenter peut avoir besoin de se
# reveiller (spin-up) apres une periode d'inactivite ; le TIMEOUT normal (8s)
# coupait alors la requete en plein reveil du disque, alors qu'elle aurait
# fini par reussir - confirme via kodi.log (env. 9s entre la requete et
# l'echec, juste au-dessus de l'ancien TIMEOUT, systematiquement resolu en
# reessayant quelques secondes plus tard une fois le disque reveille).


def browse(path):
    return _get('/api/kodi/browse', {'path': path}, timeout=BROWSE_TIMEOUT)


def movie_info(tmdb_id):
    return _get('/api/kodi/movie-info', {'tmdb_id': tmdb_id})


# ---- listes (partagées avec la page web /lists du serveur) ----------------

LISTS_TIMEOUT = 25  # secondes - meme raison que BROWSE_TIMEOUT : l'enrichissement
# d'une page (jusqu'a per_page elements, verification de disponibilite via
# pastebin_catalog + metadonnees TMDB) peut depasser le TIMEOUT normal (8s)
# sur un cache froid, surtout pour une grosse liste (rapporte reellement sur
# la liste "Halloween", 190 elements) - resolu en reessayant une fois les
# caches rechauffes, meme symptome que pour "Medias" avant le meme correctif.

def list_lists():
    return _get('/api/kodi/lists').get('lists', [])


def list_items(list_id, page=1, per_page=50):
    return _get('/api/kodi/lists/{0}'.format(list_id), {'page': page, 'per_page': per_page}, timeout=LISTS_TIMEOUT)


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


def resolve_pastebin_files(media_type, tmdb_id, season=None, episode=None):
    """Resout en un seul appel tous les fichiers Pastebin disponibles pour ce
    tmdb_id (filtres par saison/episode si fournis) en liens AllDebrid
    REELLEMENT jouables (voir la docstring de la route serveur
    /api/kodi/lists/resolve-files) - remplace la redirection vers vStream
    (vstream_adapter.py) pour la lecture directe, voir pastebin_playback.py."""
    params = {'media_type': media_type, 'tmdb_id': tmdb_id}
    if season is not None and episode is not None:
        params['season'] = season
        params['episode'] = episode
    return _get('/api/kodi/lists/resolve-files', params, timeout=LISTS_TIMEOUT).get('files', [])


def search_local_catalog(query):
    """Recherche dans la bibliotheque locale du MediaCenter par titre TMDB
    deja resolu (jamais par nom de fichier brut) - meme fonction serveur
    (lists_store.search_local) que celle utilisee par la page web /lists
    pour relier un item local a une liste."""
    return _get('/api/kodi/lists/search-local', {'q': query}).get('results', [])


# ---- reprise de lecture synchronisée (watch_progress.py sur le serveur) ---

def get_watch_progress(path):
    return _get('/api/kodi/watch-progress', {'path': path}).get('progress')


def post_watch_progress(path, position, duration, device):
    _post('/api/kodi/watch-progress', {
        'path': path, 'position': position, 'duration': duration, 'device': device,
    })


def clear_watch_progress(path):
    _post('/api/kodi/watch-progress/clear', {'path': path})


def list_watch_progress(status, category=None):
    params = {'status': status}
    if category:
        params['category'] = category
    return _get('/api/kodi/watch-progress/list', params).get('items', [])


def post_watch_progress_vstream(
    tmdb_id, position, duration, device, resume_key=None, season=None, episode=None, smedia=None,
):
    payload = {
        'source': 'vstream', 'tmdb_id': tmdb_id,
        'position': position, 'duration': duration, 'device': device, 'resume_key': resume_key,
    }
    if season is not None and episode is not None:
        payload['season'] = season
        payload['episode'] = episode
        payload['smedia'] = smedia
    _post('/api/kodi/watch-progress', payload)


def get_watch_progress_vstream_seasons(tmdb_id):
    return _get('/api/kodi/watch-progress/vstream/seasons', {'tmdb_id': tmdb_id})


def get_watch_progress_vstream_episodes(tmdb_id, season):
    return _get('/api/kodi/watch-progress/vstream/episodes', {'tmdb_id': tmdb_id, 'season': season}).get('episodes', [])


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


def get_watch_progress_last_updated():
    # Lecture d'un petit fichier cote serveur, jamais d'enrichissement -
    # le TIMEOUT normal (8s) suffit largement, aucun besoin d'un delai
    # dedie comme BROWSE_TIMEOUT/LISTS_TIMEOUT.
    return _get('/api/kodi/watch-progress/last-updated')


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


# ---- catalogue Pastebin (etape 3 du chantier de suppression de vStream) ---

PASTEBIN_TIMEOUT = 45  # secondes - meme raison que LISTS_TIMEOUT : parcourir/
# chercher une categorie entiere peut tomber sur un cache Pastebin froid.
# Relevee de 25 a 45s : constate en conditions reelles qu'au demarrage de
# Kodi, Arctic Horizon 2 declenche une vingtaine de widgets d'un coup -
# chaque route repond pourtant vite en isolation (<1.2s, verifie), donc le
# delai vient de Kodi lui-meme (nombre de scripts d'addon executes en
# parallele au demarrage), pas du serveur - une marge plus large absorbe ce
# pic ponctuel sans cout dans le cas normal.

PASTEBIN_REFRESH_TIMEOUT = 60  # secondes - rafraichit les 7 categories l'une
# apres l'autre cote serveur (voir pastebin_routes.py), largement au-dela du
# TIMEOUT normal (8s).


def pastebin_categories():
    return _get('/api/kodi/pastebin/categories').get('categories', [])


def pastebin_codes():
    return _get('/api/kodi/pastebin/codes').get('codes', [])


def pastebin_set_code(category, code):
    _post('/api/kodi/pastebin/codes', {'category': category, 'code': code})


def pastebin_refresh():
    _post('/api/kodi/pastebin/refresh', timeout=PASTEBIN_REFRESH_TIMEOUT)


def pastebin_browse(category, page=1):
    return _get('/api/kodi/pastebin/category/{0}'.format(category), {'page': page}, timeout=PASTEBIN_TIMEOUT)


def pastebin_search(category, query):
    return _get(
        '/api/kodi/pastebin/category/{0}/search'.format(category), {'q': query}, timeout=PASTEBIN_TIMEOUT,
    ).get('entries', [])


def pastebin_recent(category):
    return _get('/api/kodi/pastebin/category/{0}/recent'.format(category), timeout=PASTEBIN_TIMEOUT).get('entries', [])


def pastebin_trending(category):
    return _get(
        '/api/kodi/pastebin/category/{0}/trending'.format(category), timeout=PASTEBIN_TIMEOUT,
    ).get('entries', [])


def pastebin_news(category):
    return _get(
        '/api/kodi/pastebin/category/{0}/news'.format(category), timeout=PASTEBIN_TIMEOUT,
    ).get('entries', [])


def pastebin_top_rated(category):
    return _get(
        '/api/kodi/pastebin/category/{0}/top_rated'.format(category), timeout=PASTEBIN_TIMEOUT,
    ).get('entries', [])


def pastebin_genres(category):
    return _get(
        '/api/kodi/pastebin/category/{0}/genres'.format(category), timeout=PASTEBIN_TIMEOUT,
    ).get('genres', [])


def pastebin_genre_browse(category, movie_genre_id=None, tv_genre_id=None):
    params = {}
    if movie_genre_id:
        params['movie_genre_id'] = movie_genre_id
    if tv_genre_id:
        params['tv_genre_id'] = tv_genre_id
    return _get(
        '/api/kodi/pastebin/category/{0}/genre'.format(category), params, timeout=PASTEBIN_TIMEOUT,
    ).get('entries', [])


def pastebin_networks(category):
    return _get(
        '/api/kodi/pastebin/category/{0}/networks'.format(category), timeout=PASTEBIN_TIMEOUT,
    ).get('networks', [])


def pastebin_network_browse(category, network_id, page=1):
    return _get(
        '/api/kodi/pastebin/category/{0}/network/{1}'.format(category, network_id), {'page': page},
        timeout=PASTEBIN_TIMEOUT,
    )


# ---- liens sauvegardes AllDebrid (etape 4 du chantier de suppression de vStream) --

def pastebin_saga_search(category, query):
    return _get(
        '/api/kodi/pastebin/category/{0}/saga_search'.format(category), {'q': query}, timeout=PASTEBIN_TIMEOUT,
    ).get('collections', [])


def pastebin_saga_browse(category, collection_id):
    return _get(
        '/api/kodi/pastebin/category/{0}/saga/{1}'.format(category, collection_id), timeout=PASTEBIN_TIMEOUT,
    ).get('entries', [])


def pastebin_years(category):
    return _get('/api/kodi/pastebin/category/{0}/years'.format(category), timeout=PASTEBIN_TIMEOUT).get('years', [])


def pastebin_year_browse(category, year, page=1):
    return _get(
        '/api/kodi/pastebin/category/{0}/year/{1}'.format(category, year), {'page': page},
        timeout=PASTEBIN_TIMEOUT,
    )


def pastebin_letter_browse(category, letter, page=1):
    return _get(
        '/api/kodi/pastebin/category/{0}/letter/{1}'.format(category, letter), {'page': page},
        timeout=PASTEBIN_TIMEOUT,
    )


def pastebin_random(category):
    return _get('/api/kodi/pastebin/category/{0}/random'.format(category), timeout=PASTEBIN_TIMEOUT).get('entries', [])


def pastebin_groups(category):
    return _get('/api/kodi/pastebin/category/{0}/groups'.format(category), timeout=PASTEBIN_TIMEOUT).get('groups', [])


def pastebin_group_children(category, parent):
    return _get(
        '/api/kodi/pastebin/category/{0}/group_children'.format(category), {'parent': parent}, timeout=PASTEBIN_TIMEOUT,
    ).get('children', [])


def pastebin_group_items(category, group, page=1):
    return _get(
        '/api/kodi/pastebin/category/{0}/group_items'.format(category), {'group': group, 'page': page},
        timeout=PASTEBIN_TIMEOUT,
    )


def alldebrid_saved_links():
    return _get('/api/kodi/alldebrid/links', timeout=PASTEBIN_TIMEOUT).get('links', [])


def alldebrid_resolve_link(link):
    """Peut renvoyer {'delayed': True} (HTTP 202, l'hebergeur prepare encore
    le lien) - jamais une exception dans ce cas, voir alldebrid_routes.py
    (client) pour le reessai borne."""
    return _get('/api/kodi/alldebrid/links/resolve', {'link': link})


def alldebrid_delete_link(link):
    _post('/api/kodi/alldebrid/links/delete', {'link': link})


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
