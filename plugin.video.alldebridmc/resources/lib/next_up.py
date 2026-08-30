# -*- coding: utf-8 -*-
"""Enchainement fiable des episodes de la bibliotheque locale, en
remplacement de service.upnext pour ce cas precis, ET (voir
parse_external_notification plus bas) pour toute source EXTERNE
integree a UpNext qui diffuse le protocole standard NotifyAll/
upnext_data - vStream compris, verifie contre son propre code source
(resources/lib/upnext.py::notifyUpnext() sur Kodi-vStream/venom-xbmc-addons,
branche Beta) qui envoie exactement ce protocole avec un play_url deja
resolu. Le pont d'ecoute cote service (resources/lib service.py::
_UpNextBridge) reste separe de ce module ; ce fichier ne fait que fournir
la traduction payload -> next_info et le minuteur/popup, communs aux deux
cas.

Diagnostic (code source reel de service.upnext lu sur un appareil
installe, resources/lib/playbackmanager.py::show_popup_and_wait) :
service.upnext attend par conception qu'il ne reste plus qu'1 seconde ou
moins avant de basculer vers l'episode suivant - une vraie course contre
la fin naturelle du fichier, perdue plus souvent que gagnee sur nos
fichiers locaux (lecture SMB directe, quasi aucune mise en tampon,
contrairement aux sources en streaming HTTP de vStream qui ont
naturellement de la marge grace a leur tampon de lecture). Le meme risque
existe en theorie pour n'importe quelle autre source utilisant ce
protocole, d'ou l'interet d'etendre ce mecanisme au-dela de la
bibliotheque locale plutot que de le garder isole.

Ce module recree un popup "Episode suivant" du meme type (compte a
rebours, boutons Lire maintenant/Annuler) - jamais copie tel quel
(service.upnext est GPL-2.0-only, seuls la structure/le comportement sont
repris, avec nos propres visuels) - mais declenche avec une vraie marge
CONFIGURABLE (jamais a la derniere seconde) : deux reglages
(chaining_notify_before_end, chaining_autoplay_countdown) determinent
quand le popup apparait et combien de temps son compte a rebours dure -
le changement de fichier reel se produit donc toujours avec au moins
quelques secondes d'avance sur la fin reelle.
"""
import base64
import json
import threading
from binascii import Error as _BinasciiError
from binascii import unhexlify

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()

_WATCH_NOW_CONTROL_ID = 501
_CANCEL_CONTROL_ID = 502
_PROGRESS_CONTROL_ID = 503

_MONITOR_TICK = 1.0  # secondes entre deux sondages de la position de lecture
_COUNTDOWN_TICK = 0.5  # secondes entre deux mises a jour du compte a rebours affiche
_START_TIMEOUT = 45  # secondes max d'attente que la lecture demarre reellement


class NextEpisodePopup(xbmcgui.WindowXMLDialog):
    """Meme principe que la classe UpNext de service.upnext (WindowXMLDialog,
    skin embarque dans l'addon, lance en .show() non-modal pour laisser la
    video continuer derriere) - jamais copiee telle quelle (licence
    GPL-2.0-only), juste la meme structure/le meme comportement."""

    def __init__(self, *args, **kwargs):
        super(NextEpisodePopup, self).__init__(*args, **kwargs)
        self._cancelled = False
        self._watch_now = False
        self._episode_info = {}

    def set_episode_info(self, info):
        # Appele avant show() - onInit() (declenche par Kodi pendant show())
        # lit cet attribut, deja en place a ce moment-la.
        self._episode_info = info or {}

    def onInit(self):
        info = self._episode_info
        self.setProperty('alldebridmc_thumb', info.get('thumb', ''))
        self.setProperty('alldebridmc_showtitle', info.get('showtitle', ''))
        self.setProperty('alldebridmc_season', str(info.get('season') or ''))
        self.setProperty('alldebridmc_episode', str(info.get('episode') or ''))
        self.setProperty('alldebridmc_title', info.get('title', ''))

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self.set_cancel(True)
            self.close()

    def onClick(self, control_id):
        if control_id == _WATCH_NOW_CONTROL_ID:
            self.set_watch_now(True)
            self.close()
        elif control_id == _CANCEL_CONTROL_ID:
            self.set_cancel(True)
            self.close()

    def set_cancel(self, value):
        self._cancelled = value

    def is_cancel(self):
        return self._cancelled

    def set_watch_now(self, value):
        self._watch_now = value

    def is_watch_now(self):
        return self._watch_now

    def update_countdown(self, seconds_left, total_seconds):
        text = ADDON.getLocalizedString(30348).format(max(0, int(round(seconds_left))))
        self.setProperty('alldebridmc_countdown_text', text)
        try:
            control = self.getControl(_PROGRESS_CONTROL_ID)
        except RuntimeError:
            return
        if total_seconds > 0:
            control.setPercent(100 * (1 - max(0.0, seconds_left) / total_seconds))


def enabled():
    try:
        return ADDON.getSettingBool('own_chaining_enabled')
    except (AttributeError, TypeError):
        return True


def _notify_before_end():
    try:
        value = ADDON.getSettingInt('chaining_notify_before_end')
    except (AttributeError, TypeError):
        value = 0
    return value if value else 30


