# -*- coding: utf-8 -*-
"""Service Kodi persistant (xbmc.service, démarre avec Kodi).

Sonde PÉRIODIQUEMENT (pas événementiel) la base SQLite locale de vStream,
en lecture seule (voir resources/lib/vstream_db.py), pour détecter les
nouveaux points de reprise/films terminés que vStream y enregistre
LUI-MÊME à l'arrêt de chaque lecture - fonctionne aussi bien pour du
contenu lancé depuis notre addon que depuis la navigation native de
vStream, puisque c'est vStream qui écrit ces données dans les deux cas,
jamais nous (aucune modification de son code, aucune ligne de sa base
n'est jamais écrite depuis ce service).

La lecture MediaCenter est suivie séparément et en temps réel par
navigation.play_item()/track_playback() (suivi événementiel xbmc.Player,
dans le processus du script de lecture, cf. resources/lib/watch_progress.py) -
aucun rapport en double possible, ce service ne lit jamais que la base de
vStream, jamais nos propres chemins SMB.

Rafraichissement automatique (lists_refresh_interval_minutes, 0 = desactive,
30 par defaut) : demande explicitement par l'utilisateur pour un Kodi
laisse allume en continu - contrairement a l'action "Rafraichir" manuelle
(navigation.run_refresh_action, RunPlugin depuis un clic), qui elle DOIT
rester dans le processus plugin ephemere (seul endroit ou notifier a du
sens), le declenchement PERIODIQUE ne peut venir que d'ici : un plugin
Kodi ne tourne que le temps de repondre a UNE requete puis se termine, il
ne peut pas se re-declencher tout seul depuis l'interieur d'un ecran deja
affiche. Deux regles imposees par l'utilisateur, toutes les deux
verifiees ici avant tout rafraichissement :
- JAMAIS de notification pour un rafraichissement automatique (seul le
  clic manuel en montre une) - respecte simplement en n'appelant jamais
  navigation.run_refresh_action()/_notify() depuis ce chemin, qui se
  contente de xbmc.executebuiltin direct.
- JAMAIS pendant une lecture en cours, meme si l'ecran affiche au moment
  du declenchement etait un des notres avant de lancer la lecture.

Pour les ecrans de reprise de lecture (watch_in_progress/watch_history)
ET l'ecran d'accueil natif (voir plus bas pourquoi l'accueil a besoin
d'un traitement different) : ne rafraichit que si le serveur signale un
changement REEL depuis la derniere fois (watch_progress.
server_has_new_watch_progress, horodatage cote serveur mis a jour a
chaque ecriture de progression - voir watch_progress.py sur le Pi),
jamais sur une simple minuterie aveugle - demande explicitement suite au
widget "En cours" d'un skin (Arctic Horizon 2) ne refletant pas une
reprise synchronisee depuis un autre appareil sans rafraichissement
manuel. Les ecrans de listes (lists_home/lists_show) gardent eux le
comportement d'origine (minuterie simple), un changement de contenu de
liste n'etant pas signale par ce meme horodatage.

Ecran d'accueil : Container.Refresh ne rafraichit que le CONTENEUR qui a
le focus (deja etabli) - sur l'accueil, avec plusieurs widgets, rien ne
garantit que ce soit le bon. ReloadSkin() recharge tout, widgets compris,
de facon fiable quel que soit le skin (verifie contre le code source de
Kodi : SkinBuiltins.cpp) - plus lourd visuellement (bref clignotement),
mais rare (throttle par l'intervalle, jamais sans changement reel confirme
par le serveur, jamais en lecture).

Termine aussi, a CHAQUE demarrage (tout premier appel de run(), avant la
boucle), une restauration Kodi laissee en attente par kodi_backup.py -
voir kodi_backup.apply_pending_settings_restore pour le detail de pourquoi
les parametres JSON-RPC d'une restauration ne sont jamais appliques
pendant la restauration elle-meme, seulement au prochain redemarrage.
"""
import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import kodi_backup, vstream_db, watch_progress

POLL_INTERVAL = 30  # secondes entre deux sondages periodiques de secours

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')
_BASE_URL = 'plugin://plugin.video.alldebridmc/'
_LISTS_ACTIONS = ('action=lists_home', 'action=lists_show')
_WATCH_PROGRESS_ACTIONS = ('action=watch_in_progress', 'action=watch_history')


