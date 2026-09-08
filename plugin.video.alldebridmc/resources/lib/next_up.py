# -*- coding: utf-8 -*-
"""Enchainement fiable des episodes, pour la bibliotheque locale ET pour
le contenu Pastebin (voir navigation.py::play_item()/play_pastebin_episode),
en remplacement de service.upnext qui bascule trop tard et manque parfois
l'enchainement (voir diagnostic plus bas).

Diagnostic (code source reel de service.upnext lu sur un appareil
installe, resources/lib/playbackmanager.py::show_popup_and_wait) :
service.upnext attend par conception qu'il ne reste plus qu'1 seconde ou
moins avant de basculer vers l'episode suivant - une vraie course contre
la fin naturelle du fichier, perdue plus souvent que gagnee sur nos
fichiers locaux (lecture SMB directe, quasi aucune mise en tampon).

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
import json
import threading

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


class _ChainPlayer(xbmc.Player):
    """Distingue une fin NATURELLE de fichier d'un arret volontaire.

    Indispensable pendant le compte a rebours : la video peut tres bien se
    terminer avant lui (voir _show_popup_and_chain). Une fin naturelle ne
    doit surtout pas annuler l'enchainement - seul un vrai "Annuler", ou un
    arret demande par l'utilisateur, le fait."""

    def __init__(self):
        super().__init__()
        self.ended = False
        self.stopped = False

    def onPlayBackEnded(self):
        self.ended = True

    def onPlayBackStopped(self):
        self.stopped = True

    def onPlayBackError(self):
        self.stopped = True


def _monitor_and_chain(next_info):
    player = _ChainPlayer()
    monitor = xbmc.Monitor()

    notify_before = _notify_before_end()

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

    remaining = 0.0
    while True:
        if monitor.waitForAbort(_MONITOR_TICK):
            return
        if player.stopped:
            return
        if player.ended:
            # Fin atteinte sans etre jamais passe sous le seuil d'affichage
            # (saut direct dans les dernieres secondes) : on enchaine quand
            # meme, sans popup - il n'y a plus rien a proposer.
            _player_open(next_info['play_url'])
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

        remaining = total - position
        if remaining <= notify_before:
            break

    _show_popup_and_chain(player, monitor, next_info, remaining)


def _show_popup_and_chain(player, monitor, next_info, remaining):
    """remaining : temps REELLEMENT restant au moment ou le popup apparait.

    Le compte a rebours ne peut jamais le depasser. Il etait jusqu'ici fige
    sur le reglage (20 s par defaut), calcule avant meme de savoir ou en
    etait la lecture - or si l'utilisateur saute a une vingtaine de secondes
    de la fin, la video se termine AVANT la fin du compte a rebours. Le
    lecteur s'arretait, le popup se fermait, et l'enchainement n'avait
    jamais lieu (signale en reel : "si je vais a 18 secondes avant la fin le
    popup ne se declenche pas")."""
    countdown_total = max(1.0, min(float(_autoplay_countdown()), remaining - 1.0))

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

        # L'intention de l'utilisateur passe avant tout le reste.
        if popup.is_cancel():
            popup.close()
            return
        if popup.is_watch_now():
            break
        if player.stopped:
            # Arret volontaire pendant le compte a rebours : on n'enchaine pas.
            popup.close()
            return
        if player.ended:
            # Fin naturelle du fichier : c'est le cas NORMAL quand il restait
            # moins que le compte a rebours. Surtout ne pas annuler ici.
            break

        elapsed += _COUNTDOWN_TICK
        popup.update_countdown(countdown_total - elapsed, countdown_total)

    popup.close()
    _player_open(next_info['play_url'])
