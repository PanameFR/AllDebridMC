# -*- coding: utf-8 -*-
"""Routage plugin:// et construction des listes Kodi.

Toutes les métadonnées (jaquettes, saisons, épisodes) viennent déjà
enrichies par le serveur (api_client.browse) — ce module ne fait
qu'afficher ce qu'on lui donne, jamais de logique de correspondance TMDB
ici (elle vit uniquement côté outil, pour rester fusionnel avec lui).
"""
import urllib.parse
from datetime import datetime

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from resources.lib import api_client, kodi_backup, lists_dialogs, next_up, playback, upnext

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')


def route(base_url, handle, params):
    action = params.get('action', 'root')

    if action.startswith('lists_'):
        # Fonctionnalite Listes (integree depuis plugin.video.vstreamlists) :
        # entierement geree dans son propre module, navigation.py ne fait
        # que lui deleguer - voir lists_routes.py.
        from resources.lib import lists_routes
        lists_routes.dispatch(base_url, handle, params)
        return

    if action == 'watch_home':
        # Simple menu de navigation (En cours/Historique) - pas de donnees
        # a aller chercher, reste ici plutot que dans watch_progress.py.
        _list_watch_menu(base_url, handle)
        return

    if action in _WATCH_CATEGORY_MENUS:
        # "En cours"/"Historique" scindes par categorie Pastebin (demande
        # explicitement : un ecran par categorie plutot qu'un seul
        # fourre-tout, pour les deux) - simple menu de navigation, comme
        # watch_home ci-dessus.
        _list_watch_categories_menu(base_url, handle, action)
        return

    if action.startswith('watch_'):
        # Reprise de lecture synchronisee : ecrans "En cours"/"Historique",
        # geres dans leur propre module - meme raison que l'import differe
        # ci-dessus (watch_progress importe navigation en tete, un import
        # en tete ici creerait un import circulaire).
        from resources.lib import watch_progress
        watch_progress.dispatch(base_url, handle, params)
        return

    if action == 'root':
        _list_root_menu(base_url, handle)
    elif action == 'browse':
        list_directory(base_url, handle, params.get('path', ''))
    elif action == 'local_search_prompt':
        _run_local_search_prompt(base_url, handle)
    elif action == 'local_search':
        _render_local_search(base_url, handle, params.get('query', ''))
    elif action == 'play':
        play_item(base_url, handle, params)
    elif action == 'movie_info':
        show_movie_info(handle, params)
    elif action == 'test_connection':
        test_connection(handle)
    elif action == 'refresh_all':
        run_refresh_action(handle)
    elif action == 'open_settings':
        run_open_settings(handle)
    elif action == 'backup_home':
        _list_backup_menu(base_url, handle)
    elif action == 'backup_run':
        _run_backup_action(handle)
    elif action == 'backup_restore':
        _run_restore_action(handle, params.get('name', ''))
    else:
        xbmcplugin.endOfDirectory(handle, succeeded=False)


def _build_url(base_url, **kwargs):
    return base_url + '?' + urllib.parse.urlencode(kwargs)


def _notify(message, error=False):
    icon = xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO
    xbmcgui.Dialog().notification(ADDON_NAME, message, icon, 5000)


def handle_api_error(exc):
    """Notification unique pour toute erreur d'appel serveur - publique et
    partagee : lists_routes.py en avait sa propre copie, avec des messages
    francais codes en dur (donc non traduisibles) et une icone/duree
    differentes pour la meme situation. Une seule implementation ici, sur
    les chaines localisees.

    ValidationError porte un message deja lisible construit par le serveur
    (ex : element absent de la source Pastebin) - on l'affiche tel quel,
    c'est plus precis que n'importe quel texte generique."""
    if isinstance(exc, api_client.AuthError):
        _notify(ADDON.getLocalizedString(30013), error=True)
    elif isinstance(exc, api_client.ValidationError):
        _notify(str(exc), error=True)
    else:
        _notify(ADDON.getLocalizedString(30012), error=True)


def device_identity():
    """Nom configure de cet appareil + versions, tels qu'annonces au
    serveur (voir api_client.ping) pour sa page Reglages. Le nom vient du
    meme reglage device_name qui etiquette deja les reprises de lecture -
    jamais un nom invente ici. Ne leve jamais : une identite incomplete
    vaut mieux qu'un ping qui echoue."""
    try:
        device = (ADDON.getSettingString('device_name') or '').strip()
    except (AttributeError, TypeError):
        device = ''
    try:
        kodi_version = xbmc.getInfoLabel('System.BuildVersion').split(' ')[0]
    except Exception:
        kodi_version = ''
    return {
        'device': device,
        'addon_version': ADDON.getAddonInfo('version'),
        'kodi_version': kodi_version,
    }


