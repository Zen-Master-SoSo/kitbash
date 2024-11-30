#  kitbash/icons.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QSize

from kitbash import PACKAGE_DIR


ICON_EXPANDED = QIcon(os.path.join(PACKAGE_DIR, 'res', 'group_expanded.svg'))
ICON_HIDDEN = QIcon(os.path.join(PACKAGE_DIR, 'res', 'group_hidden.svg'))

ICON_CLOSE = QIcon.fromTheme('window-close')

size = QSize(27, 24)
PIXMAP_AUDIO_OFF = QIcon(os.path.join(PACKAGE_DIR, 'res', 'audio-off.svg')).pixmap(size)
PIXMAP_AUDIO_ON = QIcon(os.path.join(PACKAGE_DIR, 'res', 'audio-on.svg')).pixmap(size)


#  end kitbash/icons.py
