# -*- coding: utf-8 -*-
"""Integration avec le service Kodi UpNext (service.upnext), qui propose
de jouer l'episode suivant automatiquement, façon Netflix, quelques
secondes avant la fin de l'episode en cours. Jamais notre propre code qui
affiche cette proposition - on ne fait que signaler l'episode suivant a
UpNext, qui gere lui-meme le timing et l'affichage.

Format verifie en lisant a la fois le code source de service.upnext et
une integration reelle deja fonctionnelle (vStream,
resources/lib/upnext.py) avant d'ecrire ceci - jamais devine. Confirme
ensuite comme un contrat stable et largement repandu (une bonne douzaine
d'autres addons Kodi trouves avec exactement le meme mecanisme), pas une
particularite de vStream : notification JSON-RPC "NotifyAll", message
"upnext_data", donnees en JSON encode base64.
"""
import base64
import json

import xbmc
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')

UPNEXT_ADDON_ID = 'service.upnext'


def is_installed():
    try:
        xbmcaddon.Addon(UPNEXT_ADDON_ID)
        return True
    except RuntimeError:
        return False


def _episode_payload(info):
    return {
        # Pas de vraie ligne dans la videotheque Kodi (contenu servi par un
        # plugin) - 0 est la valeur utilisee par l'integration vStream
        # (verifiee fonctionnelle) dans ce meme cas.
        'episodeid': 0, 'tvshowid': 0,
        'showtitle': info.get('showtitle', ''),
        'season': str(info.get('season', '')),
        'episode': str(info.get('episode', '')),
        'title': info.get('title', ''),
        'plot': info.get('plot', ''),
        'art': {
            'thumb': info.get('thumb', ''),
            'tvshow.poster': info.get('thumb', ''),
            'tvshow.fanart': info.get('thumb', ''),
        },
    }


def notify(current, next_):
    """current/next_ : dicts avec title, showtitle, season, episode, plot,
    thumb. next_ doit en plus porter play_url (URL plugin:// complete pour
    lancer cet episode). N'envoie rien si UpNext n'est pas installe ou si
    next_ est vide (fin de saison, pas d'episode suivant connu)."""
    if not next_ or not next_.get('play_url') or not is_installed():
        return

    payload = {
        'current_episode': _episode_payload(current),
        'next_episode': _episode_payload(next_),
        'play_url': next_['play_url'],
    }

    data = base64.b64encode(json.dumps(payload).encode('utf-8')).decode('ascii')
    request = json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'JSONRPC.NotifyAll',
        'params': {
            'sender': '{0}.SIGNAL'.format(ADDON_ID),
            'message': 'upnext_data',
            'data': [data],
        },
    })
    try:
        xbmc.executeJSONRPC(request)
    except Exception:
        pass  # jamais bloquant pour la lecture en cours