def _watch_progress_enabled():
    # Meme garde defensive que _show_count() dans lists_routes.py : un
    # reglage tout juste ajoute par une mise a jour peut ne pas encore
    # exister pour une install existante - ne jamais casser le menu
    # racine pour ca.
    try:
        return ADDON.getSettingBool('watch_progress_enabled')
    except (AttributeError, TypeError):
        return True


# ---- menu racine ------------------------------------------------------

def _list_root_menu(base_url, handle):
    """Racine de l'addon : uniquement des dossiers synthetiques (jamais
    d'appel serveur ici) - Medias (la vraie arborescence du serveur,
    anciennement affichee directement a la racine), Mes Listes, et
    Visionnage (En cours/Historique) si active."""
    xbmcplugin.setPluginCategory(handle, ADDON_NAME)
    xbmcplugin.setContent(handle, 'files')

    items = [_build_media_menu_item(base_url), _build_lists_menu_item(base_url)]
    if _watch_progress_enabled():
        items.append(_build_watch_home_menu_item(base_url))
    items.append(_build_backup_menu_item(base_url))
    items.append(_build_refresh_menu_item(base_url))
    items.append(_build_settings_menu_item(base_url))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def _list_watch_menu(base_url, handle):
    """Sous-menu Visionnage : En cours / Historique - simple aiguillage,
    aucune donnee a aller chercher ici (voir watch_progress.dispatch).
    Les deux menent desormais au meme menu de categories Pastebin
    ci-dessous (En cours ET Historique scindes de la meme facon)."""
    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(30260))
    xbmcplugin.setContent(handle, 'files')

    items = [
        _build_watch_menu_item(base_url, 'watch_in_progress_categories', 30250, 'DefaultInProgressShows.png'),
        _build_watch_menu_item(base_url, 'watch_history_categories', 30251, 'DefaultRecentlyAddedEpisodes.png'),
    ]
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


# Cle interne (voir pastebin_catalog.CATEGORY_CODES cote serveur, memes
# noms) -> id de chaine localisee pour le libelle du menu. Ordre = ordre
# d'affichage, reprend celui donne par l'utilisateur.
#
# La derniere entree, "_unclassified" (voir UNCLASSIFIED_CATEGORY cote
# serveur), n'est pas une categorie Pastebin : elle rassemble ce qui
# n'appartient a aucune des 7 autres - typiquement un contenu retire du
# catalogue depuis qu'il a ete regarde. Sans elle, ces entrees seraient
# inatteignables depuis l'interface (il n'existe plus d'ecran "tout"
# depuis la scission par categorie).
_WATCH_CATEGORIES = (
    ('films', 30330),
    ('series', 30331),
    ('docus', 30332),
    ('replay', 30333),
    ('spectacles', 30334),
    ('dessins_animes', 30335),
    ('animes_japonais', 30336),
    ('_unclassified', 30337),
)

# action=... (categories) -> (action=... cible reelle, id de chaine du
# titre affiche, icone). Meme menu de categories pour En cours ET
# Historique, seule la cible/le titre changent.
_WATCH_CATEGORY_MENUS = {
    'watch_in_progress_categories': ('watch_in_progress', 30250, 'DefaultInProgressShows.png'),
    'watch_history_categories': ('watch_history', 30251, 'DefaultRecentlyAddedEpisodes.png'),
}


def watch_category_label(category):
    """Libelle localise d'une categorie "En cours"/"Historique", ou None si
    la cle est inconnue. Accesseur public : watch_progress.py en a besoin
    pour titrer son ecran, et lisait auparavant _WATCH_CATEGORIES
    directement - une constante privee d'un autre module, alors que les
    deux sont deja lies par un cycle d'imports gere a la main (navigation
    importe watch_progress en differe, jamais l'inverse)."""
    for key, label_id in _WATCH_CATEGORIES:
        if key == category:
            return ADDON.getLocalizedString(label_id)
    return None


def _list_watch_categories_menu(base_url, handle, menu_action):
    """Menu "En cours"/"Historique" scinde par categorie Pastebin - chaque
    entree mene au meme ecran qu'avant (watch_in_progress ou
    watch_history), filtre cote serveur (voir api_client.list_watch_progress)
    par la categorie choisie."""
    target_action, title_label_id, icon = _WATCH_CATEGORY_MENUS[menu_action]
    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(title_label_id))
    xbmcplugin.setContent(handle, 'files')

    items = []
    for category_key, label_id in _WATCH_CATEGORIES:
        list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(label_id), offscreen=True)
        list_item.setArt({'icon': icon})
        url = _build_url(base_url, action=target_action, category=category_key)
        items.append((url, list_item, True))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def _build_media_menu_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30259), offscreen=True)
    list_item.setArt({'icon': 'DefaultHardDisk.png'})
    url = _build_url(base_url, action='browse', path='')
    return url, list_item, True


