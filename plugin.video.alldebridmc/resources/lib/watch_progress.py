# -*- coding: utf-8 -*-
"""Reprise de lecture synchronisée entre appareils Kodi, via le serveur
(watch_progress.py côté Pi) - et écrans "En cours"/"Historique", pour le
contenu du MediaCenter ET pour le contenu Pastebin (résolu et lu
directement, voir pastebin_playback.py - étapes 1/2 du chantier de
suppression de vStream).

Suivi de lecture MediaCenter (locale) : pas de service.py séparé pour
cette partie. main.py appelle juste navigation.route(...) puis termine -
rien n'oblige le script à revenir vite après xbmcplugin.setResolvedUrl()
(qui débloque immédiatement le lecteur Kodi ; le timeout de résolution ne
s'applique qu'à la phase AVANT cet appel). track_playback() est donc
appelée à la suite, dans le même script, et bloque jusqu'à la fin de la
lecture - pattern réel, déjà utilisé par des addons de scrobbling Kodi.

Suivi de lecture Pastebin (films ET épisodes, précisément) : même
principe, track_playback_episode()/report_vstream() appelés dans le même
script que play_pastebin_movie()/play_pastebin_episode() (voir
navigation.py), dans un thread démon pour ne jamais bloquer le retour de
l'action RunPlugin. Le suffixe "vstream" de ces fonctions (report_vstream,
get_watch_progress_vstream, post_watch_progress_vstream...) est un nom
historique - vStream n'est plus impliqué du tout depuis les étapes 1/2 du
chantier de suppression de vStream, le contenu vient entièrement de la
source Pastebin résolue directement. Jamais renommé depuis (identique
côté serveur, source de vérité partagée) pour ne pas invalider les
entrées déjà stockées.

Import de navigation en tête (build_list_item) : c'est pour ça que
navigation.py importe CE module en différé (voir route()/play_item()) et
jamais l'inverse, pour éviter un cycle.
"""
import json
import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib import api_client, navigation

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_ID = ADDON.getAddonInfo('id')

TICK = 1  # secondes entre deux mesures LOCALES de la position (aucun reseau)
HEARTBEAT_INTERVAL = 60  # secondes entre deux envois pendant la lecture ACTIVE
START_TIMEOUT = 45  # secondes max d'attente que la lecture demarre vraiment
# Au-dela de la duree du media + cette marge, le traqueur s'arrete quoi qu'il
# arrive - dernier filet contre un traqueur qui survivrait a sa lecture
# (voir _track_playback).
MAX_TRACK_OVERRUN = 900
# Le fichier suivi n'est verrouille que pendant les toutes premieres
# secondes : passe ce delai, un traqueur qui n'a pas encore su a quoi il
# s'accrochait ne doit surtout pas s'accrocher a la lecture SUIVANTE.
ANCHOR_GRACE = 10
# En dessous, la position n'a pas vraiment bouge (lecture en pause, ou deux
# mesures qui se croisent) - rien a envoyer.
POSITION_EPSILON = 1.0

_STATUS_BY_ACTION = {'watch_in_progress': 'in_progress', 'watch_history': 'watched'}
_LABEL_BY_ACTION = {'watch_in_progress': 30250, 'watch_history': 30251}


def enabled():
    try:
        return ADDON.getSettingBool('watch_progress_enabled')
    except (AttributeError, TypeError):
        return True


def device_name():
    """Repli sur le nom d'hote que Kodi connait deja quand le reglage est
    vide : constate en reel lors de l'audit, 377 des 430 entrees du serveur
    n'avaient AUCUN nom d'appareil, et la reprise annoncait alors "depuis ?".
    Le reglage explicite reste prioritaire quand il est renseigne."""
    try:
        configured = (ADDON.getSettingString('device_name') or '').strip()
    except (AttributeError, TypeError):
        configured = ''
    if configured:
        return configured
    return (xbmc.getInfoLabel('System.FriendlyName') or '').strip()


_LAST_SEEN_UPDATE_FILENAME = 'last_seen_watch_progress_update.json'


