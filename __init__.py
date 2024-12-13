#  kitbash/__init__.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
from appdirs import user_config_dir
from jack_midi_looper import LoopsDB

APPLICATION_NAME	= "kitbash"
PACKAGE_DIR			= os.path.dirname(__file__)
LOOPER_CLIENT_NAME	= 'looper'
LOOPER_PORT_NAME	= 'kit'
LOOPER_PORT_FORMAT	= 'kit_%02d'
LOOPER_BASHED_PORT	= 'bashed'
SAMPLES_ABSPATH		= 0
SAMPLES_RESOLVE		= 1
SAMPLES_COPY		= 2
SAMPLES_SYMLINK		= 3
SAMPLES_HARDLINK	= 4


def loops_database():
	try:
		return loops_database.instance
	except AttributeError:
		pass
	db_dir = os.path.join(user_config_dir(), 'ZenSoSo')
	try:
		os.mkdir(db_dir)
	except FileExistsError:
		pass
	loops_database.instance = LoopsDB(os.path.join(db_dir, 'kitbash-midiloops.db'))
	return loops_database.instance

#  end kitbash/__init__.py
