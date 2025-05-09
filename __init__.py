#  kitbash/__init__.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
from PyQt5.QtCore import QSettings

APPLICATION_NAME	= "kitbash"
PACKAGE_DIR			= os.path.dirname(__file__)
SAMPLES_ABSPATH		= 0
SAMPLES_RESOLVE		= 1
SAMPLES_COPY		= 2
SAMPLES_SYMLINK		= 3
SAMPLES_HARDLINK	= 4

def settings():
	if getattr(settings, '_cached_var', None) is None:
		settings._cached_var = QSettings("ZenSoSo", APPLICATION_NAME)
	return settings._cached_var

#  end kitbash/__init__.py
