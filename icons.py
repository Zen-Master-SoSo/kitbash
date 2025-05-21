#  kitbash/icons.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
"""
Icon store.
Defers loading of QPixmaps until a QGuiApplication is instantiated.
This is a Qt5 requirement.
"""
import os
from functools import lru_cache
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QSize
from kitbash import PACKAGE_DIR

AUDIO_ICON_SIZE = QSize(21, 18)

@lru_cache
def GROUP_EXPANDED():
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'group_expanded.svg'))

@lru_cache
def GROUP_HIDDEN():
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'group_hidden.svg'))

@lru_cache
def ICON_CLOSE():
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'close.svg'))

@lru_cache
def PIXMAP_AUDIO_OFF():
	return QIcon.fromTheme('audio-volume-muted').pixmap(AUDIO_ICON_SIZE)

@lru_cache
def PIXMAP_AUDIO_ON():
	return QIcon.fromTheme('audio-volume-high').pixmap(AUDIO_ICON_SIZE)

#  end kitbash/icons.py
