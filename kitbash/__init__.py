#  kitbash/__init__.py
#
#  Copyright 2024 liyang <liyang@veronica>
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
kitbash is a program you can use to combine parts of various SFZ files into a
new SFZ with instruments "borrowed" from the originals.
"""
import sys, os, argparse, logging, json, glob
try:
	from functools import cache
except ImportError:
	from functools import lru_cache as cache
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication
from qt_extras import DevilBox
from conn_jack import JackConnectError

__version__ = "1.1.0"

APPLICATION_NAME			= "kitbash"
PACKAGE_DIR					= os.path.dirname(__file__)
DEFAULT_STYLE				= 'system'
KEY_STYLE					= 'Style'
KEY_SAMPLES_MODE			= 'KitSaveDialog/SamplesMode'
KEY_RECENT_DRUMKIT_FOLDER	= 'RecentDrumkitFolder'
KEY_RECENT_DRUMKITS			= 'RecentDrumkits'
KEY_RECENT_PROJECT_FOLDER	= 'RecentProjectFolder'
KEY_RECENT_PROJECTS			= 'RecentProjects'
KEY_SAMPLE_XPLORE_ROOT		= 'SampleExplorer/Root'
KEY_SAMPLE_XPLORE_CURR		= 'SampleExplorer/Current'

@cache
def settings():
	return QSettings('ZenSoSo', 'kitbash')

@cache
def styles():
	return {
		os.path.splitext(os.path.basename(path))[0] : path \
		for path in glob.glob(os.path.join(PACKAGE_DIR, 'styles', '*.css'))
	}

def set_application_style():
	style = settings().value(KEY_STYLE, DEFAULT_STYLE)
	with open(styles()[style], 'r', encoding = 'utf-8') as cssfile:
		QApplication.instance().setStyleSheet(cssfile.read())

def main():
	from kitbash.gui.main_window import MainWindow

	p = argparse.ArgumentParser()
	p.epilog = """
	Write your help text!
	"""
	p.add_argument('Filename', type=str, nargs='?', help='SFZ file[s] to include at startup')
	p.add_argument("--log-file", "-l", type=str, help="Log to this file")
	p.add_argument("--verbose", "-v", action="store_true", help="Show more detailed debug information")
	options = p.parse_args()

	log_level = logging.DEBUG if options.verbose else logging.ERROR
	log_format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	if options.log_file:
		logging.basicConfig(
			filename = options.log_file,
			filemode = 'w',
			level = log_level,
			format = log_format
		)
	else:
		logging.basicConfig(
			level = log_level,
			format = log_format
		)

	#-----------------------------------------------------------------------
	# Annoyance fix per:
	# https://stackoverflow.com/questions/986964/qt-session-management-error
	try:
		del os.environ['SESSION_MANAGER']
	except KeyError:
		pass
	#-----------------------------------------------------------------------

	app = QApplication([])
	try:
		main_window = MainWindow(options)
	except JackConnectError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())

if __name__ == "__main__":
	sys.exit(main())


#  end kitbash/__init__.py
