# -*- coding: utf-8 -*-
"""Construit l'URL SMB de lecture. La vidéo ne passe jamais par le serveur
Flask (un seul worker gunicorn, déjà partagé avec les téléchargements en
arrière-plan) : Kodi lit directement le partage réseau via son propre
client SMB, natif sur Android/Linux/Windows.
"""
import urllib.parse

import xbmcaddon

ADDON = xbmcaddon.Addon()


def build_smb_url(relative_path):
    server = ADDON.getSettingString('server').strip()
    share = ADDON.getSettingString('smb_share').strip()
    # Le client SMB de Kodi (libsmbclient) attend de l'UTF-8 brut dans la
    # partie chemin/partage d'une URL smb:// — un chemin pourcent-encodé
    # (%20, %28...) échouait silencieusement à l'ouverture (confirmé en
    # direct : Creating InputStream -> error opening, sans aucune trace
    # Python, jusqu'à retirer l'encodage du chemin). Seuls les identifiants
    # sont encodés, pour rester protégés si jamais ils contiennent "@"/":"
    # (qui casseraient sinon le découpage user:pass@host de l'URL).
    user = urllib.parse.quote(ADDON.getSettingString('smb_username'), safe='')
    pwd = urllib.parse.quote(ADDON.getSettingString('smb_password'), safe='')

    return 'smb://{user}:{pwd}@{host}/{share}/{path}'.format(
        user=user, pwd=pwd, host=server, share=share, path=relative_path,
    )
