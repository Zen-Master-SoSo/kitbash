#  kitbash/drumkit.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
"""
Provides percussion group / instrument oriented wrapper for SFZ classes.

Notes:
When importing
"""
from os.path import basename
from copy import deepcopy
from functools import cached_property
from functools import reduce
from midi_notes import Note, MIDI_DRUM_PITCHES, MIDI_DRUM_NAMES, MIDI_DRUM_IDS
from kitbash.sfz import COMMENT_DIVIDER
from kitbash.sfz import SFZ
from kitbash.sfz_elems import Global as SFZGlobal
from kitbash.sfz_elems import Group as SFZGroup
from kitbash.sfz_elems import Region as SFZRegion

class Global(SFZGlobal):
	pass

class Group(SFZGroup):
	pass

class Region(SFZRegion):

	def __init__(self, source_region, source_filename):
		self.subheaders = []
		self._opcodes = source_region.inherited_opcodes()
		self.filename = source_filename
		self.line = source_region.line
		self.column = source_region.column
		self.end_line = source_region.end_line
		self.end_column = source_region.end_column

	@cached_property
	def opstrs(self):
		"""
		Returns a list of all the string representation (including name and value) of
		all the opcodes which are used by this Region. That includes opcodes defined in
		this Region as well as opcodes inherited from container groups, such as Group,
		Master, and Global groups.
		"""
		return [str(opcode) for opcode in self._opcodes.values()]

	def uses_opstr(self, opstr):
		"""
		Returns True if the given string representation (including name and value) of
		an opcode is used by this Region. Checks opcodes defined in this Region as well
		as opcodes inherited from container groups, such as Group, Master, and Global
		groups.
		Note that opcode name AND value must match.
		"""
		return opstr in self.opstrs

	def __repr__(self):
		return 'Region: %s, line %d (%d opcodes)' % (
			basename(self.filename),
			self.line,
			len(self._opcodes)
		)


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
		self.regions = [ Region(region, filename) for region in regions ]
		self.inst_id = MIDI_DRUM_IDS[pitch]
		self.name = MIDI_DRUM_NAMES[pitch]

	@property
	def pitch(self):
		"""
		Returns (int) MIDI note number.
		To retrieve in a differnt format, use the .note attribute, which is an instance
		of midi_notes.Note.
		"""
		return self.note.pitch

	def empty(self):
		return len(self.regions) == 0

	def write(self, stream):
		"""
		Write in SFZ format to any file-like object, including sys.stdout
		"""
		stream.write(f'// {self.name}\n')
		stream.write(f'// MIDI pitch: {self.note.pitch}  Note name: {self.note}\n')
		stream.write(f'// Source file: {self.source_filename}\n\n')
		for region in self.regions:
			region.write(stream)

	def opcodes_used(self):
		"""
		Returns a set of all the string representation (including name and value) of
		all the opcodes used in this Instrument.
		"""
		return reduce(
			lambda a,b: set(a) | set(b),
			[region.opstrs for region in self.regions]
		)

	def regions_using_opcode(self, opstr):
		"""
		Generator function which yields each Region which uses the opcode specified.
		opstr: the string representation (including name and value) of an opcode.
		"""
		for region in self.regions:
			if region.uses_opstr(opstr):
				yield region

	def common_opcodes(self):
		return reduce(
			lambda a,b: set(a) & set(b),
			[region.opstrs for region in self.regions]
		)