def _poll_and_report(reader):
    if not watch_progress.enabled():
        return
    device = watch_progress.device_name()
    try:
        polled = reader.poll()
    except Exception:
        # Ne doit jamais remonter jusqu'a run() : une exception ici (bug de
        # ce module, ligne inattendue en base...) stopperait alors
        # DEFINITIVEMENT ce service pour le reste de la session Kodi (pas
        # de try/except autour de la boucle while de run()) - deja arrive
        # reellement avec un bug de signature corrige ici (voir git log),
        # qui a fait taire ce service en silence apres son tout premier
        # sondage avec un resultat non vide.
        xbmc.log('[alldebridmc] service: erreur pendant poll()', xbmc.LOGERROR)
        return
    for tmdb_id, position, duration, resume_key, season, episode, smedia in polled:
        try:
            watch_progress.report_vstream(tmdb_id, position, duration, device, resume_key, season, episode, smedia)
        except Exception:
            xbmc.log('[alldebridmc] service: erreur pendant report_vstream()', xbmc.LOGERROR)


def _refresh_interval_seconds():
    try:
        minutes = ADDON.getSettingInt('lists_refresh_interval_minutes')
    except (AttributeError, TypeError):
        minutes = 0
    return minutes * 60 if minutes else 0


def _apply_pending_settings_restore():
    """Termine une restauration Kodi (voir kodi_backup.run_restore) en
    appliquant les parametres JSON-RPC laisses en attente lors du dernier
    redemarrage - voir kodi_backup.apply_pending_settings_restore pour le
    pourquoi ce n'est jamais fait tout de suite pendant la restauration
    elle-meme. Contrairement a l'auto-refresh, une notification ICI est
    voulue : elle ne peut apparaitre qu'a la suite d'une restauration
    explicitement declenchee par l'utilisateur (jamais spontanement),
    donc ne viole pas la regle "jamais de notif automatique"."""
    if kodi_backup.apply_pending_settings_restore():
        xbmc.log('[alldebridmc] service: parametres Kodi restaures au demarrage', xbmc.LOGINFO)
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30322), xbmcgui.NOTIFICATION_INFO, 5000,
        )


def _maybe_auto_refresh():
    """xbmc.executebuiltin direct (jamais navigation.run_refresh_action) :
    voir la docstring en tete de module - c'est ce qui garantit qu'aucune
    notification n'apparait pour un rafraichissement automatique."""
    if xbmc.Player().isPlaying():
        return

    current_path = xbmc.getInfoLabel('Container.FolderPath')
    on_own_screen = current_path.startswith(_BASE_URL)

    if on_own_screen and any(action in current_path for action in _LISTS_ACTIONS):
        xbmc.executebuiltin('Container.Refresh')
        return

    on_watch_screen = on_own_screen and any(action in current_path for action in _WATCH_PROGRESS_ACTIONS)
    on_home_screen = xbmc.getCondVisibility('Window.IsActive(home)')
    if not (on_watch_screen or on_home_screen):
        return

    if not watch_progress.server_has_new_watch_progress():
        return

    if on_home_screen:
        xbmc.executebuiltin('ReloadSkin()')
    else:
        xbmc.executebuiltin('Container.Refresh')


class _StopTrigger(xbmc.Player):
    """Ne sert qu'a declencher un sondage immediat des qu'une lecture
    s'arrete, en plus du sondage periodique de secours - vStream vient de
    finir d'ecrire dans sa base a cet instant precis (cPlayer._setWatched
    dans son propre code, appelee depuis onPlayBackStopped/Ended)."""

    def __init__(self, reader):
        super(_StopTrigger, self).__init__()
        self.reader = reader

    def onPlayBackStopped(self):
        _poll_and_report(self.reader)

    def onPlayBackEnded(self):
        _poll_and_report(self.reader)


def run():
    try:
        _apply_pending_settings_restore()
    except Exception:
        xbmc.log('[alldebridmc] service: erreur pendant _apply_pending_settings_restore()', xbmc.LOGERROR)

    reader = vstream_db.VStreamDbReader()
    # NE PAS SUPPRIMER cette variable, meme si aucun analyseur ne la voit
    # utilisee : elle garde une reference vivante sur le xbmc.Player, sans
    # laquelle il serait ramasse par le GC et les callbacks
    # onPlayBackStopped/Ended cesseraient silencieusement d'arriver - la
    # detection de fin de lecture vStream s'arreterait sans aucune erreur
    # visible. Sa portee (locale a run(), qui tourne toute la session)
    # suffit a le maintenir en vie.
    player = _StopTrigger(reader)  # noqa: F841
    monitor = xbmc.Monitor()
    elapsed_since_refresh = 0

    while not monitor.waitForAbort(POLL_INTERVAL):
        _poll_and_report(reader)

        interval_seconds = _refresh_interval_seconds()
        if interval_seconds:
            elapsed_since_refresh += POLL_INTERVAL
            if elapsed_since_refresh >= interval_seconds:
                elapsed_since_refresh = 0
                try:
                    _maybe_auto_refresh()
                except Exception:
                    xbmc.log('[alldebridmc] service: erreur pendant _maybe_auto_refresh()', xbmc.LOGERROR)
        else:
            elapsed_since_refresh = 0


if __name__ == '__main__':
    run()
