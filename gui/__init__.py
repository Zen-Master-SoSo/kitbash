#  kitbash/gui/__init__.py
#
#  Copyright 2025 liyang <liyang@veronica>
#
import sys, os, argparse, logging, json, glob
from PyQt5.QtWidgets import QApplication, QWidget, QSplitter
from qt_extras import DevilBox
from kitbash import settings


class GeometrySaver:

	def restore_geometry(self):
		if not hasattr(self, 'restoreGeometry'):
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
			return
		settings().setValue(self.__geometry_key(), self.saveGeometry())
		for splitter in self.findChildren(QSplitter):
			settings().setValue(self.__splitter_geometry_key(splitter), splitter.saveState())

	def __geometry_key(self):
		return '{}/geometry'.format(type(self).__name__)

	def __splitter_geometry_key(self, splitter):
		return '{}/{}/geometry'.format(type(self).__name__, splitter.objectName())


#  end kitbash/gui/__init__.py
