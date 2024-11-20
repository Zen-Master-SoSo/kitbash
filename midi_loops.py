#  kitbash/utils/midi_loops.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os, sys, io, logging, sqlite3, glob, re
import numpy as np
from appdirs import user_config_dir
from random import sample
from mido import parse_all, MidiFile
from mido.midifiles.midifiles import read_file_header


EVENT_STRUCT	= np.dtype([
	('beat', float),
	('pitch', np.uint8),
	('velocity', np.uint8)
])

DEFAULT_BEATS_PER_MEASURE = 4
DEFAULT_USECS_PER_BEAT = 500000
USECS_PER_SECOND = 1000000

class Loop:

	def __init__(self, loop_id):
		cursor = Loops.conn().cursor()
		cursor.execute('SELECT * FROM midi_loops WHERE loop_id = ?', (loop_id,))
		self.loop_id, self.loop_group, self.name, self.beats_per_measure, self.measures, midi_events = cursor.fetchone()
		evfile = io.BytesIO(midi_events)
		self.events = np.load(evfile)

	@property
	def event_length(self):
		return len(self.events)

	def events_scaled(self, bpm, samplerate):
		bps = bpm / 3
		beat_scale = bps * samplerate
		scaled = self.events.copy()
		scaled['beat'] *= beat_scale
		return scaled

	def __str__(self):
		return '<Loop #{0.loop_id}: "{0.name}"; {0.beats_per_measure} beats per measure; {0.measures} measures; {0.event_length} events>'.format(self)

	def print_events(self):
		for evt in self.events.tolist():
			print("{:.2f} {} {}".format(*evt))

class Loops:

	_connection = None

	@classmethod
	def dbfile(cls):
		return os.path.join(user_config_dir(), 'ZenSoSo', 'midibanks.db')

	@classmethod
	def conn(cls):
		if cls._connection is None:
			cls._connection = sqlite3.connect(cls.dbfile())
			cls._connection.execute('PRAGMA foreign_keys = ON')
		return cls._connection

	@classmethod
	def init_schema(cls):
		cls.conn().execute("DROP TABLE IF EXISTS pitches")
		cls.conn().execute("DROP TABLE IF EXISTS midi_loops")
		cls.conn().execute("""
			CREATE TABLE midi_loops (
				loop_id INTEGER PRIMARY KEY,
				loop_group TEXT,
				name TEXT,
				beats_per_measure INTEGER,
				measures INTEGER,
				midi_events BLOB
			)""")
		cls.conn().execute("""
			CREATE TABLE pitches (
				loop_id INTEGER,
				pitch INTEGER,
				FOREIGN KEY(loop_id) REFERENCES midi_loops(loop_id) ON DELETE CASCADE
			)""")
		cls.conn().execute("CREATE INDEX bpm_index ON midi_loops (beats_per_measure)")
		cls.conn().execute("CREATE INDEX measures_index ON midi_loops (measures)")
		cls.conn().execute("CREATE INDEX pitch_index ON pitches (pitch)")

	@classmethod
	def delete_all(cls):
		cls.conn().execute("DELETE FROM midi_loops")
		cls.conn().commit()

	@classmethod
	def import_dirs(cls, base_dir):
		cursor = cls.conn().cursor()
		loop_sql = """
			INSERT INTO midi_loops(loop_group, name, beats_per_measure, measures, midi_events)
			VALUES (?,?,?,?,?)
			RETURNING loop_id
			"""
		pitch_sql = """
			INSERT INTO pitches VALUES (?,?)
			"""
		files = glob.glob(os.path.join(base_dir, '**' , '*.mid'), recursive=True)
		for filename in files:
			loop_group = re.sub(r'(_|[^\w])+', ' ', os.path.dirname(filename).replace(base_dir, ''))
			name = os.path.splitext(os.path.basename(filename))[0]
			try:
				beats_per_measure, measures, events = cls.read_midi_file(filename)
				pitches_used = set([ int(evt['pitch']) for evt in events[:] ])
				evfile = io.BytesIO()
				np.save(evfile, events)
				evfile.seek(0)
				cursor.execute(loop_sql, (loop_group, name, beats_per_measure, measures, evfile.read()))
				row_id = cursor.fetchone()
				cursor.executemany(pitch_sql, [ (row_id[0], pitch) for pitch in pitches_used ] )
				cls.conn().commit()
			except Exception as e:
				print('Failed to import {} {} "{}".'.format(type(e).__name__, e))

	@classmethod
	def read_midi_file(cls, midi_filename):
		"""
		Returns beats_per_measure, measures, events
			beats_per_measure	: (int)
			measures			: (int) measure count, rounded up
			events				: nparray of EVENT_STRUCT
		"""

		# Use mido to open
		mid = MidiFile(midi_filename)
		# Default calculations, overriden by set_tempo and time_signature events
		usecs_per_beat = DEFAULT_USECS_PER_BEAT
		beats_per_measure = DEFAULT_BEATS_PER_MEASURE
		seconds_per_beat = usecs_per_beat / USECS_PER_SECOND
		seconds_per_measure = seconds_per_beat * beats_per_measure
		# Initialize numpy array
		note_event_count = 0
		for msg in mid:
			if msg.type == 'note_on':
				note_event_count += 1
		events = np.zeros(note_event_count, EVENT_STRUCT)
		# Initialize running vars
		time = 0
		ordinal = 0
		measure = 0

		for msg in mid:
			if msg.type == 'set_tempo':
				usecs_per_beat = msg.tempo
				seconds_per_beat = usecs_per_beat / USECS_PER_SECOND
				seconds_per_measure = seconds_per_beat * beats_per_measure
			elif msg.type == 'time_signature':
				time_sig_message = msg
				beats_per_measure = msg.numerator * 4 / msg.denominator
				seconds_per_measure = seconds_per_beat * beats_per_measure
			elif msg.type == 'note_on':
				measure = int(time / seconds_per_measure)
				beat = time / seconds_per_beat
				events[ordinal] = ( beat, msg.note, msg.velocity )
				ordinal += 1
			time += msg.time
		return int(beats_per_measure), measure + 1, events


#  end kitbash/utils/midi_loops.py
