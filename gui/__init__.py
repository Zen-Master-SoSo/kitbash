#  kitbash/gui/__init__.py
#
#  Copyright 2025 liyang <liyang@veronica>
#
import sys, os, argparse, logging, json, glob
from functools import lru_cache
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QWidget, QSplitter
from qt_extras import DevilBox
from kitbash import PACKAGE_DIR, settings


AUDIO_ICON_SIZE = 16

@lru_cache
def group_expanded_icon():
	"""
	Defers loading of QPixmaps until a QGuiApplication is instantiated.
	This is a Qt5 requirement.
	"""
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'group_expanded.svg'))

@lru_cache
def group_hidden_icon():
	return QIcon(os.path.join(PACKAGE_DIR, 'res', 'group_hidden.svg'))

@lru_cache
def remove_icon():
	return QIcon.fromTheme('edit-delete')

@lru_cache
def audio_off_pixmap():
	return QIcon.fromTheme('audio-volume-muted').pixmap(AUDIO_ICON_SIZE)

@lru_cache
def audio_on_pixmap():
	return QIcon.fromTheme('audio-volume-high').pixmap(AUDIO_ICON_SIZE)


class GeometrySaver:
	"""
	Provides classes declared in this project which inherit from QDialog methods to
	easily save/restore window / splitter geometry.

	Geometry is saved in this project's QSettings accessed as "settings()"
	"""

	def restore_geometry(self):
		if not hasattr(self, 'restoreGeometry'):
			logging.error('Object of type %s has no "restoreGeometry" function',
				type(self).__name__)
			return
		geometry = settings().value(self.__geometry_key())
		if geometry is not None:
			self.restoreGeometry(geometry)
		for splitter in self.findChildren(QSplitter):
			geometry = settings().value(self.__splitter_geometry_key(splitter))
			if geometry is not None:
				splitter.restoreState(geometry)

	def save_geometry(self):
		if not hasattr(self, 'saveGeometry'):
			logging.error('Object of type %s has no "saveGeometry" function',
				type(self).__name__)
			return
		settings().setValue(self.__geometry_key(), self.saveGeometry())
		for splitter in self.findChildren(QSplitter):
			settings().setValue(self.__splitter_geometry_key(splitter), splitter.saveState())

	def __geometry_key(self):
		return '{}/geometry'.format(type(self).__name__)

	def __splitter_geometry_key(self, splitter):
		return '{}/{}/geometry'.format(type(self).__name__, splitter.objectName())


#  end kitbash/gui/__init__.py
