# -*- coding: utf-8 -*-
"""Service Kodi persistant (xbmc.service, démarre avec Kodi).

Depuis le retrait de la dépendance à vStream (résolution/lecture directe
du contenu Pastebin, voir resources/lib/pastebin_playback.py) et à
service.upnext (enchaînement propre à l'addon, voir resources/lib/next_up.py),
ce service n'a plus que trois responsabilités, aucune ne nécessitant de
sondage de base tierce :

1. Rafraîchissement automatique (lists_refresh_interval_minutes, 0 = desactive,
   30 par defaut) : demande explicitement par l'utilisateur pour un Kodi
   laisse allume en continu. Declenche apres N minutes d'INACTIVITE reelle
   (xbmc.getGlobalIdleTime(), pas un simple minuteur ecoule) - signale en
   conditions reelles : un minuteur aveugle pouvait rafraichir en pleine
   navigation active. Contrairement a l'action "Rafraichir" manuelle
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

2. Termine, a CHAQUE demarrage (tout premier appel de run(), avant la
   boucle), une restauration Kodi laissee en attente par kodi_backup.py -
   voir kodi_backup.apply_pending_settings_restore pour le detail de pourquoi
   les parametres JSON-RPC d'une restauration ne sont jamais appliques
   pendant la restauration elle-meme, seulement au prochain redemarrage.

3. Annonce periodique de cet appareil au serveur (voir _announce_device),
   qui sert aussi de ping de presence pour eviter qu'une table de connexion
   reseau (routeur/NAT) n'expire faute d'activite prolongee.
"""
import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import kodi_backup, watch_progress

POLL_INTERVAL = 30  # secondes entre deux tours de boucle

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_ID = ADDON.getAddonInfo('id')
_BASE_URL = 'plugin://plugin.video.alldebridmc/'
_LISTS_ACTIONS = ('action=lists_home', 'action=lists_show')
_WATCH_PROGRESS_ACTIONS = ('action=watch_in_progress', 'action=watch_history')


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


ANNOUNCE_INTERVAL = 10 * 60  # secondes entre deux annonces au serveur


def _announce_device():
    """Fait connaitre cet appareil au serveur (nom configure + versions),
    qui les affiche sur sa page Reglages - voir kodi_api.record_device cote
    serveur. Purement informatif : un echec (serveur eteint, reseau coupe)
    est sans consequence, on reessaiera a la prochaine echeance.

    Sert aussi de ping de presence leger et frequent (10 min), pour eviter
    qu'une table de connexion (routeur/NAT) ou une mise en veille reseau
    n'expire faute d'activite prolongee - premiere requete suivante alors en
    echec ("impossible de joindre le serveur"), deja constate reellement sur
    KodiMiniPC apres de longues periodes d'inactivite. Ce ping n'affiche
    jamais rien (meme raison que le reste de ce module : jamais de
    notification/chargement hors d'une action explicite de l'utilisateur),
    un echec est ignore exactement comme avant."""
    from resources.lib import api_client, navigation
    try:
        api_client.ping(**navigation.device_identity())
    except api_client.ApiError as exc:
        xbmc.log('[alldebridmc] service: ping serveur echoue ({0})'.format(exc), xbmc.LOGWARNING)


def run():
    try:
        _apply_pending_settings_restore()
    except Exception:
        xbmc.log('[alldebridmc] service: erreur pendant _apply_pending_settings_restore()', xbmc.LOGERROR)

    try:
        _announce_device()
    except Exception:
        xbmc.log('[alldebridmc] service: erreur pendant _announce_device()', xbmc.LOGERROR)

    monitor = xbmc.Monitor()
    idle_refresh_done = False
    elapsed_since_announce = 0

    while not monitor.waitForAbort(POLL_INTERVAL):
        elapsed_since_announce += POLL_INTERVAL
        if elapsed_since_announce >= ANNOUNCE_INTERVAL:
            elapsed_since_announce = 0
            try:
                _announce_device()
            except Exception:
                xbmc.log('[alldebridmc] service: erreur pendant _announce_device()', xbmc.LOGERROR)

        interval_seconds = _refresh_interval_seconds()
        if interval_seconds:
            # Base sur l'inactivite reelle (xbmc.getGlobalIdleTime(), deja
            # fourni par Kodi - dernier clic/touche/mouvement, tous
            # peripheriques confondus) plutot que sur un simple minuteur
            # ecoule depuis le dernier rafraichissement : sinon le
            # rafraichissement pouvait tomber en pleine navigation active
            # (ex. en train de parcourir une liste), demande explicitement
            # a corriger. idle_refresh_done evite de re-declencher a
            # chaque tick tant que l'inactivite reste au-dessus du seuil -
            # une seule fois par periode d'inactivite, remise a zero des
            # que l'utilisateur touche a nouveau a quelque chose.
            idle_seconds = xbmc.getGlobalIdleTime()
            if idle_seconds < interval_seconds:
                idle_refresh_done = False
            elif not idle_refresh_done:
                idle_refresh_done = True
                try:
                    _maybe_auto_refresh()
                except Exception:
                    xbmc.log('[alldebridmc] service: erreur pendant _maybe_auto_refresh()', xbmc.LOGERROR)
        else:
            idle_refresh_done = False


if __name__ == '__main__':
    run()
