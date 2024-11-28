#  kitbash/drumkit.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
from os import path
from copy import deepcopy
from midi_notes import Note, MIDI_DRUM_PITCHES, MIDI_DRUM_NAMES, MIDI_DRUM_IDS
from kitbash.sfz import SFZ


class PercussionInstrument:

	def __init__(self, pitch, regions, filename):
		"""
		pitch:		(int)	MIDI note number
		regions:	(list)	"region" header and contained opcodes from SFZ
		filename:	(str)	Filename from the source SFZ
		"""
		self.note = Note(pitch)
		self.regions = regions
		self.source_filename = filename
		self.inst_id = MIDI_DRUM_IDS[pitch]
		self.name = MIDI_DRUM_NAMES[pitch]

	def import_regions_from(self, sfz):
		"""
		Does a deep copy from the given SFZ of all regions used by this instrument.
		"""
		self.regions.extend(list(sfz.regions_for(lokey=self.note.pitch, hikey=self.note.pitch)))

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
		stream.write(f'// "{self.name}"\n')
		stream.write(f'// MIDI pitch: {self.note.pitch}  Note name: {self.note}\n')
		stream.write(f'// Source file: {self.source_filename}\n\n')
		for region in self.regions:
			region.write(stream)

	def opcodes_used(self):
		a = []
		for region in self.regions:
			a.extend(list(region.opcodes.keys()))
		return set(a)

	def uses_opcode(self, opname):
		return opname in self.opcodes_used()


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

	def import_regions_from(self, sfz):
		"""
		Does a deep copy from the given SFZ of all instruments in this group.
		"""
		for inst in self.instruments.values():
			inst.import_regions_from(sfz)

	def empty(self):
		"""
		Returns True if not containing any instruments, or contained instruments
		contain no Region -type headers.
		"""
		for inst in self.instruments.values():
			if not inst.empty():
				return False
		return True

	def write(self, stream):
		"""
		Write in SFZ format to any file-like object, including sys.stdout
		"""
		stream.write(f'\n// Percussion group "{self.name}"\n\n')
		for inst in self.instruments.values():
			if not inst.empty():
				inst.write(stream)

	def opcodes_used(self):
		a = []
		for inst in self.instruments.values():
			a.extend(inst.opcodes_used())
		return set(a)

	def uses_opcode(self, opname):
		return opname in self.opcodes_used()


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
			self.name = path.basename(filename)
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
		stream.write(f'// ----------------------------------------\n//   {self.name}\n// ----------------------------------------\n\n')
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
		if isinstance(pitch, int):
			inst_id = MIDI_DRUM_IDS[pitch]
		elif pitch in MIDI_DRUM_PITCHES:
			inst_id = pitch
			pitch = MIDI_DRUM_PITCHES[inst_id]
		else:
			raise ValueError()
		group_id = Drumkit.pitch_groups[pitch]
		if not group_id in source_kit.groups:
			raise Exception(f'Source kit "{source_kit}" does not have a "{group_id}" group')
		source_group = source_kit.groups[group_id]
		if not pitch in source_group.instruments:
			raise Exception(f'Source kit "{source_kit}" group "{group_id}" does not have a "{inst_id}" instrument')
		if group_id not in self.groups:
			self.groups[group_id] = PercussionGroup(group_id)
		self.groups[group_id].instruments[pitch] = deepcopy(source_kit.groups[group_id].instruments[pitch])

	def opcodes_used(self):
		a = []
		for group in self.groups.values():
			a.extend(group.opcodes_used())
		return set(a)

	def opcode_usage(self):
		return {
			opname:[
				group_id for group_id in self.groups.keys() if self.groups[group_id].uses_opcode(opname)
			] for opname in self.opcodes_used()
		}

	def __str__(self):
		return f"<Drumkit {self.filename}>"


#  end kitbash/drumkit.py
