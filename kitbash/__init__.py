#  kitbash/kitbash/__init__.py
#
#  Copyright 2025-2026 Leon Dionne <ldionne@dridesign.sh.cn>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
"""
Provides universal settings, styles, cached icons, and pixmaps, and the base
class of windows which save and restore their own geometry.
"""
import logging
from os.path import dirname, basename, splitext, join
from glob import glob
from functools import lru_cache
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication, QSplitter
from qt_extras import DevilBox

__version__ = "1.8.1"

APPLICATION_NAME			= "kitbash"
PACKAGE_DIR					= dirname(__file__)
DEFAULT_STYLE				= 'system'
AUDIO_ICON_SIZE				= 16
KEY_PREVIEW_VELOCITY		= 'PreviewVelocity'
KEY_STYLE					= 'Style'
KEY_SAMPLES_MODE			= 'KitSaveDialog/SamplesMode'
KEY_RECENT_DRUMKIT_FOLDER	= 'RecentDrumkitFolder'
KEY_RECENT_DRUMKITS			= 'RecentDrumkits'
KEY_RECENT_PROJECT_FOLDER	= 'RecentProjectFolder'
KEY_RECENT_PROJECTS			= 'RecentProjects'
KEY_SAMPLE_XPLORE_ROOT		= 'SampleExplorer/Root'
KEY_SAMPLE_XPLORE_CURR		= 'SampleExplorer/Current'
KEY_MIDI_SOURCE				= 'MIDISource'
KEY_AUDIO_SINK				= 'AudioSink'


def audio():
	if not hasattr(audio, 'instance'):
		from kitbash.jack_audio import Audio
		audio.instance = Audio()
	return audio.instance

@lru_cache
def __settings():
	return QSettings('ZenSoSo', APPLICATION_NAME)

def get_setting(key, default = None, type_ = None):
	value = __settings().value(key, default)
	if type_:
		if value is None:
			return type_()
		if type_ is bool:
			return value == '1'
		return type_(value)
	return value

def set_setting(key, value):
	if isinstance(value, bool):
		value = '1' if value else '0'
	__settings().setValue(key, value)

def delete_setting(key):
	__settings().remove(key)

@lru_cache
def styles():
	return {
		splitext(basename(path))[0] : path \
		for path in glob(join(PACKAGE_DIR, 'styles', '*.css'))
	}

def set_application_style():
	style = get_setting(KEY_STYLE, DEFAULT_STYLE)
	with open(styles()[style], 'r', encoding = 'utf-8') as cssfile:
		QApplication.instance().setStyleSheet(cssfile.read())


class GeometrySaver:
	"""
	Provides classes declared in this project which inherit from QDialog methods to
	easily save/restore window / splitter geometry.

	Geometry is saved in this project's QSettings accessed as "settings()"
	"""

	def restore_geometry(self):
		if not hasattr(self, 'restoreGeometry'):
			logging.error('Object of type %s has no "restoreGeometry" function',
				self.__class__.__name__)
			return
		geometry = get_setting(self.__geometry_key())
		if geometry is not None:
			self.restoreGeometry(geometry)	# pylint: disable = no-member
		# pylint: disable-next = no-member
		for splitter in self.findChildren(QSplitter):
			geometry = get_setting(self.__splitter_geometry_key(splitter))
			if geometry is not None:
				splitter.restoreState(geometry)	# pylint: disable = no-member

	def save_geometry(self):
		if not hasattr(self, 'saveGeometry'):
			logging.error('Object of type %s has no "saveGeometry" function',
				self.__class__.__name__)
			return
		set_setting(
			self.__geometry_key(),
			self.saveGeometry())	# pylint: disable = no-member
		# pylint: disable-next = no-member
		for splitter in self.findChildren(QSplitter):
			set_setting(
				self.__splitter_geometry_key(splitter),
				splitter.saveState())	# pylint: disable = no-member

	def __geometry_key(self):
		return f'{self.__class__.__name__}/geometry'

	def __splitter_geometry_key(self, splitter):
		return f'{self.__class__.__name__}/{splitter.objectName()}/geometry'


#  end kitbash/kitbash/__init__.py