def _last_seen_update_path():
    root = xbmcvfs.translatePath('special://home/userdata/addon_data/{0}/'.format(ADDON_ID))
    return os.path.join(root, _LAST_SEEN_UPDATE_FILENAME)


def _read_last_seen_revision():
    try:
        with open(_last_seen_update_path(), 'r', encoding='utf-8') as fh:
            return json.load(fh).get('revision')
    except (OSError, ValueError, AttributeError):
        return None


def _write_last_seen_revision(value):
    path = _last_seen_update_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'revision': value}, fh)
    except OSError:
        pass


def pending_watch_progress_revision():
    """Revision du serveur si elle differe de la derniere vue ici, None
    sinon (ou si le serveur est injoignable). Utilisee par service.py pour
    savoir s'il y a quelque chose de nouveau a montrer.

    Compare une REVISION STRUCTURELLE, jamais un horodatage d'ecriture
    (audit) : cote serveur, l'horodatage bouge a chaque battement de
    position, soit ~360 fois pour un film de 2 h. Un appareil au repos qui
    se serait fie a lui aurait recharge son skin en boucle pendant qu'on
    regarde un film sur un AUTRE appareil. La revision, elle, ne bouge que
    quand la composition des ecrans change - 2 fois pour ce meme film.

    Ne consomme RIEN : le marqueur local n'est pose qu'apres un
    rafraichissement reellement effectue (mark_watch_progress_seen), sinon
    un rafraichissement reporte - lecture en cours, plancher anti-rafale -
    perdrait definitivement le signal."""
    try:
        remote = api_client.get_watch_progress_last_updated()
    except api_client.ApiError:
        return None

    if not isinstance(remote, dict):
        return None
    revision = remote.get('revision')
    if revision is None or revision == _read_last_seen_revision():
        return None
    return revision


def mark_watch_progress_seen(revision):
    """A appeler UNIQUEMENT apres un rafraichissement reellement effectue
    (voir pending_watch_progress_revision). Fichier a part, pas un reglage
    de l'addon - meme logique que le marqueur de kodi_backup.py."""
    _write_last_seen_revision(revision)


