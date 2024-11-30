#  kitbash/icons.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
from functools import lru_cache
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QSize
from kitbash import PACKAGE_DIR

AUDIO_ICON_SIZE = QSize(21, 18)

@lru_cache
def ICON_EXPANDED():
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'group_expanded.svg'))

@lru_cache
def ICON_HIDDEN():
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'group_hidden.svg'))

@lru_cache
def ICON_CLOSE():
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'close.svg'))

@lru_cache
def PIXMAP_AUDIO_OFF():
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'audio-off.svg')).pixmap(AUDIO_ICON_SIZE)

@lru_cache
def PIXMAP_AUDIO_ON():
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'audio-on.svg')).pixmap(AUDIO_ICON_SIZE)

#  end kitbash/icons.py
