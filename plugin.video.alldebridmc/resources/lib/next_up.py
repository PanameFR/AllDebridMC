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
# Sondages consecutifs sur le MEME nouveau fichier avant de s'y ancrer, quand
# il ne correspond pas exactement a l'URL attendue (voir
# _wait_for_our_playback) : un seul suffirait a se tromper sur une valeur
# transitoire renvoyee par Kodi pendant la bascule d'un fichier a l'autre.
_ANCHOR_SETTLE_TICKS = 2


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


# ---- journal dedie -------------------------------------------------------
# Toujours actif (jamais derriere lists_debug_logging) : une dizaine de
# lignes par episode, et c'est la SEULE facon de reconstituer apres coup ce
# qui s'est reellement passe pendant un enchainement rate. Prefixe unique
# pour pouvoir tout extraire d'un kodi.log en une recherche :
#     findstr /c:"[alldebridmc] chainage" kodi.log

def log(message):
    xbmc.log('[alldebridmc] chainage: %s' % message, xbmc.LOGINFO)


def _short(file_url):
    """Nom de fichier seul : les liens AllDebrid font 150 caracteres dont
    seule la fin identifie l'episode."""
    if not file_url:
        return '(aucun)'
    return file_url.rstrip('/').rsplit('/', 1)[-1][:90]


def _playing_file(player):
    try:
        return player.getPlayingFile()
    except Exception:  # Kodi leve large quand rien ne joue
        return None


def _still_ours(player, anchor):
    """Notre fichier joue-t-il TOUJOURS ? Sert a reconnaitre un evenement
    de fin/arret qui appartient a une autre lecture : xbmc.Player() les
    delivre a toutes les surveillances en vie, sans dire de quel fichier il
    s'agit."""
    try:
        return bool(player.isPlaying()) and _playing_file(player) == anchor
    except Exception:
        return False


def _episode_label(info):
    season = info.get('season') or '?'
    episode = info.get('episode') or '?'
    show = info.get('showtitle') or info.get('title') or '?'
    return '%s S%sE%s' % (show, season, episode)


# Une seule surveillance a la fois : la plus recente est forcement celle du
# fichier qui vient de demarrer. Celles d'avant doivent se taire, meme si
# elles n'ont pas encore vu leur propre lecture s'arreter - c'est l'une des
# deux causes du bug constate le 25/09/2026 sur Code Geass (trois popups en
# 34 secondes, E06 -> E07 -> E08 enchaines en rafale).
_generation_lock = threading.Lock()
_generation = 0


def _superseded(generation):
    with _generation_lock:
        return generation != _generation


def start_chaining_monitor(next_info, expected_file=None):
    """Lance en arriere-plan (thread demon) la surveillance qui declenchera
    le popup "Episode suivant" avec une vraie marge avant la fin reelle -
    la lecture en cours continue normalement dans le thread principal via
    watch_progress.track_playback(), completement independant de ce
    thread (aucun des deux ne modifie l'etat de l'autre).

    expected_file : URL REELLE du fichier qui vient d'etre lance (lien
    AllDebrid resolu, ou URL smb:// locale). Sans elle, la surveillance
    n'avait aucun moyen de savoir a QUELLE lecture elle se rapportait :
    xbmc.Player() est global, isPlaying()/getTime() repondent pour
    n'importe quel fichier. Au moment precis d'un enchainement, l'episode
    precedent joue encore ses dernieres secondes - la surveillance du
    nouvel episode se raccrochait donc a cette fin-la, voyait "plus que
    2 secondes", et affichait aussitot son popup (constate le 25/09/2026 :
    popup a 04:26:09 pour une lecture demarree a 04:26:07).
    """
    global _generation

    if not next_info or not next_info.get('play_url'):
        log('pas d enchainement arme : aucun episode suivant connu')
        return

    with _generation_lock:
        _generation += 1
        generation = _generation

    log('arme pour %s | fichier en cours=%s | popup a -%ss, compte a rebours %ss' % (
        _episode_label(next_info), _short(expected_file),
        _notify_before_end(), _autoplay_countdown(),
    ))

    thread = threading.Thread(target=_run_monitor, args=(next_info, expected_file, generation))
    thread.daemon = True
    thread.start()


def _run_monitor(next_info, expected_file, generation):
    try:
        _monitor_and_chain(next_info, expected_file, generation)
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


def _wait_for_our_playback(player, monitor, expected_file, generation):
    """Attend que NOTRE fichier joue, et renvoie son URL (l'ancre) - jamais
    l'episode precedent qui finit encore. Renvoie None si rien de probant
    n'a demarre.

    Deux chemins, volontairement : l'egalite avec expected_file (cas
    normal : le lien AllDebrid resolu, ou l'URL smb:// locale, est
    exactement ce que getPlayingFile() renvoie), et a defaut tout fichier
    DIFFERENT de celui qui jouait a l'armement, vu stable deux sondages de
    suite - repli pour le jour ou Kodi rapporterait une URL un peu
    differente (redirection, chemin plugin://). Ce qui n'est jamais
    accepte, c'est de s'ancrer sur le fichier d'avant."""
    previous_file = _playing_file(player)
    stable = 0
    waited = 0.0

    while waited < _START_TIMEOUT:
        if monitor.waitForAbort(_MONITOR_TICK):
            return None
        waited += _MONITOR_TICK

        if _superseded(generation):
            log('abandon : une lecture plus recente a pris la main')
            return None

        current = _playing_file(player)
        if not current:
            stable = 0
            continue

        if expected_file and current == expected_file:
            log('lecture confirmee apres %.0fs : %s' % (waited, _short(current)))
            return current

        if current != previous_file:
            stable += 1
            if stable >= _ANCHOR_SETTLE_TICKS:
                log('lecture confirmee apres %.0fs (par defaut) : %s' % (waited, _short(current)))
                return current
        else:
            stable = 0

    log('abandon : aucune lecture a nous en %ss (toujours %s)' % (
        _START_TIMEOUT, _short(previous_file)))
    return None