def _format_time(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return '{0:d}:{1:02d}:{2:02d}'.format(hours, minutes, secs)
    return '{0:d}:{1:02d}'.format(minutes, secs)


# ---- reprise avant lecture (appelé depuis navigation.play_item) ----------

def _apply_resume(info, list_item, position, duration, title, device):
    """Reprend DIRECTEMENT, sans rien demander, et se contente de l'annoncer
    par une notification qui ne bloque pas (demande explicite : "j'arrive je
    lance l'episode ou le film ca reprend direct").

    Remplace un dialogue yesno pose a chaque lancement, dont la branche
    "non" appelait clear_watch_progress() : repondre non par reflexe - ou
    simplement pour verifier de quel episode il s'agissait - effacait
    definitivement la progression sur TOUS les appareils a la fois. Plus
    aucune suppression en effet de bord ici ; seules l'action explicite
    "Retirer" (voir _action_clear) et l'entree "Lire depuis le debut" du
    menu contextuel touchent encore a la progression.

    list_item : UNIQUEMENT necessaire quand la lecture demarre via
    xbmc.Player().play() (jamais setResolvedUrl - voir play_pastebin_movie/
    play_pastebin_episode). Constate en conditions reelles :
    VideoInfoTag.setResumePoint() est bien lu par Kodi pour la reprise
    NATIVE d'un item resolu via setResolvedUrl/la bibliotheque, mais
    totalement ignore par Player().play() - la video repart de zero. Seule
    la propriete ListItem "StartOffset" (en secondes, chaine) fait
    reellement seeker Player().play() au bon endroit."""
    info.setResumePoint(float(position), float(duration))
    if list_item is not None:
        list_item.setProperty('StartOffset', str(position))

    if device:
        message = ADDON.getLocalizedString(30383).format(_format_time(position), device)
    else:
        message = ADDON.getLocalizedString(30382).format(_format_time(position))
    xbmcgui.Dialog().notification(
        title or ADDON_NAME, message, xbmcgui.NOTIFICATION_INFO, 4000,
    )


def maybe_apply_resume(info, relative_path, title, list_item=None, from_start=False):
    """from_start : pose par l'entree "Lire depuis le debut" du menu
    contextuel (voir navigation.build_list_item) - la seule facon de
    repartir de zero maintenant que la reprise ne pose plus de question."""
    if not relative_path or not enabled() or from_start:
        return

    try:
        progress = api_client.get_watch_progress(relative_path)
    except api_client.ApiError:
        return  # ne bloque jamais la lecture pour un probleme reseau

    if not progress:
        return

    position, duration = progress.get('position'), progress.get('duration')
    if not position or not duration:
        return

    _apply_resume(info, list_item, position, duration, title, progress.get('device'))


def maybe_apply_resume_episode(info, tmdb_id, season, episode, title, list_item=None, from_start=False):
    """Etape 2 du chantier de suppression de vStream : meme reprise que
    maybe_apply_resume, sur l'identite tmdb_id/saison/episode (deja precise
    cote serveur, voir get_watch_progress_vstream) plutot qu'un chemin -
    appelee depuis navigation.py::play_pastebin_episode, juste avant
    xbmc.Player().play()."""
    if not enabled() or from_start:
        return

    try:
        progress = api_client.get_watch_progress_vstream(int(tmdb_id), season=int(season), episode=int(episode))
    except (api_client.ApiError, TypeError, ValueError):
        return

    if not progress:
        return

    position, duration = progress.get('position'), progress.get('duration')
    if not position or not duration:
        return

    _apply_resume(info, list_item, position, duration, title, progress.get('device'))


# ---- suivi pendant/apres lecture (appelé depuis navigation.play_item) ----

class _ProgressPlayer(xbmc.Player):
    """`flush` : un evenement vient de se produire (pause, reprise, saut de
    chapitre...) et merite un envoi immediat plutot que d'attendre le
    prochain battement - c'est ce qui rend la position exacte au moment ou
    l'utilisateur risque de quitter."""

    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False
        self.flush = False

    def onAVStarted(self):
        self.started = True

    def onPlayBackPaused(self):
        self.flush = True

    def onPlayBackResumed(self):
        self.flush = True

    def onPlayBackSeek(self, time, seekOffset):
        self.flush = True

    def onPlayBackSeekChapter(self, chapter):
        self.flush = True

    def onPlayBackStopped(self):
        self.stopped = True

    def onPlayBackEnded(self):
        self.stopped = True

    def onPlayBackError(self):
        self.stopped = True


def _playing_file(player):
    try:
        return player.getPlayingFile()
    except (RuntimeError, Exception):  # noqa: B014 - Kodi leve large ici
        return None


def _report(relative_path, position, duration, device):
    try:
        api_client.post_watch_progress(relative_path, position, duration, device)
    except api_client.ApiError:
        pass  # best-effort : un heartbeat rate ne doit jamais interrompre la lecture ni notifier


# ---- suivi des films vStream (service.py, sondage de sa base SQLite) -----

def report_vstream(tmdb_id, position, duration, device, resume_key=None, season=None, episode=None, smedia=None):
    try:
        api_client.post_watch_progress_vstream(
            tmdb_id, position, duration, device,
            resume_key=resume_key, season=season, episode=episode, smedia=smedia,
        )
    except api_client.ApiError:
        pass  # best-effort, meme raison que _report() pour le local


def _track_playback(report_fn):
    """Commun a track_playback/track_playback_episode : bloque jusqu'a la
    fin de la lecture en cours (voir docstring de tete de module), rapporte
    via report_fn(position, duration, device).

    Deux corrections d'audit, toutes deux essentielles.

    1. ANCRAGE AU FICHIER SUIVI. L'ancienne boucle ne se terminait que si
       `player.stopped` etait vrai EN TETE de tour ; sa branche
       "not player.isPlaying(): continue" repartait au waitForAbort sans
       jamais sortir. Quand onPlayBackStopped n'atteignait pas cette
       instance - script plugin ephemere pour la bibliotheque locale,
       thread demon pour Pastebin - le traqueur survivait indefiniment et
       continuait a interroger xbmc.Player(), qui est GLOBAL : il renvoyait
       la video lue A CET INSTANT. Chaque fantome reecrivait donc sa vieille
       cle avec la position d'un AUTRE film, toutes les 20 s.
       Degats reels retrouves dans les donnees : quatre films portaient la
       meme duree a la milliseconde (6170,624 s), trois d'entre eux marques
       "vus" a 99,9 % sans avoir ete regardes. Meme signature cote Pastebin.
       Le fichier en cours est desormais compare a chaque tour ; des qu'il
       change, ce traqueur n'a plus rien a dire et sort.

    2. MESURE LOCALE A LA SECONDE, ENVOI SUR EVENEMENT. L'ancien rapport
       final reutilisait la position du dernier battement, soit jusqu'a 20 s
       de retard sur l'arret reel. On mesure maintenant toutes les secondes
       en memoire (aucun reseau) et on n'envoie que sur evenement (pause,
       reprise, saut, arret, fin) ou battement espace - plus precis ET moins
       de requetes qu'avant.
       Corollaire : rien n'est envoye tant que la position ne bouge pas, ce
       qui neutralise l'appareil laisse EN PAUSE. isPlaying() y reste vrai,
       et ces media centers restent allumes en permanence : un Kodi oublie
       en pause reecrivait la cle partagee en boucle et defaisait la
       progression faite ailleurs.
    """
    player = _ProgressPlayer()
    monitor = xbmc.Monitor()
    device = device_name()

    waited = 0
    while not player.started and waited < START_TIMEOUT:
        if monitor.waitForAbort(TICK):
            return
        waited += TICK

    if not player.started:
        # La lecture n'a jamais vraiment demarre (erreur, SMB injoignable...)
        # - Kodi affiche deja sa propre erreur, rien a rapporter.
        return

    tracked_file = _playing_file(player)
    last_position, last_duration = 0.0, 0.0
    sent_position = None
    since_send = 0
    alive = 0

    def _moved():
        return sent_position is None or abs(last_position - sent_position) >= POSITION_EPSILON

    while not player.stopped:
        if monitor.waitForAbort(TICK):
            break
        since_send += TICK
        alive += TICK

        if player.stopped:
            break
        if not player.isPlaying():
            continue

        current_file = _playing_file(player)
        if tracked_file is None and alive <= ANCHOR_GRACE:
            # L'ancrage n'a pas pu etre pris au demarrage (course avec Kodi) :
            # on le rattrape, mais UNIQUEMENT dans les premieres secondes -
            # au-dela, s'accrocher a ce qui joue reviendrait a devenir le
            # fantome que ce mecanisme doit empecher.
            tracked_file = current_file
        elif tracked_file and current_file and current_file != tracked_file:
            break

        try:
            last_position = player.getTime()
            last_duration = player.getTotalTime()
        except Exception:
            continue

        # Plafond de vie absolu : meme si l'ancrage et les callbacks
        # echouaient tous les deux, aucun traqueur ne survit tres au-dela
        # de la duree de son propre media.
        if last_duration and alive > last_duration + MAX_TRACK_OVERRUN:
            break

        if player.flush:
            player.flush = False
        elif since_send < HEARTBEAT_INTERVAL:
            continue

        if _moved():
            report_fn(last_position, last_duration, device)
            sent_position = last_position
        since_send = 0

    # Rapport final : la position date de moins d'une seconde, plus du
    # dernier battement (voir point 2 de la docstring).
    if last_duration and _moved():
        report_fn(last_position, last_duration, device)


def track_playback(relative_path):
    if not relative_path or not enabled():
        return
    _track_playback(lambda position, duration, device: _report(relative_path, position, duration, device))


def track_playback_episode(tmdb_id, season, episode):
    """Etape 2 du chantier de suppression de vStream : meme suivi que
    track_playback, mais rapporte par identite tmdb_id/saison/episode
    (report_vstream, deja precise - voir play_pastebin_episode) plutot que
    par chemin."""
    if not enabled():
        return
    _track_playback(
        lambda position, duration, device: report_vstream(
            tmdb_id, position, duration, device, season=season, episode=episode,
        )
    )


# ---- ecrans "En cours" / "Historique" -------------------------------------

def dispatch(base_url, handle, params):
    action = params.get('action')

    if action == 'watch_clear':
        _action_clear(params)
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        return

    if action == 'watch_show_seasons':
        _render_show_seasons(base_url, handle, params)
        return

    if action == 'watch_show_episodes':
        _render_show_episodes(base_url, handle, params)
        return

    _render_list(base_url, handle, action, params)


def _action_clear(params):
    source = params.get('source', 'local')
    title = params.get('title', '')
    try:
        if source == 'vstream':
            tmdb_id = params.get('tmdb_id', '')
            if not tmdb_id.isdigit():
                return
            season, episode = params.get('season'), params.get('episode')
            if season is not None and episode is not None:
                api_client.clear_watch_progress_vstream(int(tmdb_id), season=int(season), episode=int(episode))
            else:
                api_client.clear_watch_progress_vstream(int(tmdb_id))
        else:
            relative_path = params.get('path', '')
            if not relative_path:
                return
            api_client.clear_watch_progress(relative_path)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        return
    # Confirmation explicite du succes (jamais affichee avant) : voir
    # docstring de _add_remove_context_item pour le pourquoi - le seul
    # retour visuel fiable tant qu'un widget d'accueil ne se rafraichit pas
    # forcement tout de suite.
    xbmcgui.Dialog().notification(
        ADDON_NAME,
        ADDON.getLocalizedString(30350).format(title) if title else ADDON.getLocalizedString(30256),
        xbmcgui.NOTIFICATION_INFO, 3000,
    )
    xbmc.executebuiltin('Container.Refresh')


def _render_list(base_url, handle, action, params):
    status = _STATUS_BY_ACTION.get(action)
    if status is None:
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    # Categorie (Films/Series/Documentaires/... ou "Autres") - s'applique
    # de la meme facon a "En cours" et a "Historique", tous deux scindes
    # par categorie. Absent = toutes categories confondues.
    category = params.get('category')

    try:
        entries = api_client.list_watch_progress(status, category=category)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    label = ADDON.getLocalizedString(_LABEL_BY_ACTION[action])
    if category:
        category_label = navigation.watch_category_label(category)
        if category_label:
            label = '%s - %s' % (label, category_label)
    xbmcplugin.setPluginCategory(handle, label)
    xbmcplugin.setContent(handle, 'episodes' if any(e.get('episode_info') for e in entries) else 'movies')

    items = []
    for entry in entries:
        watch_progress_info = entry.get('watch_progress') or {}
        if watch_progress_info.get('source') == 'vstream':
            url, list_item, is_folder = _build_vstream_item(base_url, entry)
        else:
            url, list_item, is_folder = navigation.build_list_item(base_url, entry)
        _apply_visuals(list_item, watch_progress_info, watched=(status == 'watched'))
        _add_remove_context_item(list_item, base_url, entry, watch_progress_info)
        items.append((url, list_item, is_folder))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    # Deja trie par le serveur (plus recent d'abord) : on garde cet ordre
    # plutot que le tri natif de Kodi, meme raison que list_directory().
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=False)


