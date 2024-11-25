#  kitbash/__init__.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
#  end kitbash/__init__.py
import os
from appdirs import user_config_dir
from jack_midi_looper import Loops

def loops_database():
	try:
		return loops_database.instance
	except AttributeError:
		dbpath = os.path.join(user_config_dir(), 'ZenSoSo', 'midibanks.db')
		try:
			os.mkdir(dbpath)
		except FileExistsError:
			pass
		loops_database.instance = Loops(dbpath)
	return loops_database.instance