def _build_lists_menu_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30150), offscreen=True)
    list_item.setArt({'icon': 'DefaultVideoPlaylists.png'})
    url = _build_url(base_url, action='lists_home')
    return url, list_item, True


def _build_watch_home_menu_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30260), offscreen=True)
    # Icone differente de son propre enfant "En cours" (DefaultInProgressShows.png)
    # pour eviter d'avoir deux fois la meme icone a un niveau d'ecart.
    list_item.setArt({'icon': 'DefaultFavourites.png'})
    url = _build_url(base_url, action='watch_home')
    return url, list_item, True


def _build_watch_menu_item(base_url, action, label_id, icon):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(label_id), offscreen=True)
    list_item.setArt({'icon': icon})
    return _build_url(base_url, action=action), list_item, True


def build_watch_action_url(base_url, action, **params):
    return _build_url(base_url, action=action, **params)


def _build_backup_menu_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30300), offscreen=True)
    # Icone differente des 3 autres items racine (HardDisk/VideoPlaylists/
    # Favourites) - meme logique que pour Visionnage/En cours plus haut.
    list_item.setArt({'icon': 'DefaultNetwork.png'})
    url = _build_url(base_url, action='backup_home')
    return url, list_item, True


def _build_refresh_menu_item(base_url):
    """Action directe (RunPlugin, jamais une vraie navigation - meme
    convention que test_connection), pas un sous-dossier : Container.Refresh
    rafraichit le conteneur ACTIF au moment du clic. Depuis ce menu racine,
    ca ne rafraichit que lui-meme (peu utile) - le vrai interet est de
    pouvoir pointer un raccourci de skin directement sur cette action (ou
    de l'utiliser via son item de menu contextuel, voir lists_gui.py/
    watch_progress.py) pendant qu'on est deja sur l'ecran a rafraichir."""
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30316), offscreen=True)
    list_item.setArt({'icon': 'DefaultAddonsUpdates.png'})
    url = _build_url(base_url, action='refresh_all')
    return url, list_item, False


def _build_settings_menu_item(base_url):
    """Action directe (RunPlugin), ouvre les reglages de CET addon
    (Addon.OpenSettings, jamais un sous-dossier) - pour ne pas dependre de
    l'ecran "Gerer les extensions" de Kodi pour y acceder."""
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30320), offscreen=True)
    list_item.setArt({'icon': 'DefaultAddonProgram.png'})
    url = _build_url(base_url, action='open_settings')
    return url, list_item, False


# ---- sauvegarde/restauration Kodi --------------------------------------

def _list_backup_menu(base_url, handle):
    """Dossier Sauvegarde : en premier une action "Sauvegarder maintenant",
    puis une entree par sauvegarde deja presente sur le serveur (voir
    kodi_backup.list_backups) - cliquer une entree lance sa restauration.
    Jamais de sous-dossier ici, tout est action directe (comme
    test_connection), pas une vraie navigation."""
    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(30300))
    xbmcplugin.setContent(handle, 'files')

    items = [_build_backup_run_item(base_url)]

    try:
        backups = kodi_backup.list_backups()
    except api_client.ApiError as exc:
        handle_api_error(exc)
        backups = []

    for backup in backups:
        items.append(_build_backup_restore_item(base_url, backup))

    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def _build_backup_run_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30308), offscreen=True)
    list_item.setArt({'icon': 'DefaultAddSource.png'})
    url = _build_url(base_url, action='backup_run')
    return url, list_item, False


def _build_backup_restore_item(base_url, backup):
    label = '{0} — {1} — {2}'.format(
        backup.get('device') or '?',
        _format_backup_date(backup.get('created_at')),
        backup.get('size_human') or '',
    )
    list_item = xbmcgui.ListItem(label=label, offscreen=True)
    list_item.setArt({'icon': 'DefaultAddonsUpdates.png'})
    url = _build_url(base_url, action='backup_restore', name=backup.get('name', ''))
    return url, list_item, False


def _format_backup_date(iso_string):
    if not iso_string:
        return '?'
    try:
        parsed = datetime.fromisoformat(iso_string)
    except ValueError:
        return iso_string
    return parsed.strftime('%d/%m/%Y %H:%M')


