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
"""
import xbmc

from resources.lib import vstream_db, watch_progress

POLL_INTERVAL = 30  # secondes entre deux sondages periodiques de secours


def _poll_and_report(reader):
    if not watch_progress.enabled():
        return
    device = watch_progress.device_name()
    for tmdb_id, position, duration, resume_key in reader.poll():
        watch_progress.report_vstream(tmdb_id, position, duration, device, resume_key)


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
    reader = vstream_db.VStreamDbReader()
    player = _StopTrigger(reader)
    monitor = xbmc.Monitor()

    while not monitor.waitForAbort(POLL_INTERVAL):
        _poll_and_report(reader)


if __name__ == '__main__':
    run()
