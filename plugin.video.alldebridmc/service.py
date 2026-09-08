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

   Cette minuterie d'inactivite ne concerne PLUS que les ecrans de listes
   (lists_home/lists_show), un changement de contenu de liste n'etant
   signale par aucun horodatage serveur - voir _maybe_auto_refresh_lists.

1bis. Rafraichissement de la reprise de lecture (ecrans watch_in_progress/
   watch_history et widgets de l'accueil) : desormais completement
   independant du point 1, voir _maybe_refresh_watch_progress pour le
   detail. Il etait auparavant soumis a la meme porte d'inactivite, ce qui
   le rendait inoperant dans le cas d'usage principal - un Kodi laisse
   allume avait consomme son unique rafraichissement bien avant que
   l'utilisateur ne revienne, d'ou un ReloadSkin manuel a chaque fois.

   Deux choses y sont maintenant separees : DETECTER (a chaque tour, coute
   presque rien, ne fait que lever un drapeau) et RAFRAICHIR (uniquement
   quand l'utilisateur revient devant l'ecran, ou qu'un ecran de reprise est
   deja affiche). Le serveur, de son cote, ne signale que les changements de
   COMPOSITION des listes, jamais les battements de position - sans quoi
   rafraichir "des qu'il y a du nouveau" rechargerait le skin en boucle
   pendant qu'on regarde un film sur un autre appareil.

   Ecran d'accueil : Container.Refresh ne rafraichit que le CONTENEUR qui a
   le focus (deja etabli) - sur l'accueil, avec plusieurs widgets, rien ne
   garantit que ce soit le bon. ReloadSkin() recharge tout, widgets compris,
   de facon fiable quel que soit le skin (verifie contre le code source de
   Kodi : SkinBuiltins.cpp) - plus lourd visuellement (bref clignotement),
   mais desormais limite a l'arrivee de l'utilisateur, jamais en rafale
   (plancher absolu), jamais sans changement reel, jamais en lecture.

2. Termine, a CHAQUE demarrage (tout premier appel de run(), avant la
   boucle), une restauration Kodi laissee en attente par kodi_backup.py -
   voir kodi_backup.apply_pending_settings_restore pour le detail de pourquoi
   les parametres JSON-RPC d'une restauration ne sont jamais appliques
   pendant la restauration elle-meme, seulement au prochain redemarrage.

3. Annonce periodique de cet appareil au serveur (voir _announce_device),
   qui sert aussi de ping de presence pour eviter qu'une table de connexion
   reseau (routeur/NAT) n'expire faute d'activite prolongee.
"""
import time

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


def _maybe_auto_refresh_lists():
    """Rafraichissement des ecrans de LISTES uniquement (lists_home/
    lists_show), inchange : minuterie d'inactivite simple, un changement de
    contenu de liste n'etant signale par aucun horodatage serveur.

    xbmc.executebuiltin direct (jamais navigation.run_refresh_action) : voir
    la docstring en tete de module - c'est ce qui garantit qu'aucune
    notification n'apparait pour un rafraichissement automatique."""
    if xbmc.Player().isPlaying():
        return
    current_path = xbmc.getInfoLabel('Container.FolderPath')
    if not current_path.startswith(_BASE_URL):
        return
    if any(action in current_path for action in _LISTS_ACTIONS):
        xbmc.executebuiltin('Container.Refresh')


# Plancher absolu entre deux rafraichissements de reprise, quoi qu'il arrive :
# filet de securite pour qu'aucun defaut futur ne puisse produire une rafale
# de ReloadSkin.
REFRESH_FLOOR_SECONDS = 300
# Au-dela de cette inactivite, l'appareil est considere comme laisse seul.
ARRIVAL_IDLE_THRESHOLD = 120
# Repasser sous ce seuil juste apres = quelqu'un vient d'agir sur la
# telecommande, donc de revenir devant l'ecran.
ARRIVAL_WAKE_IDLE = 30
# Delai apres une lecture pendant lequel une baisse d'inactivite n'est JAMAIS
# prise pour une arrivee.
#
# Regarder un episode sans toucher a la telecommande fait monter le compteur
# d'inactivite de Kodi exactement comme une absence : reprendre la
# telecommande a la fin d'un episode ressemblait donc trait pour trait a un
# retour devant l'ecran, et rechargeait le skin alors que l'utilisateur etait
# deja en train de naviguer dans ses widgets (signale en reel le 08/09/2026).
#
# Effet de bord du rechargement, tout aussi genant : il fait repartir d'un
# coup la dizaine de widgets de l'accueil, qui interrogent tous le serveur -
# heberge sur CETTE machine pour KodiMiniPC. D'ou les erreurs de connexion
# constatees a la meme minute que le rechargement (07:21:56 et 07:22:16 pour
# un rechargement a 07:22).
POST_PLAYBACK_GRACE = 600


def _maybe_refresh_watch_progress(state):
    """Rafraichit les ecrans de reprise (et l'accueil) - refondu apres audit.

    L'ancienne version etait enfermee derriere la meme porte d'inactivite
    que les listes : le rafraichissement ne partait qu'apres 30 minutes
    d'inactivite ININTERROMPUE, et une seule fois par periode. Un Kodi
    laisse allume dans une chambre avait donc deja consomme son unique
    rafraichissement des le matin ; en rentrant le soir, apres avoir regarde
    un film sur un autre appareil, le widget "En cours" restait perime et il
    fallait un ReloadSkin manuel. C'est exactement le symptome signale.

    La refonte separe deux choses qui etaient confondues :

    - DETECTER coute presque rien (un petit fichier cote serveur) et se fait
      donc a chaque tour de boucle. On se contente alors de lever un drapeau,
      SANS rien rafraichir.
    - RAFRAICHIR ne se fait qu'au moment ou ca sert : quand l'utilisateur
      revient devant l'ecran (l'inactivite retombe brutalement), ou quand un
      ecran de reprise est deja affiche sous ses yeux.

    Sans cette separation, rafraichir des qu'il y a du nouveau rechargerait
    le skin en boucle pendant qu'on regarde un film ailleurs - c'est aussi
    pour cela que le serveur ne signale desormais que les changements de
    COMPOSITION, jamais les battements de position (voir
    watch_progress.pending_watch_progress_revision)."""
    # 1. Detection - a chaque tour, sans consequence visible.
    if state['pending'] is None:
        state['pending'] = watch_progress.pending_watch_progress_revision()
    if state['pending'] is None:
        return

    now = time.time()

    # 2. Jamais pendant une lecture, ni dans la foulee d'une lecture (voir
    #    POST_PLAYBACK_GRACE : sinon la fin d'un episode passe pour une
    #    arrivee et recharge le skin sous les doigts de l'utilisateur).
    if xbmc.Player().isPlaying():
        state['last_playing_at'] = now
        return
    if now - state['last_playing_at'] < POST_PLAYBACK_GRACE:
        return

    # 3. Plancher anti-rafale.
    if now - state['last_refresh'] < REFRESH_FLOOR_SECONDS:
        return

    # 4. Le bon moment, et lui seul.
    idle = xbmc.getGlobalIdleTime()
    just_arrived = state['previous_idle'] >= ARRIVAL_IDLE_THRESHOLD and idle <= ARRIVAL_WAKE_IDLE

    current_path = xbmc.getInfoLabel('Container.FolderPath')
    on_watch_screen = (
        current_path.startswith(_BASE_URL)
        and any(action in current_path for action in _WATCH_PROGRESS_ACTIONS)
    )

    if on_watch_screen:
        # L'ecran concerne est deja affiche : Container.Refresh suffit, et
        # ne coute pratiquement rien visuellement.
        xbmc.executebuiltin('Container.Refresh')
    elif just_arrived and xbmc.getCondVisibility('Window.IsActive(home)'):
        # Accueil : Container.Refresh ne toucherait que le conteneur qui a le
        # focus, sans garantie que ce soit le bon widget. ReloadSkin recharge
        # tout de facon fiable quel que soit le skin (verifie contre le code
        # source de Kodi : SkinBuiltins.cpp) - acceptable ici parce qu'il ne
        # peut plus se produire qu'a l'arrivee, une fois, jamais en rafale.
        xbmc.executebuiltin('ReloadSkin()')
    else:
        return

    # Le marqueur n'est pose qu'ICI, apres un rafraichissement reellement
    # effectue : un rafraichissement reporte ne doit jamais perdre le signal.
    watch_progress.mark_watch_progress_seen(state['pending'])
    state['pending'] = None
    state['last_refresh'] = now


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
    # Etat du rafraichissement de reprise (voir _maybe_refresh_watch_progress) :
    # `pending` retient la revision serveur vue mais pas encore montree,
    # `previous_idle` sert a detecter le retour de l'utilisateur.
    watch_state = {'pending': None, 'last_refresh': 0.0, 'previous_idle': 0, 'last_playing_at': 0.0}

    while not monitor.waitForAbort(POLL_INTERVAL):
        elapsed_since_announce += POLL_INTERVAL
        if elapsed_since_announce >= ANNOUNCE_INTERVAL:
            elapsed_since_announce = 0
            try:
                _announce_device()
            except Exception:
                xbmc.log('[alldebridmc] service: erreur pendant _announce_device()', xbmc.LOGERROR)

        # Independant du reglage lists_refresh_interval_minutes (audit) : a 0,
        # celui-ci desactivait aussi la synchronisation de reprise, qui n'a
        # pourtant rien a voir avec les listes.
        try:
            _maybe_refresh_watch_progress(watch_state)
        except Exception:
            xbmc.log('[alldebridmc] service: erreur pendant _maybe_refresh_watch_progress()', xbmc.LOGERROR)
        watch_state['previous_idle'] = xbmc.getGlobalIdleTime()

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
                    _maybe_auto_refresh_lists()
                except Exception:
                    xbmc.log('[alldebridmc] service: erreur pendant _maybe_auto_refresh_lists()', xbmc.LOGERROR)
        else:
            idle_refresh_done = False


if __name__ == '__main__':
    run()
