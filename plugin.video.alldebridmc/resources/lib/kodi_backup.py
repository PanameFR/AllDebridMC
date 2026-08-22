# -*- coding: utf-8 -*-
"""Sauvegarde/restauration complète de Kodi, intégrée à AllDebridMC plutôt
qu'un addon séparé (inspiré de l'addon officiel robweber/xbmcbackup, mais
simplifié : un seul mode "tout", une seule cible (notre serveur Pi),
toujours compressé). Catégories et chemins vérifiés directement contre
resources/data/default_files.json du projet de référence - jamais deviné.

"Le cache" = special://home/userdata/Thumbnails/ (l'artwork, coûteux à
régénérer) - special://temp/ (régénérable, jamais utile à restaurer) n'est
volontairement pas inclus, même choix que la référence.

Limite connue et assumée (documentée, pas filtrée activement) : un addon
avec des composants binaires compilés (ex. inputstream.adaptive) est
compilé PAR PLATEFORME - copier son dossier special://home/addons/<id>/
d'un Android vers un Windows ne rendra pas forcément cet addon fonctionnel
sur la nouvelle plateforme, même si Kodi résout bien special://home/
correctement de son côté sur chaque plateforme.
"""
import json
import os
import shutil
import uuid
import zipfile

import xbmc
import xbmcaddon
import xbmcvfs

from resources.lib import api_client

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')

CHUNK_SIZE = 4 * 1024 * 1024  # 4 Mo - compromis mémoire/nombre de requêtes

# nom de catégorie -> (special:// racine, récursif). Racines et portée
# vérifiées 1:1 contre default_files.json de robweber/xbmcbackup.
_CATEGORY_ROOTS = {
    'addons': ('special://home/addons/', True),
    'addon_data': ('special://home/userdata/addon_data/', True),
    'database': ('special://home/userdata/Database/', True),
    'game_saves': ('special://home/userdata/Savestates/', True),
    'playlists': ('special://home/userdata/playlists/', True),
    'profiles': ('special://home/userdata/profiles/', True),
    'thumbnails': ('special://home/userdata/Thumbnails/', True),
    'config': ('special://home/userdata/', False),
}
_CONFIG_EXTRA_DIRS = ['keymaps', 'peripheral_data', 'library']
# ADDON_ID (nous-memes) exclu : c'est CE code qui execute la sauvegarde/
# restauration, en tant que fichiers sous special://home/addons/<ADDON_ID>/ -
# l'ecraser pendant qu'il tourne est fragile (deja constate : Permission
# Denied sur un fichier verrouille par Windows au mauvais moment) et de
# toute facon inutile : pour restaurer une sauvegarde il faut deja avoir
# installe cet addon depuis le depot, jamais l'inverse.
_ADDONS_EXCLUDE = ['packages', 'temp', ADDON_ID]
_META_MEMBERS = ('kodi_settings.json', 'backup_meta.json')

_TEMP_DIR = 'special://temp/alldebridmc_backup/'

# Prefixes de reglages propres au MATERIEL de l'appareil (ecran, sortie
# audio) - jamais restaures depuis la sauvegarde d'un AUTRE appareil : deux
# Kodi n'ont jamais le meme ecran/la meme carte son, et appliquer les
# valeurs de la source casse l'affichage/le son sur l'appareil cible
# (constate reellement : resolution et plein ecran modifies par une
# restauration cross-device). L'appareil cible garde toujours SES PROPRES
# valeurs pour ces prefixes, quoi que contienne la sauvegarde.
_SETTINGS_EXCLUDE_PREFIXES = ('videoscreen.', 'audiooutput.')

# Nom du fichier marqueur (voir apply_pending_settings_restore plus bas).
_PENDING_SETTINGS_FILENAME = 'pending_settings_restore.json'


def _log(message):
    xbmc.log('[{0}] {1}'.format(ADDON_ID, message), level=xbmc.LOGINFO)


def _device_label():
    from resources.lib import watch_progress
    name = watch_progress.device_name()
    return name or xbmc.getInfoLabel('System.FriendlyName') or 'Kodi'


def _settings_snapshot():
    response = json.loads(xbmc.executeJSONRPC(
        '{"jsonrpc":"2.0","id":1,"method":"Settings.GetSettings","params":{"level":"expert"}}'
    ))
    return response.get('result', {}).get('settings', [])


def _restore_settings(settings):
    current_by_id = {
        s['id']: s['value'] for s in _settings_snapshot() if s.get('type') != 'action'
    }

    applied = 0
    skipped = 0
    for setting in settings:
        setting_id = setting.get('id') or ''
        if setting.get('type') == 'action' or setting_id not in current_by_id:
            continue
        if setting_id.startswith(_SETTINGS_EXCLUDE_PREFIXES):
            skipped += 1
            continue

        request = json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'Settings.SetSettingValue',
            'params': {'setting': setting_id, 'value': setting.get('value')},
        })
        xbmc.executeJSONRPC(request)
        applied += 1

    _log('Parametres Kodi restaures : {0} (ignores car specifiques a l\'appareil : {1})'.format(applied, skipped))


