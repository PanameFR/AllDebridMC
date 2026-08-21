# -*- coding: utf-8 -*-
"""Service Kodi persistant (xbmc.service, demarre avec Kodi) : suit
UNIQUEMENT la lecture de films vStream/Pastebin lancee depuis notre propre
addon (Mes Listes/Recherche/En cours - voir
resources/lib/watch_progress.py::arm_vstream_marker), jamais la navigation
native de vStream - aucune identite TMDB fiable n'en ressort une fois la
lecture reelle demarree (verifie en lisant le code source de vStream avant
de construire ceci, voir la docstring de watch_progress.py). La lecture
MediaCenter est deja suivie par navigation.play_item()/track_playback(),
qui reste actif dans le processus du script le temps de la lecture - ce
service l'ignore explicitement (watch_progress.is_own_smb_path) pour ne
jamais la rapporter deux fois.
"""
import xbmc

from resources.lib import watch_progress


class _VStreamProgressPlayer(xbmc.Player):
    def __init__(self):
        super(_VStreamProgressPlayer, self).__init__()
        self.tmdb_id = None
        self.stopped = False

    def onAVStarted(self):
        # Reinitialise a chaque nouvelle lecture, jamais de fuite d'un
        # tmdb_id suivi lors d'une session PRECEDENTE vers celle-ci.
        self.stopped = False
        self.tmdb_id = None

        try:
            playing_file = self.getPlayingFile()
        except Exception:
            return

        if watch_progress.is_own_smb_path(playing_file):
            return  # deja suivi par track_playback() cote script de lecture

        marker = watch_progress.consume_vstream_marker()
        if marker:
            self.tmdb_id = marker.get('tmdb_id')
        # Sinon : navigation native de vStream, ou tout autre contenu -
        # honnetement non identifiable, on n'essaie pas de deviner.

    def onPlayBackStopped(self):
        self.stopped = True

    def onPlayBackEnded(self):
        self.stopped = True

    def onPlayBackError(self):
        self.stopped = True


def run():
    player = _VStreamProgressPlayer()
    monitor = xbmc.Monitor()
    last_position, last_duration = 0.0, 0.0
    reported_stop_for = None  # evite de renvoyer plusieurs fois le meme rapport final

    while not monitor.waitForAbort(watch_progress.HEARTBEAT_INTERVAL):
        if player.tmdb_id is None:
            continue

        if player.stopped:
            if last_duration and player.tmdb_id != reported_stop_for:
                watch_progress.report_vstream(
                    player.tmdb_id, last_position, last_duration, watch_progress.device_name(),
                )
                reported_stop_for = player.tmdb_id
            continue

        if not player.isPlaying():
            continue

        try:
            last_position, last_duration = player.getTime(), player.getTotalTime()
        except Exception:
            continue

        watch_progress.report_vstream(
            player.tmdb_id, last_position, last_duration, watch_progress.device_name(),
        )
        reported_stop_for = None


if __name__ == '__main__':
    run()
