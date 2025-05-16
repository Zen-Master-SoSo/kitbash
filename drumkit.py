#  kitbash/drumkit.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
"""
Provides percussion group / instrument oriented wrapper for SFZ classes.

Notes:
When importing
"""
from os import path
from os import mkdir
from copy import deepcopy
from functools import reduce
from operator import and_, or_
from midi_notes import Note, MIDI_DRUM_PITCHES, MIDI_DRUM_NAMES, MIDI_DRUM_IDS
from sfzen import COMMENT_DIVIDER
from sfzen import SFZ
from sfzen.sort import OPCODE_SORT_ORDER
from sfzen.sfz_elems import Region as SFZRegion
from kitbash import (
	SAMPLES_ABSPATH,
	SAMPLES_RESOLVE,
	SAMPLES_COPY,
	SAMPLES_SYMLINK,
	SAMPLES_HARDLINK
)

def opstring_sorted(opstrings):
	def sort_val(opstring):
		op = opstring.split('=', 1)[0]
		return OPCODE_SORT_ORDER.index(op) \
		if op in OPCODE_SORT_ORDER else 1000
	return sorted(opstrings, key = sort_val)


class Region(SFZRegion):
	"""
	A representation of an SFZ <region> header, extending the Region class from
	sfzen in order to make it mutable.
	"""

	def __init__(self, source_region, source_filename):
		self.subheaders = []
		self._opcodes = source_region.inherited_opcodes()
		self.filename = source_filename
		self.line = source_region.line
		self.column = source_region.column
		self.end_line = source_region.end_line
		self.end_column = source_region.end_column

	def __repr__(self):
		return 'Region: %s, line %d (%d opcodes)' % (
			path.basename(self.filename),
			self.line,
			len(self._opcodes)
		)

	def write(self, stream, exclude_opstrings):
		"""
		Write in SFZ format to any file-like object, including sys.stdout.

		"exclude_opstrings" is a set of string representations (including name and value)
		of all the opcodes NOT to define in this region, as they are common opcodes
		defined in a parent header.
		"""
		stream.write("<region>\n")
		opstrings = opstring_sorted(self.opstrings - exclude_opstrings)
		for opstring in opstrings:
			stream.write(opstring + '\n')
		stream.write('\n')


class PercussionInstrument:
	"""
	Reresents a single instrument trigerred by a single MIDI note number.
	When importing from an SFZ, this class contains the regions that define the
	sound of the instrument.
	"""

	def __init__(self, pitch, regions, filename):
		"""
		Used when importing from an SFZ
		pitch:		(int)	MIDI note number
		regions:	(list)	Region headers from source SFZ
		filename:	(str)	Filename from source SFZ
		"""
		self.note = Note(pitch)
		self.inst_id = MIDI_DRUM_IDS[pitch]
		self.name = MIDI_DRUM_NAMES[pitch]
		self.regions = [ Region(region, filename) for region in regions ]
		self.source_filename = filename

	@property
	def pitch(self):
		"""
		Returns (int) MIDI note number.
		To retrieve in a differnt format, use the .note attribute, which is an instance
		of midi_notes.Note.
		"""
		return self.note.pitch

	def empty(self):
		"""
		Returns True if there are no regions defined for this Instrument's pitch
		"""
		return len(self.regions) == 0

	def write(self, stream, exclude_opstrings):
		"""
		Write in SFZ format to any file-like object, including sys.stdout

		"exclude_opstrings" is a set of string representations (including name and value)
		of all the opcodes NOT to define in this region, as they are common opcodes
		defined in a parent header.
		"""
		stream.write(f'// {self.name}\n')
		stream.write(f'// MIDI pitch: {self.note.pitch}  Note name: {self.note}\n')
		stream.write(f'// Source: {self.source_filename}\n\n')
		if len(self.regions) > 1:
			common_opstrings = self.common_opstrings()
			group_opstrings = common_opstrings - exclude_opstrings
			if group_opstrings:
				stream.write('<group>\n')
				for opstring in opstring_sorted(group_opstrings):
					stream.write(opstring + '\n')
				stream.write('\n')
			exclude_opstrings |= group_opstrings
		for region in self.regions:
			region.write(stream, exclude_opstrings)

	def opstrings_used(self):
		"""
		Returns a set of all the string representation (including name and value) of
		all the opcodes used in this Instrument.
		"""
		return reduce(or_, [region.opstrings for region in self.regions], set())

	def common_opstrings(self):
		"""
		Returns a set of all the string representation (including name and value) of
		all the identical opcodes used in every region in this Instrument.
		"""
		return reduce(and_, [region.opstrings for region in self.regions], set())

	def regions_using_opstring(self, opstring):
		"""
		Generator function which yields each Region which uses the opcode specified.
		opstring: the string representation (including name and value) of an opcode.
		"""
		for region in self.regions:
			if region.uses_opstring(opstring):
				yield region

	def samples_used(self):
		"""
		Returns a set of all raw values of all "sample" opcodes contained in the
		regions defined for this Instrument.
		"""
		return set(region.sample for region in self.regions if region.sample is not None)

	def samples(self):
		"""
		Generator which yields every sample opcode (Opcode class)
		"""
		for region in self.regions:
			if 'sample' in region.opcodes:
				yield region.opcodes['sample']