def _own_addon_data_dir():
    root = xbmcvfs.translatePath(_CATEGORY_ROOTS['addon_data'][0])
    return os.path.join(root, ADDON_ID)


def _pending_settings_path():
    return os.path.join(_own_addon_data_dir(), _PENDING_SETTINGS_FILENAME)


def apply_pending_settings_restore():
    """Appelee par service.py a CHAQUE demarrage de Kodi, avant toute
    autre chose. Si une restauration a laisse des parametres en attente
    (voir run_restore plus bas - jamais appliques tout de suite, justement
    pour eviter le probleme ci-dessous), les applique maintenant et
    supprime le marqueur. Ne fait rien sinon (l'immense majorite des
    demarrages). Retourne True si des parametres ont ete restaures,
    False sinon - pour que service.py sache s'il doit notifier.

    Pourquoi differe au redemarrage suivant plutot qu'applique tout de
    suite dans run_restore : au moment ou une restauration s'execute,
    Kodi tourne encore, avec en memoire le skin/les reglages d'AVANT -
    un appel JSON-RPC Settings.SetSettingValue immediat s'applique par-
    dessus cet etat encore vivant, et rien ne force Kodi a relire tout de
    suite les fichiers addon_data/addons fraichement extraits sur disque
    (constate reellement : le skin et ses reglages ne survivaient pas a
    une restauration, alors que les fichiers etaient bien la sur disque
    juste apres). En repartant a froid avant d'appliquer les parametres,
    Kodi a deja tout relu depuis le disque (skin, addons, leurs donnees)
    et les Settings.SetSettingValue s'appliquent sur une base saine."""
    path = _pending_settings_path()
    if not os.path.isfile(path):
        return False

    try:
        with open(path, 'r', encoding='utf-8') as fh:
            settings_payload = json.load(fh)
        _restore_settings(settings_payload)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return True


def _iter_files(root_special, recurse, exclude_top=None):
    """Renvoie (chemin_reel, chemin_relatif_a_la_racine) pour chaque fichier
    sous root_special. Non recursif = uniquement les fichiers directement
    dans le dossier (utilise pour 'config', dont la racine userdata/ elle-
    meme ne doit pas remonter tout le reste de userdata/). exclude_top =
    noms de sous-dossiers a exclure, seulement verifies au premier niveau
    (utilise pour addons/packages et addons/temp)."""
    root = xbmcvfs.translatePath(root_special)
    if not os.path.isdir(root):
        return

    if not recurse:
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if os.path.isfile(full):
                yield full, entry
        return

    for current_dir, dirs, files in os.walk(root):
        if current_dir == root and exclude_top:
            dirs[:] = [d for d in dirs if d not in exclude_top]
        for filename in sorted(files):
            full = os.path.join(current_dir, filename)
            yield full, os.path.relpath(full, root)


def _build_zip(progress):
    temp_dir = xbmcvfs.translatePath(_TEMP_DIR)
    shutil.rmtree(temp_dir, ignore_errors=True)
    os.makedirs(temp_dir, exist_ok=True)
    zip_path = os.path.join(temp_dir, 'backup.zip')

    category_names = list(_CATEGORY_ROOTS.keys())

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for index, name in enumerate(category_names):
            if progress.iscanceled():
                return None

            progress.update(
                int((index / len(category_names)) * 60),
                '{0}...'.format(ADDON.getLocalizedString(30301)),
            )

            root_special, recurse = _CATEGORY_ROOTS[name]

            if name == 'config':
                for full, rel in _iter_files(root_special, False):
                    zf.write(full, '/'.join(('config', rel)))
                for extra in _CONFIG_EXTRA_DIRS:
                    for full, rel in _iter_files(root_special + extra + '/', True):
                        zf.write(full, '/'.join(('config', extra, rel)))
                continue

            exclude_top = _ADDONS_EXCLUDE if name == 'addons' else None
            for full, rel in _iter_files(root_special, recurse, exclude_top):
                zf.write(full, '/'.join((name, rel)))

        zf.writestr('kodi_settings.json', json.dumps(_settings_snapshot(), ensure_ascii=False))
        zf.writestr('backup_meta.json', json.dumps({
            'kodi_version': xbmc.getInfoLabel('System.BuildVersion'),
            'addon_version': ADDON.getAddonInfo('version'),
            'device': _device_label(),
        }, ensure_ascii=False))

    return zip_path


