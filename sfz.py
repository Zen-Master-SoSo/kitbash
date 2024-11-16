#  kitbash/sfz.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os, logging, re
from appdirs import user_cache_dir
from lark import Lark, Transformer, v_args
from kitbash.opcodes import OPCODES


class _SFZElem:

	_ordinals = {}

	def __init__(self, meta):
		typ = type(self).__name__
		if typ not in _SFZElem._ordinals:
			_SFZElem._ordinals[typ] = 1
		self._idx = _SFZElem._ordinals[typ]
		_SFZElem._ordinals[typ] += 1
		self.line = meta.line
		self.column = meta.column
		self.end_line = meta.end_line
		self.end_column = meta.end_column
		self._parent = None

	@property
	def parent(self):
		return self._parent

	@parent.setter
	def parent(self, parent):
		self._parent = parent

	def sfz(self):
		elem = self
		while not isinstance(elem, SFZ):
			elem = elem.parent
		return elem


class _Header(_SFZElem):

	def __init__(self, toks, meta):
		super().__init__(meta)
		self.subheaders = []
		self._opcodes = {}

	def may_contain(self, header):
		return False

	def append_opcode(self, opcode):
		assert(isinstance(opcode, Opcode))
		self._opcodes[opcode.name] = opcode
		opcode.parent = self

	def append_subheader(self, subheading):
		self.subheaders.append(subheading)
		subheading.parent = self

	def inherited_opcodes(self):
		return dict(self._opcodes, **self._parent.inherited_opcodes())

	def regions(self):
		for sub in self.subheaders:
			if isinstance(sub, Region):
				yield sub
			yield from sub.regions()

	def opcode(self, name):
		return self._opcodes[name] if name in self._opcodes \
			else None if self._parent is None \
			else self._parent.opcode(name)

	@property
	def opcodes(self):
		return self._opcodes

	@property
	def subheadings(self):
		return self.subheaders

	def __repr__(self):
		return '%-4d %s #%s (%d opcodes)' % (self.line, type(self).__name__, self._idx, len(self._opcodes))

	def write(self, stream):
		stream.write('<%s>\n' % type(self).__name__.lower())
		opcodes = self._opcodes.values()
		if opcodes:
			for op in self._opcodes.values():
				op.write(stream)
			stream.write("\n")
		if self.subheaders:
			for sub in self.subheaders:
				sub.write(stream)


class _Modifier(_SFZElem):
	pass


class Global(_Header):

	def may_contain(self, header):
		return True


class Master(_Header):

	def may_contain(self, header):
		return type(header) not in [Global, Master]


class Group(_Header):

	def may_contain(self, header):
		return type(header) not in [Global, Master, Group]


class Region(_Header):

	def may_contain(self, header):
		return type(header) not in [Global, Master, Group, Region]

	def is_triggerd_by(self, lokey=None, hikey=None, lovel=None, hivel=None):
		if lokey is None and hikey is None and lovel is None and hivel is None:
			raise Exception('Requires a key or velocity to filter by')
		ops = self.inherited_opcodes()
		if 'lokey' in ops and lokey is not None and ops['lokey'].value > lokey:
			return False
		if 'hikey' in ops and hikey is not None and ops['hikey'].value < hikey:
			return False
		if 'lovel' in ops and lovel is not None and ops['lovel'].value > lovel:
			return False
		if 'hivel' in ops and hivel is not None and ops['hivel'].value < hivel:
			return False
		return True


class Control(_Header):
	pass


class Effect(_Header):
	pass


class Midi(_Header):
	pass


class Curve(_Header):

	curve_index = None
	points = {}

	def __repr__(self):
		return '%-4d %s #%s curve_index %s (%d points)' % \
			(self.line, type(self).__name__, self._idx, self.curve_index, len(self.points))

	def write(self, stream):
		stream.write('<%s>curve_index=%s\n' % (type(self).__name__.lower(), self.curve_index))
		for vals in self.points.items():
			stream.write('%s=%s\n' % vals)


class Opcode(_SFZElem):

	def __init__(self, name, value, meta):
		super().__init__(meta)
		self.name = name
		self.value = value
		self._parsed_value = value
		odef = OPCODES[self.name] \
			if self.name in OPCODES \
			else self._get_opcode_def(self.name)
		if odef is None or 'value' not in odef:
			self.unit = None
			self.type = None
			self.valid = None
		else:
			self.unit = odef['value']['unit'] if 'unit' in odef['value'] else None
			self.type = odef['value']['type'] if 'type' in odef['value'] else None
			self.valid = odef['value']['valid'] if 'valid' in odef['value'] else None
		if self.type == 'float':
			self.value = float(self.value)
		elif self.type == 'integer':
			self.value = int(self.value)

	def _get_opcode_def(self, name):
		if re.match(r'amp_velcurve_(\d+)', name):
			return 'amp_velcurve_N'
		if re.search(r'eq\d+_', name):
			name = re.sub(r'eq\d+_', 'eqN_', name)
			if name in OPCODES:
				return OPCODES[name]
			if re.search(r'cc\d', name):
				for regex, repl in {
					r'_oncc(\d+)'	: '_onccX',
					r'_cc(\d+)'		: '_ccX',
					r'cc(\d+)'		: 'ccX'
				}.items():
					sub = re.sub(regex, repl, name)
					if sub != name and sub in OPCODES:
						return OPCODES[sub]
		if re.search(r'cc\d', name):
			for regex, repl in {
				r'_oncc(\d+)'	: '_onccN',
				r'_cc(\d+)'		: '_ccN',
				r'cc(\d+)'		: 'ccN'
			}.items():
				sub = re.sub(regex, repl, name)
				if sub != name:
					# Recurse for opcodes like "eq3_gain_oncc12"
					return OPCODES[sub] if sub in OPCODES else self._get_opcode_def(sub)
		logging.warning('Could not find opcode ' + name)

	def __repr__(self):
		return '%-4d opcode #%d: "%s" = %s' % (self.line, self._idx, self.name, repr(self.value))

	def write(self, stream):
		stream.write('%s=%s\n' % (self.name, self._parsed_value))


