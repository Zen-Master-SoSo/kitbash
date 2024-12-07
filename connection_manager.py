#  kitbash/connection_manager.py
#
#  Copyright 2024 liyang <liyang@veronica>
#

import logging
import re
from functools import cached_property
import jacklib
from jacklib.helpers import c_char_p_p_to_list
from jacklib.helpers import get_jack_status_error_string
from PyQt5.QtCore import (
	QRunnable,
	pyqtSignal,
	pyqtSlot
)


class JackConnectionManager(QRunnable):

	instance = None
	client = None

	def __new__(cls):
		if cls.instance is None:
			cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self):
		if self.client is None:
			super().__init__()
			self.connected = True
			self.client_name = 'conn-man'
			logging.debug('Connecting')
			status = jacklib.jack_status_t()
			self.client = jacklib.client_open(self.client_name, jacklib.JackNoStartServer, status)
			if status.value:
				raise JackConnectError(get_jack_status_error_string(status))
			if not self.client:
				raise JackConnectError('No client created')
			name = jacklib.get_client_name(self.client)
			if name is None:
				raise RuntimeError("Could not get JACK client name.")
			else:
				self.client_name = name.decode()
			jacklib.on_shutdown(self.client, self.shutdown_callback, None)
			logging.debug("Client connected, name: %s UUID: %s",
				self.client_name, jacklib.client_get_uuid(self.client))
			jacklib.set_error_function(self.error_callback)
			jacklib.set_port_registration_callback(self.client, self.port_registration_callback, None)
			jacklib.set_port_connect_callback(self.client, self.port_connect_callback, None)
			jacklib.set_port_rename_callback(self.client, self.port_rename_callback, None)
			jacklib.set_xrun_callback(self.client, self.xrun_callback, None)
			jacklib.activate(self.client)

	def error_callback(self, error):
		error = error.decode(jacklib.ENCODING, errors='ignore')
		logging.debug(error)

	def port_registration_callback(self, port_id, action, *args):
		port = self.get_port_by_id(port_id)
		logging.debug("%s %s", port, 'register' if action else 'gone')

	def port_connect_callback(self, port_a_id, port_b_id, connect, *args):
		port_a = jacklib.port_by_id(self.client, port_a_id)
		port_b = jacklib.port_by_id(self.client, port_b_id)
		port_a_name = jacklib.port_name(port_a)
		port_b_name = jacklib.port_name(port_b)
		logging.debug("New port connection: '%s' -> '%s'", port_a_name, port_b_name)

	def port_rename_callback(self, port_id, old_name, new_name, *args):
		old_name = old_name.decode(jacklib.ENCODING, errors='ignore') if old_name else 'NO_OLD_NAME'
		new_name = new_name.decode(jacklib.ENCODING, errors='ignore') if new_name else 'NO_OLD_NAME'
		logging.debug("Port name %s changed to %s.", old_name, new_name)

	def xrun_callback(self, millis):
		logging.debug("Xrun '%d' millis", millis)

	def shutdown_callback(self, *args):
		logging.debug("JACK server signalled shutdown.")
		self.client = None
		self.queue.put(None)

	def get_port_by_name(self, name):
		ptr = jacklib.port_by_name(self.client, name)
		return JackPort(ptr, name)

	def get_port_by_id(self, port_id):
		ptr = jacklib.port_by_id(self.client, port_id)
		return JackPort(ptr, jacklib.port_name(ptr))

	def get_connections(self, ports = None):
		if ports is None:
			ports = (p[0] for p in self.get_ports())
		for port_name in ports:
			port = jacklib.port_by_name(self.client, port_name)
			if port and jacklib.port_connected(port):
				for other in jacklib.port_get_all_connections(self.client, port):
					yield((port_name, other))

	def list_connections(self):
		for outport, inport in self.get_connections():
			print("%s\n    %s\n" % (outport, inport))

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

	def get_ports(self, flags = 0):
		return [
			self.get_port_by_name(name) \
			for name in c_char_p_p_to_list(
				jacklib.get_ports(self.client, '', '', flags))
		]

	def pysical_input_ports(self):
		return self.get_ports(jacklib.JackPortIsInput | jacklib.JackPortIsPhysical)

	def pysical_output_ports(self):
		return self.get_ports(jacklib.JackPortIsOutput | jacklib.JackPortIsPhysical)

	def close(self):
		if self.client:
			jacklib.deactivate(self.client)
			jacklib.client_close(self.client)


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

	def __str__(self):
		return '<JackPort "{}" ({}, {})>'.format(
			self.name,
			'physical' if self.is_physical else 'plugin',
			'input'if self.is_input else 'output'
		)



class JackConnectError(RuntimeError):
	pass


#  end kitbash/connection_manager.py