class PercussionGroup:

	def __init__(self, group_id):
		self.group_id = group_id
		self.name = group_id.replace('_', ' ').title()
		self.instruments = { }

	def append_instrument(self, pitch, regions, filename):
		"""
		Adds orreplaces an instrument in this group.
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

	def write(self, stream):
		"""
		Write in SFZ format to any file-like object, including sys.stdout
		"""
		stream.write(f'{COMMENT_DIVIDER}// Percussion group "{self.name}"\n\n')
		for inst in self.instruments.values():
			if not inst.empty():
				inst.write(stream)

	def opcodes_used(self):
		"""
		Returns a set of all the string representation (including name and value) of
		all the opcodes used in this Group.
		"""
		a = []
		for inst in self.instruments.values():
			a.extend(inst.opcodes_used())
		return set(a)

	def regions_using_opcode(self, opstr):
		"""
		Generator function which yields each Region which uses the opcode specified.
		opstr: the string representation (including name and value) of an opcode.
		"""
		for instrument in self.instruments.values():
			yield from instrument.regions_using_opcode(opstr)


class Drumkit:

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
		self.groups = { }
		self.filename = filename
		if self.filename is None:
			self.name = '[unnamed drumkit]'
		else:
			self.name = basename(filename)
			sfz = SFZ(self.filename)
			for pitch, group_id in Drumkit.pitch_groups.items():
				regions = list(sfz.regions_for(lokey=pitch, hikey=pitch))
				if regions:
					if group_id not in self.groups:
						self.groups[group_id] = PercussionGroup(group_id)
					self.groups[group_id].append_instrument(pitch, regions, filename)

	def write(self, stream):
		"""
		Write in SFZ format to any file-like object, including sys.stdout
		"""
		stream.write(f'{COMMENT_DIVIDER}// {self.name}\n{COMMENT_DIVIDER}\n')
		for group in self.groups.values():
			if not group.empty():
				group.write(stream)

	def import_group(self, group_id, source_kit):
		"""
		Do a deep copy from the given Drumkit, of the specified group.
		group_id:	(str)		Group ID, as from Drumkit.group_pitches
		source_kit	(Drumkit)	Source to copy from
		"""
		if not group_id in source_kit.groups:
			raise Exception(f'Source kit "{source_kit}" does not have a "{group_id}" group')
		self.groups[group_id] = deepcopy(source_kit.groups[group_id])

	def import_instrument(self, pitch, source_kit):
		"""
		Do a deep copy from the given Drumkit, of the instrument tied to the spectfied
		pitch.
		pitch:		(int)		MIDI note number of the instrument to copy.
		source_kit	(Drumkit)	Source to copy from
		"""
		pitch, inst_id = self.instrument_ids(pitch)
		self.groups[group_id].instruments[pitch] = deepcopy(source_kit.instrument(pitch))

	def opcodes_used(self):
		"""
		Returns a set of all the string representation (including name and value) of
		all the opcodes used in this Drumkit
		"""
		a = []
		for group in self.groups.values():
			a.extend(group.opcodes_used())
		return set(a)

	def regions_using_opcode(self, opstr):
		"""
		Generator function which yields each Region which uses the opcode specified.
		opcode: the string representation (including name and value) of an opcode.
		"""
		for group in self.groups.values():
			yield from group.regions_using_opcode(opstr)

	def opcode_usage(self):
		"""
		Returns a dict pf lists, each item's key being the representaion of the opcode,
		(including name and value) and value a list of regions where it is used.
		"""
		return {
			opstr:list(self.regions_using_opcode(opstr)) \
			for opstr in self.opcodes_used()
		}

	def instrument_ids(self, arg):
		"""
		Returns tuple:
			(int) pitch
			(str) instrument_id
		"""
		if arg in MIDI_DRUM_IDS:
			return arg, MIDI_DRUM_IDS[arg]
		elif arg in MIDI_DRUM_PITCHES:
			return MIDI_DRUM_PITCHES[arg], arg
		else:
			raise ValueError()

	def instrument(self, arg):
		pitch, inst_id = self.instrument_ids(arg)
		group_id = self.pitch_groups[pitch]
		if group_id not in self.groups:
			raise IndexError(group_id)
		if pitch not in self.groups[group_id].instruments:
			raise IndexError(pitch)
		return self.groups[group_id].instruments[pitch]

	def __str__(self):
		return f"<Drumkit {self.filename}>"


#  end kitbash/drumkit.py
