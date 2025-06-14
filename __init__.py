#  kitbash/__init__.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys, os, argparse, logging, json, glob
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication
from jack_connection_manager import JackConnectError

APPLICATION_NAME			= "kitbash"
PACKAGE_DIR					= os.path.dirname(__file__)
DEFAULT_STYLE				= 'system'
SAMPLES_ABSPATH				= 0
SAMPLES_RESOLVE				= 1
SAMPLES_COPY				= 2
SAMPLES_SYMLINK				= 3
SAMPLES_HARDLINK			= 4
KEY_STYLE					= 'Style'
KEY_SAMPLES_MODE			= 'FileSaveDialog/SamplesMode'
KEY_RECENT_DRUMKIT_FOLDER	= 'RecentDrumkitFolder'
KEY_RECENT_DRUMKITS			= 'RecentDrumkits'
KEY_RECENT_PROJECT_FOLDER	= 'RecentProjectFolder'
KEY_RECENT_PROJECTS			= 'RecentProjects'
KEY_SAMPLE_XPLORE_ROOT		= 'SampleExplorerRoot'
KEY_SAMPLE_XPLORE_CURR		= 'SampleExplorerCurrent'

def settings():
	if getattr(settings, '_cached_var', None) is None:
		settings._cached_var = QSettings("ZenSoSo", APPLICATION_NAME)
	return settings._cached_var

def styles():
	if getattr(styles, '_cached_var', None) is None:
		styles._cached_var = {
			os.path.splitext(os.path.basename(path))[0] : path \
			for path in glob.glob(os.path.join(PACKAGE_DIR, 'styles', '*.css'))
		}
	return styles._cached_var

def set_application_style():
	style = settings().value(KEY_STYLE, DEFAULT_STYLE)
	with open(styles()[style], 'r') as cssfile:
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