def _run_backup_action(handle):
    confirmed = xbmcgui.Dialog().yesno(
        ADDON.getLocalizedString(30300), ADDON.getLocalizedString(30309),
    )
    if confirmed:
        progress = xbmcgui.DialogProgress()
        success, error = kodi_backup.run_backup(progress)
        if success:
            _notify(ADDON.getLocalizedString(30310), error=False)
        elif error:
            # Dialog().ok (modale, texte complet) plutot qu'une notification
            # toast (tronquee a quelques mots) : une erreur de sauvegarde
            # est rare et doit rester lisible en entier - notamment le
            # chemin de fichier complet d'une PermissionError, indispensable
            # pour diagnostiquer sans acces aux logs de l'appareil.
            xbmcgui.Dialog().ok(ADDON.getLocalizedString(30300), error)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


def _run_restore_action(handle, backup_name):
    if backup_name:
        confirmed = xbmcgui.Dialog().yesno(
            ADDON.getLocalizedString(30300), ADDON.getLocalizedString(30311),
        )
        if confirmed:
            progress = xbmcgui.DialogProgress()
            success, error = kodi_backup.run_restore(progress, backup_name)
            if success:
                if xbmcgui.Dialog().yesno(
                    ADDON.getLocalizedString(30312), ADDON.getLocalizedString(30313)
                ):
                    xbmc.executebuiltin('Quit')
            elif error:
                xbmcgui.Dialog().ok(ADDON.getLocalizedString(30300), error)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


# ---- browse (Medias) ----------------------------------------------------

def list_directory(base_url, handle, path):
    try:
        data = api_client.browse(path)
    except api_client.ApiError as exc:
        handle_api_error(exc)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    entries = [e for e in data.get('entries', []) if e.get('is_dir') or e.get('is_video')]

    xbmcplugin.setPluginCategory(handle, _category_label(data, path))
    xbmcplugin.setContent(handle, _guess_content(entries))

    items = [
        build_list_item(base_url, entry, entries[i + 1] if i + 1 < len(entries) else None)
        for i, entry in enumerate(entries)
    ]
    if not path:
        # Uniquement a la racine de "Medias" (a cote d'Animations/Films/
        # Series) - une recherche n'a de sens que sur toute la
        # bibliotheque, jamais limitee a un sous-dossier deja filtre.
        items.append(_build_local_search_menu_item(base_url))
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    # Le serveur trie déjà correctement (SxxExx, alphabétique) : on garde
    # cet ordre plutôt que de proposer le tri natif de Kodi.
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, updateListing=False, cacheToDisc=False)


def _category_label(data, path):
    if not path:
        # Racine du vrai serveur (ecran "Medias") - le fil d'Ariane du
        # serveur est vide a ce niveau, jamais tres parlant comme categorie.
        return ADDON.getLocalizedString(30259)
    breadcrumb = data.get('breadcrumb') or []
    return breadcrumb[-1]['name'] if breadcrumb else ADDON_NAME


def _guess_content(entries):
    if any(e.get('episode_info') for e in entries):
        return 'episodes'
    if any(e.get('season_info') for e in entries):
        # 'seasons' est le type de contenu que vStream utilise reellement
        # pour ce meme ecran (verifie contre son code source reel,
        # resources/lib/gui/gui.py::addSeason -> setContent(handle,
        # 'seasons') - jamais devine). Un essai passe sur Estuary (skin par
        # defaut de Kodi) avait montre que ce type n'y affichait pas le
        # resume de saison dans le panneau d'info, d'ou un repli vers
        # 'tvshows' - mais ce test visait Estuary, pas Arctic Horizon 2 (le
        # skin reellement utilise), qui traite 'seasons' specialement (le
        # double panneau saisons/apercu-episodes vu sur vStream vient de la
        # meme prise en charge cote skin, jamais du code de vStream
        # lui-meme). A revenir a 'tvshows' si ce constat ne se confirme pas
        # ici non plus.
        return 'seasons'
    if any((e.get('poster') or {}).get('media_type') == 'tv' for e in entries):
        return 'tvshows'
    if any((e.get('poster') or {}).get('media_type') == 'movie' for e in entries):
        return 'movies'
    return 'files'


def _guess_search_content(results):
    """Meme intention que _guess_content ci-dessus, mais pour les resultats
    de recherche locale (forme differente : media_type au premier niveau,
    jamais season_info/episode_info). Necessaire pour la meme raison :
    sans un vrai type 'movies'/'tvshows', le skin affiche une simple liste/
    vignette generique au lieu du mur d'affiches (format vStream) - constate
    directement (setContent('videos') rendait des tuiles plates avec juste
    une barre de titre, pas des affiches hautes)."""
    if any(r.get('media_type') == 'movie' for r in results):
        return 'movies'
    if any(r.get('media_type') == 'tv' for r in results):
        return 'tvshows'
    return 'files'


