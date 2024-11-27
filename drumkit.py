#  kitbash/drumkit.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
from os import path
from midi_notes import Note, MIDI_DRUM_NAMES, MIDI_DRUM_IDS
from kitbash.sfz import SFZ


class PercussionInstrument:

	def __init__(self, pitch):
		self.note = Note(pitch)
		self.inst_id = MIDI_DRUM_IDS[pitch]
		self.name = MIDI_DRUM_NAMES[pitch]
		self._regions = []

	def import_regions_from(self, sfz):
		self._regions.extend(list(sfz.regions_for(lokey=self.note.pitch, hikey=self.note.pitch)))

	@property
	def pitch(self):
		return self.note.pitch

	def empty(self):
		return len(self._regions) == 0

	def write(self, stream):
		stream.write(f'// "{self.name}"\n')
		stream.write(f'// MIDI pitch: {self.note.pitch}  Note name: {self.note}\n\n')
		for region in self._regions:
			region.write(stream)


class PercussionGroup:

	def __init__(self, group_id, pitches):
		self.group_id = group_id
		self.name = group_id.replace('_', ' ').title()
		self.instruments = { pitch:PercussionInstrument(pitch) for pitch in pitches }

	def import_regions_from(self, sfz):
		for inst in self.instruments.values():
			inst.import_regions_from(sfz)

	def empty(self):
		for inst in self.instruments.values():
			if not inst.empty():
				return False
		return True

	def write(self, stream):
		stream.write(f'\n// Percussion group "{self.name}"\n\n')
		for inst in self.instruments.values():
			if not inst.empty():
				inst.write(stream)


class Drumkit:

	defs = {
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

	def __init__(self, filename=None):
		self.percussion_groups = [ PercussionGroup(group_id, pitches) for group_id, pitches in Drumkit.defs.items() ]
		self.filename = filename
		self.name = path.basename(filename)
		if self.filename is not None:
			sfz = SFZ(self.filename)
			for group in self.percussion_groups:
				group.import_regions_from(sfz)

	def write(self, stream):
		stream.write(f'// ----------------------------------------\n//   {self.name}\n// ----------------------------------------\n\n')
		for group in self.percussion_groups:
			if not group.empty():
				group.write(stream)

	def __str__(self):
		return f"<Drumkit {self.filename}>"


#  end kitbash/drumkit.py