def _autoplay_countdown():
    try:
        value = ADDON.getSettingInt('chaining_autoplay_countdown')
    except (AttributeError, TypeError):
        value = 0
    return value if value else 20


def _decode_notification_payload(encoded):
    """Meme format que celui lu par service.upnext lui-meme (verifie contre
    son propre resources/lib/utils.py::decode_data sur im85288/service.upnext) :
    hex ou base64, jamais devine - essaie hex d'abord (comme lui) puis
    retombe sur base64. vStream et notre propre notify() de secours
    encodent toujours en base64, mais un autre addon integre a UpNext
    pourrait utiliser l'un ou l'autre selon ce meme contrat public."""
    try:
        json_data = unhexlify(encoded)
    except (TypeError, _BinasciiError):
        json_data = base64.b64decode(encoded)
    return json.loads(json_data.decode('utf-8'))


def parse_external_notification(data):
    """Traduit une notification JSON-RPC 'upnext_data' recue de N'IMPORTE
    QUEL addon integre a UpNext (vStream verifie reellement : son propre
    resources/lib/upnext.py::notifyUpnext() envoie exactement ce protocole,
    play_url deja resolu compris) vers le meme dict plat que consomme
    start_chaining_monitor() pour la bibliotheque locale - aucune autre
    difference de traitement ensuite entre une source externe et locale.
    None si data est illisible ou ne contient pas d'episode suivant jouable
    (fin de saison, pas de source resolue par l'addon appelant)."""
    try:
        encoded = json.loads(data)
    except (TypeError, ValueError):
        return None
    if not encoded:
        return None

    try:
        payload = _decode_notification_payload(encoded[0])
    except Exception:
        return None

    play_url = payload.get('play_url')
    if not play_url:
        return None

    next_episode = payload.get('next_episode') or {}
    art = next_episode.get('art') or {}
    return {
        'showtitle': next_episode.get('showtitle', ''),
        'season': next_episode.get('season', ''),
        'episode': next_episode.get('episode', ''),
        'title': next_episode.get('title', ''),
        'thumb': art.get('thumb', ''),
        'play_url': play_url,
    }


def _player_open(file_url):
    xbmc.executeJSONRPC(json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'Player.Open',
        'params': {'item': {'file': file_url}},
    }))


def start_chaining_monitor(next_info):
    """Lance en arriere-plan (thread demon) la surveillance qui declenchera
    le popup "Episode suivant" avec une vraie marge avant la fin reelle -
    la lecture en cours continue normalement dans le thread principal via
    watch_progress.track_playback(), completement independant de ce
    thread (aucun des deux ne modifie l'etat de l'autre)."""
    if not next_info or not next_info.get('play_url'):
        return

    thread = threading.Thread(target=_run_monitor, args=(next_info,))
    thread.daemon = True
    thread.start()


def _run_monitor(next_info):
    try:
        _monitor_and_chain(next_info)
    except Exception:
        # Ne doit jamais faire planter ce thread en silence sans laisser de
        # trace - meme raison que _poll_and_report dans service.py (jamais
        # remonter jusqu'a l'appelant, mais jamais invisible non plus).
        xbmc.log('[alldebridmc] next_up: erreur pendant la surveillance', xbmc.LOGERROR)


def _monitor_and_chain(next_info):
    player = xbmc.Player()
    monitor = xbmc.Monitor()

    notify_before = _notify_before_end()
    # Garde-fou : le compte a rebours ne doit jamais atteindre (ou depasser)
    # le delai d'affichage, sinon la marge reelle avant la fin redevient
    # nulle ou negative - exactement le probleme que ce module corrige.
    # Au moins 1s de marge garantie meme avec des reglages mal choisis.
    countdown_total = min(_autoplay_countdown(), max(1, notify_before - 1))

    waited = 0.0
    started = False
    while waited < _START_TIMEOUT:
        if monitor.waitForAbort(_MONITOR_TICK):
            return
        waited += _MONITOR_TICK
        try:
            if player.isPlaying():
                started = True
                break
        except RuntimeError:
            continue
    if not started:
        return

    while True:
        if monitor.waitForAbort(_MONITOR_TICK):
            return
        try:
            if not player.isPlaying():
                return
            position = player.getTime()
            total = player.getTotalTime()
        except RuntimeError:
            return

        if total <= 0:
            continue

        if total - position <= notify_before:
            break

    _show_popup_and_chain(player, monitor, next_info, countdown_total)


def _show_popup_and_chain(player, monitor, next_info, countdown_total):
    popup = NextEpisodePopup(
        'script-alldebridmc-nextup.xml', ADDON.getAddonInfo('path'), 'default', '1080i',
    )
    popup.set_episode_info(next_info)
    popup.show()
    popup.update_countdown(countdown_total, countdown_total)

    elapsed = 0.0

    while elapsed < countdown_total:
        if monitor.waitForAbort(_COUNTDOWN_TICK):
            popup.close()
            return
        try:
            if not player.isPlaying():
                # Lecture arretee manuellement avant la fin du compte a
                # rebours - rien a enchainer.
                popup.close()
                return
        except RuntimeError:
            popup.close()
            return

        if popup.is_cancel():
            popup.close()
            return
        if popup.is_watch_now():
            break

        elapsed += _COUNTDOWN_TICK
        popup.update_countdown(countdown_total - elapsed, countdown_total)

    popup.close()
    _player_open(next_info['play_url'])