def _monitor_and_chain(next_info, expected_file, generation):
    player = _ChainPlayer()
    monitor = xbmc.Monitor()

    notify_before = _notify_before_end()

    anchor = _wait_for_our_playback(player, monitor, expected_file, generation)
    if anchor is None:
        return

    # Les evenements recus AVANT l'ancrage appartiennent a la lecture
    # precedente (sa fin naturelle, justement, puisque c'est elle qui vient
    # de nous enchainer) : xbmc.Player() les delivre a tout le monde. Les
    # garder faisait enchainer l'episode d'APRES immediatement, sans meme
    # attendre le popup - deuxieme cause du bug du 25/09/2026.
    player.ended = False
    player.stopped = False

    remaining = 0.0
    duration_logged = False
    while True:
        if monitor.waitForAbort(_MONITOR_TICK):
            return
        if _superseded(generation):
            log('abandon : une lecture plus recente a pris la main')
            return
        if (player.stopped or player.ended) and _still_ours(player, anchor):
            # Evenement de fin/arret qui ne nous concerne pas : il vient de
            # la lecture precedente, qui s'est terminee APRES notre ancrage
            # (course de quelques dixiemes de seconde pendant la bascule).
            # Notre fichier, lui, joue toujours.
            player.stopped = False
            player.ended = False
        if player.stopped:
            log('abandon : lecture arretee avant le popup')
            return
        if player.ended:
            # Fin atteinte sans etre jamais passe sous le seuil d'affichage
            # (saut direct dans les dernieres secondes) : on enchaine quand
            # meme, sans popup - il n'y a plus rien a proposer.
            log('fin du fichier sans etre passe par le popup (saut) -> %s' % _episode_label(next_info))
            _player_open(next_info['play_url'])
            return
        try:
            if not player.isPlaying():
                log('abandon : plus rien ne joue')
                return
            current = _playing_file(player)
            position = player.getTime()
            total = player.getTotalTime()
        except RuntimeError:
            log('abandon : lecteur indisponible')
            return

        if current and current != anchor:
            log('abandon : un autre fichier joue maintenant (%s)' % _short(current))
            return

        if total <= 0:
            continue

        if not duration_logged:
            log('suivi de %s | duree %.0fs | popup prevu a %.0fs' % (
                _short(anchor), total, max(0.0, total - notify_before)))
            duration_logged = True

        remaining = total - position
        if remaining <= notify_before:
            break

    _show_popup_and_chain(player, monitor, next_info, remaining, generation, anchor)


def _show_popup_and_chain(player, monitor, next_info, remaining, generation, anchor):
    """remaining : temps REELLEMENT restant au moment ou le popup apparait.

    Le compte a rebours ne peut jamais le depasser. Il etait jusqu'ici fige
    sur le reglage (20 s par defaut), calcule avant meme de savoir ou en
    etait la lecture - or si l'utilisateur saute a une vingtaine de secondes
    de la fin, la video se termine AVANT la fin du compte a rebours. Le
    lecteur s'arretait, le popup se fermait, et l'enchainement n'avait
    jamais lieu (signale en reel : "si je vais a 18 secondes avant la fin le
    popup ne se declenche pas")."""
    countdown_total = max(1.0, min(float(_autoplay_countdown()), remaining - 1.0))

    log('popup affiche a -%.0fs de la fin | compte a rebours %.0fs | propose %s' % (
        remaining, countdown_total, _episode_label(next_info)))

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
            log('popup annule par l utilisateur apres %.0fs' % elapsed)
            popup.close()
            return
        if popup.is_watch_now():
            log('"Lire maintenant" apres %.0fs' % elapsed)
            break
        if _superseded(generation):
            log('popup ferme : une lecture plus recente a pris la main')
            popup.close()
            return
        if player.stopped:
            if _still_ours(player, anchor):
                player.stopped = False  # arret d'une AUTRE lecture (voir _still_ours)
            else:
                # Arret volontaire pendant le compte a rebours : on n'enchaine pas.
                log('lecture arretee pendant le compte a rebours : pas d enchainement')
                popup.close()
                return
        if player.ended:
            # Fin naturelle du fichier : c'est le cas NORMAL quand il restait
            # moins que le compte a rebours. Surtout ne pas annuler ici -
            # sauf si notre fichier joue encore, auquel cas l'evenement
            # venait d'une autre lecture (voir _still_ours).
            if _still_ours(player, anchor):
                player.ended = False
            else:
                log('fin naturelle du fichier pendant le compte a rebours')
                break

        elapsed += _COUNTDOWN_TICK
        popup.update_countdown(countdown_total - elapsed, countdown_total)

    popup.close()
    log('ouverture de %s' % _episode_label(next_info))
    _player_open(next_info['play_url'])
