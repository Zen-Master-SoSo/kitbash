#  kitbash/connection_manager.py
#
#  Copyright 2024 liyang <liyang@veronica>
#

import logging
from functools import cached_property
from queue import Queue
import jacklib
from jacklib.helpers import c_char_p_p_to_list
from jacklib.helpers import get_jack_status_error_string
from PyQt5.QtCore import (
	QObject,
	pyqtSignal
)

class JackPort:

	def __init__(self, ptr, name):
		self.ptr = ptr
		self.name = name

	@cached_property
	def aliases(self):
		num_aliases, *aliases = jacklib.port_get_aliases(self.ptr)
		return list(aliases[:num_aliases])

	@cached_property
	def flags(self):
		return jacklib.port_flags(self.ptr)

	@cached_property
	def is_physical(self):
		return self.flags & jacklib.JackPortIsPhysical

	@cached_property
	def is_input(self):
		return self.flags & jacklib.JackPortIsInput

	@cached_property
	def is_output(self):
		return self.flags & jacklib.JackPortIsOutput

	@property
	def client_name(self):
		return self._split_name[0]

	@property
	def port_name(self):
		return self._split_name[1]

	@cached_property
	def type(self):
		return jacklib.port_type(self.ptr)

	@property
	def is_midi(self):
		return 'midi' in self.type

	@property
	def is_audio(self):
		return 'audio' in self.type

	@cached_property
	def _split_name(self):
		try:
			return self.name.split(':', 1)
		except ValueError:
			return ('[error]', '[error]')

	def __str__(self):
		return '<JackPort "{}" ({}, {})>'.format(
			self.name,
			'physical' if self.is_physical else 'plugin',
			'input'if self.is_input else 'output'
		)


class JackConnectError(RuntimeError):
	pass


class JackConnectionManager(QObject):

	sig_error = pyqtSignal(str)
	sig_port_registration = pyqtSignal(JackPort, int)
	sig_port_connect = pyqtSignal(JackPort, JackPort, bool)
	sig_port_rename = pyqtSignal(JackPort, str, str)
	sig_shutdown = pyqtSignal()

	instance = None
	client = None

	# ------------------------------
	# Lifecycle funcs

	def __new__(cls):
		if cls.instance is None:
			cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self):
		if self.client is None:
			super().__init__()
			self.connected = True
			self.client_name = 'conn-man'
			status = jacklib.jack_status_t()
			self.client = jacklib.client_open(self.client_name, jacklib.JackNoStartServer, status)
			if status.value:
				raise JackConnectError(get_jack_status_error_string(status))
			if not self.client:
				raise JackConnectError('No client created')
			name = jacklib.get_client_name(self.client)
			if name is None:
				raise RuntimeError("Could not get JACK client name.")
			self.client_name = name.decode()
			self.queue = Queue()
			self.xruns = 0
			jacklib.on_shutdown(self.client, self.shutdown_callback, None)
			logging.debug('ConnectionManager client "%s" created', self.client_name)
			jacklib.set_error_function(self.error_callback)
			jacklib.set_port_registration_callback(self.client, self.port_registration_callback, None)
			jacklib.set_port_connect_callback(self.client, self.port_connect_callback, None)
			jacklib.set_port_rename_callback(self.client, self.port_rename_callback, None)
			jacklib.set_xrun_callback(self.client, self.xrun_callback, None)
			jacklib.activate(self.client)

	def close(self):
		if self.client:
			jacklib.deactivate(self.client)
			jacklib.client_close(self.client)

	# ------------------------------
	# Callbacks

	def error_callback(self, error):
		self.sig_error.emit(error.decode(jacklib.ENCODING, errors='ignore'))

	def port_registration_callback(self, port_id, action, *args):
		self.sig_port_registration.emit(self.get_port_by_id(port_id), action)

	def port_connect_callback(self, port_a_id, port_b_id, connect, *args):
		self.sig_port_connect.emit(
			self.get_port_by_id(port_a_id),
			self.get_port_by_id(port_b_id),
			bool(connect)
		)

	def port_rename_callback(self, port_id, old_name, new_name, *args):
		self.sig_port_rename.emit(
			self.get_port_by_id(port_id),
			old_name.decode(jacklib.ENCODING, errors='ignore') if old_name else 'NO_OLD_NAME',
			new_name.decode(jacklib.ENCODING, errors='ignore') if new_name else 'NO_NEW_NAME'
		)

	def xrun_callback(self, arg):
		self.xruns += 1
		return 0

	def shutdown_callback(self, *args):
		self.sig_shutdown.emit()
		self.client = None

	# ------------------------------
	# Port / connection info funcs

	def get_ports(self, flags = 0):
		return [
			self.get_port_by_name(name) \
			for name in c_char_p_p_to_list(
				jacklib.get_ports(self.client, '', '', flags))
		]

	def get_port_by_name(self, name):
		ptr = jacklib.port_by_name(self.client, name)
		return JackPort(ptr, name)

	def get_port_by_id(self, port_id):
		ptr = jacklib.port_by_id(self.client, port_id)
		return JackPort(ptr, jacklib.port_name(ptr))

	def get_connections(self, ports = None):
		if ports is None:
			ports = self.get_ports()
		for port in ports:
			if jacklib.port_connected(port.ptr):
				for port_name in jacklib.port_get_all_connections(self.client, port.ptr):
					yield((port, self.get_port_by_name(port_name)))

	def list_connections(self):
		print('==== CONNECTIONS ====')
		for outport, inport in self.get_connections():
			print("%s\n    %s" % (outport, inport))

	def list_ports(self):
		print('==== INPUT PORTS ====')
		self._list_ports(jacklib.JackPortIsInput)
		print('==== OUTPUT PORTS ====')
		self._list_ports(jacklib.JackPortIsOutput)

	def _list_ports(self, flags):
		for port in self.get_ports(flags):
			print(port.name, end = "")
			if port.aliases:
				print('; alias "' + '", "'.join(port.aliases) + '"', end = '')
			print()

	def physical_input_ports(self):
		return self.get_ports(jacklib.JackPortIsInput | jacklib.JackPortIsPhysical)

	def physical_output_ports(self):
		return self.get_ports(jacklib.JackPortIsOutput | jacklib.JackPortIsPhysical)

	def playback_clients(self):
		return list(set([port.client_name \
			for port in self.get_ports(jacklib.JackPortIsInput | jacklib.JackPortIsPhysical) \
			if not port.is_midi]))

	def connect(self, outport, inport):
		#logging.debug('Connecting %s -> %s', outport.name, inport.name)
		jacklib.connect(self.client, outport.name, inport.name)

#  end kitbash/connection_manager.py