def _entry_title(entry):
    ep = entry.get('episode_info')
    if ep and ep.get('name'):
        se, epn = ep.get('season_number'), ep.get('episode_number')
        prefix = 'S{0:02d}E{1:02d} - '.format(se, epn) if se is not None and epn is not None else ''
        return prefix + ep['name']

    season = entry.get('season_info')
    if season and season.get('name'):
        return season['name']

    poster = entry.get('poster')
    if poster and poster.get('title'):
        year = poster.get('year')
        return '{0} ({1})'.format(poster['title'], year) if year else poster['title']

    return entry.get('name', '?')


def _entry_art(entry):
    ep = entry.get('episode_info')
    if ep and ep.get('still_url'):
        return {'thumb': ep['still_url'], 'icon': ep['still_url']}

    if entry.get('is_season_folder'):
        # Jamais d'affiche par saison (meme si le serveur en fournit une,
        # via season_info.poster_url ou poster.poster_url - identiques) :
        # verifie contre le code source reel de l'integration Pastebin/
        # vStream de reference (resources/sites/pastebin.py::addSeason,
        # sThumbnail toujours vide, icone generique "no-image.png") avant
        # d'ecrire ceci, jamais devine. Les affiches de saison TMDB varient
        # trop d'un design/langue a l'autre pour la meme serie (constate
        # directement sur "Super Noel, la serie" : Saison 1 et 2 ont deux
        # visuels completement differents) - une tuile neutre uniforme
        # rend l'identite "meme serie, saison differente" plus claire
        # qu'une jaquette a chaque fois differente.
        return {}

    poster = entry.get('poster')
    if poster and poster.get('poster_url'):
        return {'thumb': poster['poster_url'], 'poster': poster['poster_url']}

    return {}


def _apply_metadata(info, entry):
    poster = entry.get('poster')
    season = entry.get('season_info')
    ep = entry.get('episode_info')

    if ep:
        info.setMediaType('episode')
        if poster and poster.get('title'):
            info.setTvShowTitle(poster['title'])
        if ep.get('season_number') is not None:
            info.setSeason(ep['season_number'])
        if ep.get('episode_number') is not None:
            info.setEpisode(ep['episode_number'])
        if ep.get('overview'):
            info.setPlot(ep['overview'])
        if ep.get('air_date'):
            info.setFirstAired(ep['air_date'])
            info.setPremiered(ep['air_date'])
        if ep.get('runtime'):
            info.setDuration(int(ep['runtime']) * 60)  # TMDB : minutes -> Kodi attend des secondes
        if ep.get('vote_average'):
            info.setRating(float(ep['vote_average']))
    elif season:
        info.setMediaType('season')
        if season.get('season_number') is not None:
            info.setSeason(season['season_number'])
        if season.get('air_date'):
            info.setPremiered(season['air_date'])
        if season.get('overview'):
            info.setPlot(season['overview'])
    elif poster:
        info.setMediaType('movie' if poster.get('media_type') == 'movie' else 'tvshow')
        if poster.get('year'):
            info.setYear(int(poster['year']))
        if poster.get('overview'):
            info.setPlot(poster['overview'])