def _apply_visuals(list_item, progress, watched):
    info = list_item.getVideoInfoTag()
    if watched:
        # Coche "vu" native de Kodi, meme convention visuelle que le reste
        # de l'interface pour du contenu deja regarde.
        info.setPlaycount(1)
        return
    if not progress:
        return
    position, duration = progress.get('position'), progress.get('duration')
    if position and duration:
        # Barre de progression native Kodi sur la vignette (skin Estuary) -
        # affichage seulement, la vraie proposition de reprise reste le
        # dialogue de maybe_apply_resume() au moment de lancer la lecture.
        info.setResumePoint(float(position), float(duration))


def _build_vstream_item(base_url, entry):
    """ListItem pour un film OU une SERIE suivi (jamais un episode precis -
    voir docstring en tete de module) - jamais navigation.build_list_item,
    qui suppose un chemin local (entry['path'] est None ici). Nom du module
    ("vstream") historique - le contenu vient de la source Pastebin,
    resolu directement (etapes 1/2 du chantier de suppression de vStream),
    jamais vStream lui-meme depuis ce point.

    Film : resolution directe (action play_pastebin_movie, voir
    pastebin_playback.py) - meme chemin que lists_gui.render_list().

    Serie : cible = notre propre ecran Saisons (action watch_show_seasons)
    - l'episode reel n'est connu qu'au clic sur un episode precis (voir
    _render_show_episodes)."""
    poster = entry.get('poster') or {}
    title = poster.get('title') or entry.get('name') or '?'
    year = poster.get('year')
    is_series = poster.get('media_type') == 'tv'

    label = '{0} ({1})'.format(title, year) if year else title

    list_item = xbmcgui.ListItem(label=label, offscreen=True)
    if poster.get('poster_url'):
        art = {'thumb': poster['poster_url'], 'poster': poster['poster_url']}
        if poster.get('fanart_url'):
            art['fanart'] = poster['fanart_url']
        if poster.get('landscape_url'):
            art['landscape'] = poster['landscape_url']
        list_item.setArt(art)

    info = list_item.getVideoInfoTag()
    info.setTitle(label)
    info.setMediaType('tvshow' if is_series else 'movie')
    if year:
        info.setYear(int(year))
    if poster.get('overview'):
        info.setPlot(poster['overview'])
    if poster.get('rating'):
        info.setRating(float(poster['rating']))
    if poster.get('runtime'):
        info.setDuration(int(poster['runtime']) * 60)  # TMDB : minutes -> Kodi attend des secondes

    tmdb_id = poster.get('tmdb_id')
    if is_series:
        url = navigation.build_watch_action_url(
            base_url, 'watch_show_seasons', tmdb_id=tmdb_id, title=title, smedia=poster.get('smedia') or '',
        )
        is_folder = True
    else:
        url = navigation.build_watch_action_url(
            base_url, 'play_pastebin_movie', tmdb_id=tmdb_id, title=title, thumb=poster.get('poster_url') or '',
        )
        is_folder = False
    return url, list_item, is_folder