def run_backup(progress):
    """Retourne (succes, message_erreur_ou_None)."""
    progress.create(ADDON.getLocalizedString(30300), ADDON.getLocalizedString(30301))
    temp_dir = xbmcvfs.translatePath(_TEMP_DIR)

    try:
        zip_path = _build_zip(progress)
        if zip_path is None:
            return False, ADDON.getLocalizedString(30302)

        total_size = os.path.getsize(zip_path) or 1
        session_id = uuid.uuid4().hex
        device = _device_label()

        sent = 0
        index = 0
        with open(zip_path, 'rb') as fh:
            while True:
                if progress.iscanceled():
                    return False, ADDON.getLocalizedString(30302)

                chunk = fh.read(CHUNK_SIZE)
                sent += len(chunk)
                is_last = sent >= total_size

                api_client.backup_upload_chunk(session_id, device, index, is_last, chunk)

                progress.update(
                    min(60 + int((sent / total_size) * 40), 99),
                    ADDON.getLocalizedString(30303),
                )

                index += 1
                if is_last:
                    break

        return True, None
    except api_client.ApiError as exc:
        return False, str(exc)
    except (OSError, zipfile.BadZipFile) as exc:
        return False, str(exc)
    finally:
        progress.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def list_backups():
    return api_client.backup_list()


def run_restore(progress, backup_name):
    """Retourne (succes, message_erreur_ou_None). Les parametres Kodi ne
    sont jamais appliques ici tout de suite (voir
    apply_pending_settings_restore ci-dessus pour le pourquoi) : ce qui se
    passe ici est extraction des fichiers + marqueur ecrit pour le
    prochain demarrage, jamais l'application des reglages elle-meme."""
    progress.create(ADDON.getLocalizedString(30300), ADDON.getLocalizedString(30304))
    temp_dir = xbmcvfs.translatePath(_TEMP_DIR)

    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)
        zip_path = os.path.join(temp_dir, 'restore.zip')

        # Le nom de CET appareil (reglage de notre propre addon) ne doit
        # jamais etre ecrase par celui de l'appareil source de la
        # sauvegarde, sous peine de melanger les appareils - capture avant
        # extraction (qui ecrase le settings.xml de notre propre addon
        # avec celui de la source), restaure juste apres.
        from resources.lib import watch_progress
        own_device_name = watch_progress.device_name()

        def on_download_progress(written, total):
            if total and not progress.iscanceled():
                progress.update(int((written / total) * 50), ADDON.getLocalizedString(30304))

        api_client.backup_download(backup_name, zip_path, on_download_progress)

        if progress.iscanceled():
            return False, ADDON.getLocalizedString(30302)

        settings_payload = None

        with zipfile.ZipFile(zip_path, 'r') as zf:
            members = [m for m in zf.namelist() if m not in _META_MEMBERS and not m.endswith('/')]
            total = len(members) or 1

            try:
                settings_payload = json.loads(zf.read('kodi_settings.json').decode('utf-8'))
            except KeyError:
                pass

            for i, member in enumerate(members):
                if progress.iscanceled():
                    return False, ADDON.getLocalizedString(30302)

                progress.update(50 + int((i / total) * 45), ADDON.getLocalizedString(30305))

                category, _sep, relative = member.partition('/')
                root_special = _CATEGORY_ROOTS.get(category, (None, None))[0]
                if root_special is None or not relative:
                    continue  # membre inattendu (ne devrait pas arriver) - ignore par securite
                if category == 'addons' and relative.split('/', 1)[0] == ADDON_ID:
                    # Sauvegardes deja existantes, creees avant l'exclusion
                    # de ADDON_ID dans _ADDONS_EXCLUDE (voir plus haut) :
                    # peuvent encore contenir nos propres fichiers - jamais
                    # restaures, memes raisons (Permission Denied constate
                    # en ecrasant le code en train de s'executer).
                    continue

                dest_root = xbmcvfs.translatePath(root_special)
                dest_path = os.path.join(dest_root, *relative.split('/'))
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)

                with zf.open(member) as source, open(dest_path, 'wb') as target:
                    shutil.copyfileobj(source, target)

        if own_device_name:
            ADDON.setSetting('device_name', own_device_name)

        progress.update(95, ADDON.getLocalizedString(30307))
        xbmc.executebuiltin('UpdateLocalAddons')

        if settings_payload is not None:
            os.makedirs(_own_addon_data_dir(), exist_ok=True)
            with open(_pending_settings_path(), 'w', encoding='utf-8') as fh:
                json.dump(settings_payload, fh)

        progress.update(99, ADDON.getLocalizedString(30307))

        return True, None
    except api_client.ApiError as exc:
        return False, str(exc)
    except (zipfile.BadZipFile, OSError) as exc:
        return False, str(exc)
    finally:
        progress.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