class PercussionGroup:
	"""
	Class used for organizing instruments in a Drumkit, not to be confused with a
	<group> header in an SFZ file.

	Allows for the user to select an entire category of instruments with one click
	from the gui.
	"""

	def __init__(self, group_id):
		self.group_id = group_id
		self.name = group_id.replace('_', ' ').title()
		self.instruments = { }

	def append_instrument(self, pitch, regions, filename):
		"""
		Adds or replaces an instrument in this group.
		pitch:		(int)	MIDI note number
		regions:	(list)	"region" header and contained opcodes from SFZ
		filename:	(str)	Filename from the source SFZ
		"""
		self.instruments[pitch] = PercussionInstrument(pitch, regions, filename)

	def empty(self):
		"""
		Returns True if not containing any instruments, or contained instruments
		contain no Region -type headers.
		"""
		return all(inst.empty() for inst in self.instruments.values())

	def write(self, stream, exclude_opstrings):
		"""
		Write in SFZ format to any file-like object, including sys.stdout

		"exclude_opstrings" is a set of string representations (including name and value)
		of all the opcodes NOT to define in this region, as they are common opcodes
		defined in a parent header.
		"""
		stream.write(f'{COMMENT_DIVIDER}// "{self.name}" group\n{COMMENT_DIVIDER}\n')
		for inst in self.instruments.values():
			if not inst.empty():
				inst.write(stream, exclude_opstrings)

	def opstrings_used(self):
		"""
		Returns a set of all the string representation (including name and value) of
		all the opcodes used by all Instruments in this Group.
		"""
		return reduce(or_, [instrument.opstrings_used() \
			for instrument in self.instruments.values()], set())

	def common_opstrings(self):
		"""
		Returns a set of all the string representation (including name and value) of
		all the identical opcodes used in every region in this Group.
		"""
		return reduce(and_, [instrument.opstrings_used() \
			for instrument in self.instruments.values()], set())

	def regions_using_opstring(self, opstring):
		"""
		Generator function which yields each Region which uses the opcode specified.
		opstring: the string representation (including name and value) of an opcode.
		"""
		for instrument in self.instruments.values():
			yield from instrument.regions_using_opstring(opstring)

	def samples_used(self):
		"""
		Returns a set of all raw values of all "sample" opcodes contained in the
		regions defined for this Instrument.
		"""
		return reduce(or_, [ instrument.samples_used() \
			for instrument in self.instruments.values() ], set())

	def samples(self):
		"""
		Generator which yields every sample opcode (Opcode class)
		"""
		for instrument in self.instruments.values():
			yield from instrument.samples()