class Define(_Modifier):

	def __init__(self, varname, value, meta):
		super().__init__(meta)
		self.varname = varname
		self.value = value

	def __repr__(self):
		return '%-4d define #%d: %s = %s' % (self.line, self._idx, self.varname, self.value)


class Include(_Modifier):

	def __init__(self, path, meta):
		super().__init__(meta)
		self.path = path

	def __repr__(self):
		return '%-4d include #%d: %s' % (self.line, self._idx, self.path)


class SFZXformer(Transformer):

	def __init__(self, sfz):
		self.sfz = sfz
		self.current_header = self.sfz

	@v_args(meta=True)
	def header(self, toks, meta):
		if toks[0].value == 'region':
			header = Region(toks, meta)
		elif toks[0].value == 'group':
			header = Group(toks, meta)
		elif toks[0].value == 'control':
			header = Control(toks, meta)
		elif toks[0].value == 'global':
			header = Global(toks, meta)
		elif toks[0].value == 'curve':
			header = Curve(toks, meta)
		elif toks[0].value == 'effect':
			header = Effect(toks, meta)
		elif toks[0].value == 'master':
			header = Master(toks, meta)
		elif toks[0].value == 'midi':
			header = Midi(toks, meta)
		while not self.current_header.may_contain(header):
			self.current_header = self.current_header.parent
		self.current_header.append_subheader(header)
		self.current_header = header

	@v_args(meta=True)
	def define_macro(self, toks, meta):
		self.sfz.defines[toks[0].value] = Define(toks[0].value, toks[1].value, meta)

	@v_args(meta=True)
	def include_macro(self, toks, meta):
		include = Include(self.unquote(self.replace_defs(toks[0].value)), meta)
		self.sfz.includes.append(include)
		path = os.path.join(os.path.dirname(self.sfz.filename), include.path)
		if os.path.exists(path):
			logging.debug(f'Including "{path}"')
			try:
				subsfz = SFZ(path)
				for header in subsfz.subheaders:
					while not self.current_header.may_contain(header):
						self.current_header = self.current_header.parent
					self.current_header.append_subheader(header)
					self.current_header = header
				self.sfz.defines = dict(self.sfz.defines, **subsfz.defines)
				self.sfz.includes.extend(subsfz.includes)
			except Exception as e:
				logging.error(f'Failed to include "{path}"')
				logging.error('%s: %s' % (type(e).__name__, str(e))),

	@v_args(meta=True)
	def opcode_exp(self, toks, meta):
		if isinstance(self.current_header, Curve):
			if toks[0] == 'curve_index':
				self.current_header.curve_index = toks[1].value
			else:
				match = re.match(r'v(\d+)', toks[0].value)
				if match:
					self.current_header.points[toks[0].value] = toks[1].value
				else:
					logging.error('Invalid opcode inside velocity curve definition')
		else:
			self.current_header.append_opcode(Opcode(
				self.replace_defs(toks[0].value),
				self.replace_defs(toks[1].value),
				meta))

	@v_args(meta=True)
	def start(self, toks, meta):
		pass

	def replace_defs(self, var):
		return re.sub(r'\$(\w+)', lambda v: self.sfz.defines[v.group(1)].value, var)

	def unquote(self, var):
		for q in ["'", '"']:
			if var[0] == q and var[-1] == q:
				return var[1:-1]
		return var


class SFZ(_Header):

	_parser = None

	def __init__(self, filename):
		if SFZ._parser is None:
			cache_file = os.path.join(user_cache_dir(), 'kitbash')
			grammar = os.path.join(os.path.dirname(__file__), 'res', 'sfz.lark')
			SFZ._parser = Lark.open(grammar, parser='lalr', propagate_positions=True, cache=cache_file)
		#logging.debug(f'Parsing {filename}')
		with open(filename) as f:
			tree = SFZ._parser.parse(f.read() + "\n")
		self.filename = filename
		self._parent = None
		self.defines = {}
		self.includes = []
		self.subheaders = []
		#logging.debug(f'Transforming {filename}')
		xformer = SFZXformer(self)
		xformer.transform(tree)

	def may_contain(self, header):
		return True

	def append_opcode(self, opcode):
		raise Exception("Opcode outside of header")

	def append_subheader(self, subheading):
		self.subheaders.append(subheading)
		subheading.parent = self

	def __repr__(self):
		return 'SFZ "%s"' % os.path.basename(self.filename)

	def inherited_opcodes(self):
		return {}

	def headers(self):
		return self.subheaders

	def regions_for(self, lokey=None, hikey=None, lovel=None, hivel=None):
		for region in self.regions():
			if region.is_triggerd_by(lokey, hikey, lovel, hivel):
				yield region

	def write(self, stream):
		stream.write('// %s\n\n' % self.filename)
		for sub in self.subheaders:
			sub.write(stream)

	def dump(self):
		self._dump(self, 0)

	def _dump(self, obj, indent):
		print('  ' * indent, end="")
		print(repr(obj))
		if isinstance(obj, _Header) or isinstance(obj, SFZ):
			for sub in obj.subheaders:
				self._dump(sub, indent + 1)



#  end kitbash/sfz.py