def build_list_item(base_url, entry, next_entry=None):
    title = _entry_title(entry)
    list_item = xbmcgui.ListItem(label=title, offscreen=True)

    art = _entry_art(entry)
    if art:
        list_item.setArt(art)

    info = list_item.getVideoInfoTag()
    info.setTitle(title)
    _apply_metadata(info, entry)

    poster = entry.get('poster') or {}
    context_items = []
    if poster.get('media_type') == 'movie' and poster.get('tmdb_id'):
        info_url = _build_url(
            base_url, action='movie_info', tmdb_id=poster['tmdb_id'],
            title=title, thumb=art.get('thumb', ''),
        )
        context_items.append(
            (ADDON.getLocalizedString(30014), 'RunPlugin({0})'.format(info_url))
        )
    if poster.get('tmdb_id'):
        # Deja associe a une fiche TMDB (film - fichier ou dossier selon
        # l'organisation de la bibliotheque - ou racine de serie) : peut
        # etre relie a une liste. is_dir est transmis (pas utilise comme
        # condition : un film est parfois un fichier direct, parfois un
        # dossier) pour que la redirection sache plus tard si elle doit
        # ouvrir un dossier ou lancer la lecture directement (voir
        # lists_routes.action_add_local / lists_gui.render_list).
        add_to_list_url = _build_url(
            base_url, action='lists_add_local', path=entry['path'],
            tmdb_id=poster['tmdb_id'], media_type=poster.get('media_type'), title=title,
            is_dir='1' if entry.get('is_dir') else '0',
        )
        context_items.append(
            (ADDON.getLocalizedString(30151), 'RunPlugin({0})'.format(add_to_list_url))
        )
    if context_items:
        list_item.addContextMenuItems(context_items)

    if entry.get('is_dir'):
        url = _build_url(base_url, action='browse', path=entry['path'])
        return url, list_item, True

    list_item.setProperty('IsPlayable', 'true')
    play_params = {
        'action': 'play', 'path': entry['path'], 'title': title,
        'thumb': art.get('thumb', ''),
    }
    ep = entry.get('episode_info')
    if ep:
        if poster.get('title'):
            play_params['showtitle'] = poster['title']
        if ep.get('overview'):
            play_params['plot'] = ep['overview']
        if ep.get('season_number') is not None:
            play_params['season'] = ep['season_number']
        if ep.get('episode_number') is not None:
            play_params['episode'] = ep['episode_number']
        if ep.get('air_date'):
            play_params['aired'] = ep['air_date']
        if ep.get('runtime'):
            play_params['duration'] = ep['runtime']
        if ep.get('vote_average'):
            play_params['rating'] = ep['vote_average']
        # UpNext (service.upnext) : episode suivant deja connu ici (meme
        # dossier de saison, deja trie SxxExx par le serveur) - transmis a
        # travers l'URL de lecture plutot que recalcule au moment de jouer,
        # pour eviter un aller-retour serveur supplementaire depuis
        # play_item(). Jamais envoye si l'entree suivante n'est pas un
        # episode (fin de saison).
        next_ep = (next_entry or {}).get('episode_info')
        if next_ep:
            play_params['next_path'] = next_entry['path']
            play_params['next_title'] = next_ep.get('name') or ''
            play_params['next_plot'] = next_ep.get('overview') or ''
            if next_ep.get('season_number') is not None:
                play_params['next_season'] = next_ep['season_number']
            if next_ep.get('episode_number') is not None:
                play_params['next_episode'] = next_ep['episode_number']
            next_thumb = (next_ep.get('still_url') or poster.get('poster_url') or '')
            if next_thumb:
                play_params['next_thumb'] = next_thumb
    url = _build_url(base_url, **play_params)
    return url, list_item, False


def _build_local_search_menu_item(base_url):
    list_item = xbmcgui.ListItem(label=ADDON.getLocalizedString(30338), offscreen=True)
    list_item.setArt({'icon': 'DefaultAddonsSearch.png'})
    url = _build_url(base_url, action='local_search_prompt')
    return url, list_item, False


def _run_local_search_prompt(base_url, handle):
    query = lists_dialogs.ask_text(ADDON.getLocalizedString(30339))
    if query:
        url = _build_url(base_url, action='local_search', query=query)
        xbmc.executebuiltin('Container.Update({0})'.format(url))
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


def _render_local_search(base_url, handle, query):
    """Resultats de recherche dans la bibliotheque locale, par titre TMDB
    deja resolu cote serveur (voir lists_store.search_local /
    tmdb_poster_cache.json) - jamais par nom de fichier brut. Chaque
    resultat pointe directement vers action=browse (dossier - typiquement
    la racine d'une serie) ou action=play (fichier), exactement comme un
    item de navigation normale (voir build_list_item) : aucune logique de
    lecture separee, la suite (reprise, enchainement UpNext...) se
    comporte alors normalement des qu'on rebrowse/joue depuis la, comme
    n'importe quel autre chemin d'acces a ce meme contenu."""
    if not query:
        # Filet de securite (URL malformee/directe) : le prompt normal
        # (_run_local_search_prompt) ne navigue jamais ici sans texte saisi.
        xbmcplugin.setContent(handle, 'files')
        xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(30338))
        _notify(ADDON.getLocalizedString(30340))
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        return

    xbmcplugin.setPluginCategory(handle, ADDON.getLocalizedString(30341).format(query))

    try:
        results = api_client.search_local_catalog(query)
    except api_client.ApiError as exc:
        handle_api_error(exc)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    # Determine apres coup (comme _guess_content pour la navigation normale) :
    # un vrai type 'movies'/'tvshows' (jamais 'videos', trop generique) est
    # ce qui declenche le mur d'affiches hautes du skin plutot qu'une simple
    # liste/vignette avec barre de titre.
    xbmcplugin.setContent(handle, _guess_search_content(results))

    items = [_build_search_list_item(base_url, entry) for entry in results]
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=bool(results), cacheToDisc=False)