def _render_show_seasons(base_url, handle, params):
    """Ecran "Saisons" pour une serie vStream suivie (En cours/Historique) -
    construit depuis pastebin_catalog.py cote serveur (jamais vStream
    directement), pour garder la main jusqu'au clic sur l'episode precis
    (voir _render_show_episodes) et pouvoir semer la bonne reprise a ce
    moment-la, jamais avant."""
    tmdb_id = params.get('tmdb_id', '')
    title = params.get('title', '')
    smedia = params.get('smedia') or None

    try:
        data = api_client.get_watch_progress_vstream_seasons(tmdb_id)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    xbmcplugin.setPluginCategory(handle, title or data.get('title') or '')
    xbmcplugin.setContent(handle, 'seasons')

    items = []
    for season_entry in data.get('seasons') or []:
        season = season_entry['season']
        li = xbmcgui.ListItem(label=ADDON.getLocalizedString(30314) % season, offscreen=True)
        info = li.getVideoInfoTag()
        info.setMediaType('season')
        info.setSeason(int(season))
        if season_entry.get('overview'):
            info.setPlot(season_entry['overview'])
        if season_entry.get('poster_url'):
            li.setArt({'thumb': season_entry['poster_url'], 'poster': season_entry['poster_url']})
        url = navigation.build_watch_action_url(
            base_url, 'watch_show_episodes', tmdb_id=tmdb_id, season=season,
            title=title or data.get('title') or '', smedia=smedia or data.get('smedia') or '',
        )
        items.append((url, li, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def _render_show_episodes(base_url, handle, params):
    """Ecran "Episodes" d'UNE saison precise. Chaque item pointe vers
    l'action play_pastebin_episode (RunPlugin, resolution directe - voir
    navigation.py) : plus de reprise a semer dans une base tierce, notre
    propre dialogue (maybe_apply_resume_episode, precis par episode cote
    serveur) suffit desormais seul.

    Transmet aussi l'episode SUIVANT (dans cette meme saison, meme
    limite que build_list_item pour le local - jamais entre deux saisons)
    pour l'enchainement (voir navigation.py::play_pastebin_episode) -
    jusqu'ici uniquement cable pour la bibliotheque locale, jamais pour
    Pastebin."""
    tmdb_id_raw = params.get('tmdb_id', '')
    season_raw = params.get('season', '')
    title = params.get('title', '')

    try:
        episodes = api_client.get_watch_progress_vstream_episodes(tmdb_id_raw, season_raw)
    except api_client.ApiError:
        xbmcgui.Dialog().notification(
            ADDON_NAME, ADDON.getLocalizedString(30012), xbmcgui.NOTIFICATION_ERROR, 5000,
        )
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    xbmcplugin.setPluginCategory(handle, '{0} - Saison {1}'.format(title, season_raw))
    xbmcplugin.setContent(handle, 'episodes')

    items = []
    for i, entry in enumerate(episodes):
        episode = entry.get('episode')
        progress = entry.get('progress')

        label = ADDON.getLocalizedString(30315) % episode
        if entry.get('name'):
            label += ' - {0}'.format(entry['name'])
        li = xbmcgui.ListItem(label=label, offscreen=True)
        info = li.getVideoInfoTag()
        info.setMediaType('episode')
        info.setEpisode(int(episode))
        if entry.get('overview'):
            info.setPlot(entry['overview'])
        if entry.get('poster_url'):
            li.setArt({'thumb': entry['poster_url'], 'poster': entry['poster_url']})
        if entry.get('watched'):
            # Coche "vu" native de Kodi (audit) : cet ecran posait bien une
            # barre de reprise, mais ne marquait JAMAIS un episode comme vu -
            # en parcourant une saison, rien ne distinguait ce qui avait
            # deja ete regarde.
            info.setPlaycount(1)
        elif progress and progress.get('position') and progress.get('duration'):
            info.setResumePoint(float(progress['position']), float(progress['duration']))

        url_params = dict(
            tmdb_id=tmdb_id_raw, season=season_raw, episode=episode,
            title=title, thumb=entry.get('poster_url') or '',
        )
        next_entry = episodes[i + 1] if i + 1 < len(episodes) else None
        if next_entry:
            next_episode = next_entry.get('episode')
            next_label = ADDON.getLocalizedString(30315) % next_episode
            if next_entry.get('name'):
                next_label += ' - {0}'.format(next_entry['name'])
            url_params.update(
                next_season=season_raw, next_episode=next_episode,
                next_title=next_label, next_thumb=next_entry.get('poster_url') or '',
            )
        url = navigation.build_watch_action_url(base_url, 'play_pastebin_episode', **url_params)
        items.append((url, li, False))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(items), cacheToDisc=False)


def _add_remove_context_item(list_item, base_url, entry, watch_progress_info):
    # Titre transmis en parametre d'URL (pas relu depuis le serveur au
    # moment du clic) : sert uniquement a personnaliser la notification de
    # succes dans _action_clear() - un widget d'accueil (Arctic Horizon 2,
    # voir sa discussion) ne se rafraichit pas forcement tout de suite,
    # cette notification reste alors la seule confirmation visible que le
    # retrait a bien fonctionne cote serveur.
    poster = entry.get('poster') or {}
    title = poster.get('title') or entry.get('name') or ''
    if watch_progress_info.get('source') == 'vstream':
        tmdb_id = poster.get('tmdb_id')
        season, episode = poster.get('season'), poster.get('episode')
        if season is not None and episode is not None:
            url = navigation.build_watch_action_url(
                base_url, 'watch_clear', source='vstream', tmdb_id=tmdb_id,
                season=season, episode=episode, title=title,
            )
        else:
            url = navigation.build_watch_action_url(
                base_url, 'watch_clear', source='vstream', tmdb_id=tmdb_id, title=title,
            )
    else:
        url = navigation.build_watch_action_url(base_url, 'watch_clear', path=entry.get('path'), title=title)
    list_item.addContextMenuItems([
        (ADDON.getLocalizedString(30256), 'RunPlugin({0})'.format(url)),
        navigation.build_refresh_context_item(base_url),
    ])
