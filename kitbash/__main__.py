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
kitbash is a program you can use to combine parts of various SFZ files into a
new SFZ with instruments "borrowed" from the originals.
"""
import sys, os, argparse, logging
from PyQt5.QtWidgets import QApplication, QErrorMessage
from qt_extras import exceptions_hook
from kitbash.gui.main_window import MainWindow


def main():
	p = argparse.ArgumentParser()
	p.epilog = __doc__
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
	sys.excepthook = exceptions_hook
	main_window = MainWindow(options)
	main_window.show()
	sys.exit(app.exec())

if __name__ == "__main__":
	sys.exit(main())


#  end kitbash/kitbash/__init__.py