def _build_search_list_item(base_url, entry):
    title = entry.get('title') or '?'
    if entry.get('year'):
        title = '{0} ({1})'.format(title, entry['year'])

    list_item = xbmcgui.ListItem(label=title, offscreen=True)
    poster_url = entry.get('poster_url')
    if poster_url:
        list_item.setArt({'thumb': poster_url, 'poster': poster_url})

    info = list_item.getVideoInfoTag()
    info.setTitle(title)
    info.setMediaType('movie' if entry.get('media_type') == 'movie' else 'tvshow')
    if entry.get('year'):
        try:
            info.setYear(int(entry['year']))
        except (TypeError, ValueError):
            pass
    if entry.get('overview'):
        info.setPlot(entry['overview'])
    if entry.get('rating'):
        info.setRating(float(entry['rating']))
    if entry.get('runtime'):
        info.setDuration(int(entry['runtime']) * 60)  # TMDB : minutes -> Kodi attend des secondes

    path = entry.get('local_path') or ''
    if entry.get('local_is_dir'):
        url = _build_url(base_url, action='browse', path=path)
        return url, list_item, True

    list_item.setProperty('IsPlayable', 'true')
    url = _build_url(base_url, action='play', path=path, title=title, thumb=poster_url or '')
    return url, list_item, False


# ---- play -------------------------------------------------------------

def play_item(base_url, handle, params):
    title = params.get('title', '')
    relative_path = params.get('path', '')
    list_item = xbmcgui.ListItem(label=title, offscreen=True)

    thumb = params.get('thumb')
    if thumb:
        list_item.setArt({'thumb': thumb, 'icon': thumb})

    info = list_item.getVideoInfoTag()
    if title:
        info.setTitle(title)
    if params.get('showtitle'):
        info.setTvShowTitle(params['showtitle'])
    if params.get('plot'):
        info.setPlot(params['plot'])
    if params.get('season'):
        info.setSeason(int(params['season']))
    if params.get('episode'):
        info.setEpisode(int(params['episode']))
    if params.get('aired'):
        info.setFirstAired(params['aired'])
    if params.get('duration'):
        info.setDuration(int(float(params['duration'])) * 60)  # minutes -> secondes
    if params.get('rating'):
        info.setRating(float(params['rating']))

    # Reprise de lecture synchronisee : import differe (meme raison que
    # pour lists_routes/watch_progress dans route() - le module importe
    # navigation en tete, un import en tete ici créerait un cycle).
    from resources.lib import watch_progress
    watch_progress.maybe_apply_resume(info, relative_path, title)

    list_item.setPath(playback.build_smb_url(relative_path))
    xbmcplugin.setResolvedUrl(handle, True, list_item)

    # Enchainement fiable (notre propre popup, voir next_up.py) si active
    # et qu'un episode suivant est connu - sinon (dernier episode d'une
    # saison, film, ou fonctionnalite desactivee dans les reglages) filet
    # de secours vers service.upnext comme avant. Jamais les deux a la
    # fois (double popup).
    if params.get('next_path') and next_up.enabled():
        next_up.start_chaining_monitor(_build_next_episode_info(base_url, params))
    else:
        _notify_upnext(base_url, params)

    # Bloque jusqu'a la fin de la lecture pour suivre la progression - le
    # script du plugin n'est pas oblige de revenir vite apres
    # setResolvedUrl (voir le commentaire en tete de watch_progress.py).
    watch_progress.track_playback(relative_path)


def _build_next_episode_info(base_url, params):
    """Meme construction que next_play_params dans _notify_upnext (juste
    en dessous) - dupliquee volontairement plutot que partagee, les deux
    consommateurs (service.upnext vs next_up.py) ont des besoins et des
    formats de donnees differents (dict current+next vs un seul dict)."""
    next_play_params = {
        'action': 'play', 'path': params['next_path'],
        'title': params.get('next_title', ''), 'thumb': params.get('next_thumb', ''),
        'plot': params.get('next_plot', ''), 'showtitle': params.get('showtitle', ''),
    }
    if params.get('next_season'):
        next_play_params['season'] = params['next_season']
    if params.get('next_episode'):
        next_play_params['episode'] = params['next_episode']

    return {
        'showtitle': params.get('showtitle', ''),
        'season': params.get('next_season', ''),
        'episode': params.get('next_episode', ''),
        'title': params.get('next_title', ''),
        'thumb': params.get('next_thumb', ''),
        'play_url': _build_url(base_url, **next_play_params),
    }