class Drumkit:
	"""
	Represents a set of percussion instruments organized by groups.

	Passing a filename to the constructor loads the given .sfz file and attaches
	its regions to a PercussionInstrument. These are organized under
	PercussionGroup objects.

	You may instantiate an empty Drumkit ohect and import instruments or groups of
	instruments from other Drumkit objects.
	"""

	group_pitches = {
		'bass_drums'	: [35, 36],
		'snares'		: [37, 38, 39, 40],
		'tom_toms'		: [41, 43, 45, 47, 48, 50],
		'high_hats'		: [42, 44, 46],
		'crashes'		: [49, 57],
		'rides'			: [51, 53, 59],
		'other_cymbals'	: [52, 55, 56],
		'bongos'		: [60, 61],
		'congas'		: [62, 63, 64],
		'agogos'		: [67, 68],
		'timbales'		: [65, 66],
		'guiros'		: [73, 74],
		'woodblocks'	: [76, 77],
		'triangles'		: [80, 81],
		'cuica'			: [78, 79],
		'whistle'		: [71, 72],
		'others'		: [54, 58, 69, 70, 75]
	}

	pitch_groups = {
		35	: 'bass_drums',
		36	: 'bass_drums',
		37	: 'snares',
		38	: 'snares',
		39	: 'snares',
		40	: 'snares',
		41	: 'tom_toms',
		43	: 'tom_toms',
		45	: 'tom_toms',
		47	: 'tom_toms',
		48	: 'tom_toms',
		50	: 'tom_toms',
		42	: 'high_hats',
		44	: 'high_hats',
		46	: 'high_hats',
		49	: 'crashes',
		57	: 'crashes',
		51	: 'rides',
		53	: 'rides',
		59	: 'rides',
		52	: 'other_cymbals',
		55	: 'other_cymbals',
		56	: 'other_cymbals',
		60	: 'bongos',
		61	: 'bongos',
		62	: 'congas',
		63	: 'congas',
		64	: 'congas',
		67	: 'agogos',
		68	: 'agogos',
		65	: 'timbales',
		66	: 'timbales',
		73	: 'guiros',
		74	: 'guiros',
		76	: 'woodblocks',
		77	: 'woodblocks',
		80	: 'triangles',
		81	: 'triangles',
		78	: 'cuica',
		79	: 'cuica',
		71	: 'whistle',
		72	: 'whistle',
		54	: 'others',
		58	: 'others',
		69	: 'others',
		70	: 'others',
		75	: 'others'
	}

	def __init__(self, filename=None):
		self.groups = { group_id:PercussionGroup(group_id) for group_id in self.group_pitches.keys() }
		self.filename = filename
		if self.filename is None:
			self.name = '[unnamed drumkit]'
		else:
			self.name = path.basename(filename)
			sfz = SFZ(self.filename)
			for pitch, group_id in Drumkit.pitch_groups.items():
				regions = list(sfz.regions_for(lokey=pitch, hikey=pitch))
				if regions:
					self.groups[group_id].append_instrument(pitch, regions, filename)

	def save_as(self, filename, samples_mode = SAMPLES_ABSPATH):
		"""
		Save in SFZ format to the given filename.
		"samples_mode" is a kitbash constant which defines how to render "sample"
		opcodes. May be one of:
			SAMPLES_ABSPATH		SAMPLES_RESOLVE		SAMPLES_COPY
			SAMPLES_SYMLINK		SAMPLES_HARDLINK
		"""
		filename = path.abspath(filename)
		target_dir = path.dirname(filename)
		try:
			mkdir(target_dir)
		except FileExistsError:
			pass
		if samples_mode == SAMPLES_ABSPATH:
			for sample in self.samples():
				sample.use_abspath()
		elif samples_mode == SAMPLES_RESOLVE:
			for sample in self.samples():
				sample.resolve_from(target_dir)
		else:
			target_sample_dir = path.join(target_dir, 'samples')
			try:
				mkdir(target_sample_dir)
			except FileExistsError:
				pass
			for sample in self.samples():
				try:
					if samples_mode == SAMPLES_COPY:
						sample.copy_to(target_sample_dir)
					elif samples_mode == SAMPLES_SYMLINK:
						sample.symlink_to(target_sample_dir)
					elif samples_mode == SAMPLES_HARDLINK:
						sample.hardlink_to(target_sample_dir)
				except FileExistsError:
					pass
		with open(filename, 'w') as fob:
			self.write(fob)

	def write(self, stream):
		"""
		Write in SFZ format to any file-like object, including sys.stdout.
		"""
		stream.write(f'//\n// {self.name}\n//\n')
		global_opstrings = self.common_opstrings()
		if global_opstrings:
			stream.write('<global>\n')
			for opstring in opstring_sorted(global_opstrings):
				stream.write(opstring + '\n')
			stream.write('\n')
		for group in self.groups.values():
			if not group.empty():
				group.write(stream, global_opstrings)

	def import_group(self, group_id, source_kit):
		"""
		Do a deep copy from the given Drumkit, of the specified group.
		group_id:	(str)		Group ID, as from Drumkit.group_pitches
		source_kit	(Drumkit)	Source to copy from

		Raises IndexError if the specified group was not found in the source kit.
		"""
		self.groups[group_id] = deepcopy(source_kit.groups[group_id])

	def import_instrument(self, arg, source_kit):
		"""
		Do a deep copy from the given Drumkit, of the instrument tied to the spectfied
		pitch.
		pitch:		(int)		MIDI note number of the instrument to copy.
		source_kit	(Drumkit)	Source to copy from
		"""
		pitch, _ = self.instrument_selection_arg(arg)
		group_id = self.pitch_groups[pitch]
		self.groups[group_id].instruments[pitch] = \
			deepcopy(source_kit.instrument(pitch))

	def delete_instrument(self, arg):
		"""
		Removes an instrument - quicker than reimporting everything when changes are made.
		"""
		pitch, _ = self.instrument_selection_arg(arg)
		group_id = self.pitch_groups[pitch]
		del self.groups[group_id].instruments[pitch]

	def opstrings_used(self):
		"""
		Returns a set of all the string representation (including name and value) of
		all the opcodes used in this Drumkit
		"""
		return reduce(or_, [group.opstrings_used() for group in self.groups.values()], set())

	def common_opstrings(self):
		"""
		Returns a set of all the string representation (including name and value) of
		all the identical opcodes used in every region in this Drumki.
		"""
		return reduce(and_, [group.opstrings_used() for group in self.groups.values()], set())

	def regions_using_opstring(self, opstring):
		"""
		Generator function which yields each Region which uses the opcode specified.
		opcode: the string representation (including name and value) of an opcode.
		"""
		for group in self.groups.values():
			yield from group.regions_using_opstring(opstring)

	def opstring_usage(self):
		"""
		Returns a dict of lists
		Keys are the string representation of the opcode, (including name and value).
		Values are a list of regions where it is used.
		"""
		return {
			opstring:list(self.regions_using_opstring(opstring)) \
			for opstring in self.opstrings_used()
		}

	def samples(self):
		"""
		Generator which yields every sample opcode (Opcode class)
		"""
		for group in self.groups.values():
			yield from group.samples()

	def samples_used(self):
		"""
		Returns a set of all raw values of all "sample" opcodes used in this Drumkit.
		"""
		return reduce(or_, [group.samples_used() \
			for group in self.groups.values()], set())

	def instruments(self):
		"""
		Generator function which yields every instrument.
		"""
		for group in self.groups.values():
			for instrument in group.instruments.values():
				yield instrument

	def instrument_ids(self):
		"""
		Returns a list of (str) inst_id
		"""
		return [ instrument.inst_id for instrument in self.instruments() ]

	def instrument_pitches(self):
		"""
		Returns a list of (int) pitch
		"""
		return [ instrument.pitch for instrument in self.instruments() ]

	def instrument_selection_arg(self, arg):
		"""
		Returns tuple:
			(int) pitch
			(str) instrument_id
		"arg" may be a pitch or an instrument id string (i.e. "side_stick").
		"""
		if arg in MIDI_DRUM_IDS:
			return arg, MIDI_DRUM_IDS[arg]
		if arg in MIDI_DRUM_PITCHES:
			return MIDI_DRUM_PITCHES[arg], arg
		raise ValueError(f'"{arg}" not recognized as an instrument id or pitch' )

	def instrument(self, arg):
		"""
		Returns a PercussionInstrument.
		"arg" may be a pitch or an instrument id string (i.e. "side_stick").

		Raises IndexError if the instrument is not found in this Drumkit.
		"""
		pitch, _ = self.instrument_selection_arg(arg)
		group_id = self.pitch_groups[pitch]
		return self.groups[group_id].instruments[pitch]

	def group(self, group_id):
		"""
		Convenience function for syntactic uniformity.
		"""
		return self.groups[group_id]

	def __str__(self):
		return f"<Drumkit {self.name}>"


#  end kitbash/drumkit.py