def _notify_upnext(base_url, params):
    """Signale l'episode suivant a service.upnext (voir upnext.py) - rien
    n'est envoye si next_path est absent (fin de saison, ou entree
    suivante qui n'est pas un episode - voir build_list_item)."""
    if not params.get('next_path'):
        return

    next_play_params = {
        'action': 'play', 'path': params['next_path'],
        'title': params.get('next_title', ''), 'thumb': params.get('next_thumb', ''),
        'plot': params.get('next_plot', ''), 'showtitle': params.get('showtitle', ''),
    }
    if params.get('next_season'):
        next_play_params['season'] = params['next_season']
    if params.get('next_episode'):
        next_play_params['episode'] = params['next_episode']

    upnext.notify(
        current={
            'showtitle': params.get('showtitle', ''), 'season': params.get('season', ''),
            'episode': params.get('episode', ''), 'title': params.get('title', ''),
            'plot': params.get('plot', ''), 'thumb': params.get('thumb', ''),
        },
        next_={
            'showtitle': params.get('showtitle', ''), 'season': params.get('next_season', ''),
            'episode': params.get('next_episode', ''), 'title': params.get('next_title', ''),
            'plot': params.get('next_plot', ''), 'thumb': params.get('next_thumb', ''),
            'play_url': _build_url(base_url, **next_play_params),
        },
    )


# ---- infos film à la demande -------------------------------------------

def show_movie_info(handle, params):
    tmdb_id = params.get('tmdb_id')

    try:
        data = api_client.movie_info(tmdb_id)
    except api_client.ApiError as exc:
        handle_api_error(exc)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    list_item = xbmcgui.ListItem(label=params.get('title', ''), offscreen=True)
    thumb = params.get('thumb')
    if thumb:
        list_item.setArt({'thumb': thumb, 'poster': thumb})

    info = list_item.getVideoInfoTag()
    info.setMediaType('movie')
    if params.get('title'):
        info.setTitle(params['title'])
    if data.get('overview'):
        info.setPlot(data['overview'])
    if data.get('genres'):
        info.setGenres(data['genres'])
    if data.get('vote_average'):
        info.setRating(float(data['vote_average']))
    if data.get('runtime'):
        info.setDuration(int(data['runtime']) * 60)  # minutes -> secondes
    if data.get('release_date'):
        info.setPremiered(data['release_date'])

    xbmcgui.Dialog().info(list_item)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


# ---- bouton "Tester la connexion" des réglages -------------------------

def test_connection(handle):
    try:
        # En profite pour annoncer l'appareil au serveur (nom + versions),
        # qui les affiche sur sa page Reglages - voir api_client.ping.
        api_client.ping(**device_identity())
    except api_client.AuthError:
        _notify(ADDON.getLocalizedString(30013), error=True)
    except api_client.ApiError:
        _notify(ADDON.getLocalizedString(30012), error=True)
    else:
        _notify(ADDON.getLocalizedString(30011), error=False)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


# ---- action "Rafraichir" (menu racine + menu contextuel Mes Listes/En cours) --

def run_refresh_action(handle):
    """Container.Refresh ne rafraichit que le conteneur ACTIF au moment de
    l'appel - insuffisant sur l'ecran d'accueil, ou les widgets ne sont pas
    forcement le conteneur qui a le focus (meme probleme, et meme solution,
    que _maybe_auto_refresh dans service.py : ReloadSkin() y recharge tout,
    widgets compris, de facon fiable quel que soit le skin). Meme detection
    ici, pour qu'un declenchement MANUEL (raccourci de skin, menu racine,
    menu contextuel Mes Listes/En cours) soit fiable partout, y compris
    depuis l'accueil - pas seulement le declenchement automatique.

    Notre contenu n'est deja jamais mis en cache (cacheToDisc=False
    partout) - le seul interet ici est de forcer Kodi a re-executer la
    requete tout de suite, sans attendre un eventuel rafraichissement
    automatique de widget de skin.
    """
    if xbmc.getCondVisibility('Window.IsActive(home)'):
        xbmc.executebuiltin('ReloadSkin()')
    else:
        xbmc.executebuiltin('Container.Refresh')
    _notify(ADDON.getLocalizedString(30317), error=False)
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


def run_open_settings(handle):
    ADDON.openSettings()
    xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


def build_refresh_context_item(base_url):
    """A ajouter dans addContextMenuItems() d'un ecran qu'on veut pouvoir
    rafraichir depuis lui-meme (voir lists_gui.py/watch_progress.py)."""
    url = _build_url(base_url, action='refresh_all')
    return (ADDON.getLocalizedString(30316), 'RunPlugin({0})'.format(url))
