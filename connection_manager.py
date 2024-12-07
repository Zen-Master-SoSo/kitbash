#  kitbash/connection_manager.py
#
#  Copyright 2024 liyang <liyang@veronica>
#

import logging
import queue
import re
import jacklib
from jacklib.helpers import c_char_p_p_to_list
from jacklib.helpers import get_jack_status_error_string
from PyQt5.QtCore import QRunnable
from PyQt5.QtCore import pyqtSlot


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
			self.stay_alive = True
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
			else:
				self.client_name = name.decode()
			jacklib.on_shutdown(self.client, self.shutdown_callback, None)
			logging.debug("Client connected, name: %s UUID: %s",
				self.client_name, jacklib.client_get_uuid(self.client))
			jacklib.set_error_function(self.error_callback)
			jacklib.set_port_registration_callback(self.client, self.port_registration_callback, None)
			jacklib.set_port_connect_callback(self.client, self.port_connect_callback, None)
			jacklib.set_port_rename_callback(self.client, self.port_rename_callback, None)
			jacklib.set_property_change_callback(self.client, self.property_change_callback, None)
			jacklib.activate(self.client)
			self.queue = queue.Queue()

	def error_callback(self, error):
		error = error.decode(jacklib.ENCODING, errors='ignore')
		logging.debug(error)

	def port_registration_callback(self, port_id, action, *args):
		port = jacklib.port_by_id(self.client, port_id)
		logging.debug("Port registration: %s %s", jacklib.port_name(port), action)

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

	def property_change_callback(self, subject, name, type_, *args):
		name = name.decode(jacklib.ENCODING, errors='ignore') if name else 'NO_NAME'
		logging.debug("Property '%s' on subject %s %s.", name, subject, PROPERTY_CHANGE_MAP[type_])

	def shutdown_callback(self, *args):
		logging.debug("JACK server signalled shutdown.")
		self.client = None
		self.queue.put(None)

	def _refresh(self):
		inputs = list(flatten(self.get_ports(jacklib.JackPortIsInput)))
		outputs = list(flatten(self.get_ports(jacklib.JackPortIsOutput)))

	def _get_port_by_name(self, name):
		return JackPort(jacklib.port_by_name(self.client, name), name)

	def _get_aliases(self, port_name):
		port = self._get_port_by_name(port_name)
		num_aliases, *aliases = jacklib.port_get_aliases(port)
		return list(aliases[:num_aliases])

	def get_ports(self, direction = jacklib.JackPortIsOutput):
		return c_char_p_p_to_list(jacklib.get_ports(self.client, '', '', direction))

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

	def list_ports(self, direction = jacklib.JackPortIsOutput):
		for port_name in self.get_ports(direction):
			port = self._get_port_by_name(port_name)
			print(port.name, end = "")
			pretty_name = port.pretty_name()
			if pretty_name:
				print('; pretty_name: "' + '", "'.join(pretty_name) + '"', end = '')
			aliases = port.aliases()
			if aliases:
				print('; alias "' + '", "'.join(aliases) + '"', end = '')
			print()

	def _format_ports(self, ports):
		out = []
		for output in ports:
			out.append(output[0])
			for alias in output[1:]:
				if isinstance(alias, tuple):
					alias = alias[1]
				out.append("    %s" % alias)
		return "\n".join(out)

	@pyqtSlot()
	def run(self):
		while self.stay_alive:
			tup = self.queue.get()
			if tup is None:
				break
			(srcport, dstport) = tup
			port = self._get_port_by_name(srcport)
			if port:
				flags = jacklib.port_flags(port)
				if flags & jacklib.JackPortIsInput:
					to_connect = [(p, dstport) for _, p in self.get_connections([srcport])]
				else:
					to_connect = [(srcport, dstport)]
				for outport, inport in to_connect:
					port = self._get_port_by_name(outport)
					if not port:
						continue
					if not jacklib.port_connected_to(port, inport):
						logging.info("Connecting ports: '%s' --> '%s'.", outport, inport)
						self.connection_cache[(outport, inport)] = True
						jacklib.connect(self.client, outport, inport)
					else:
						logging.debug("Ports already connected: '%s' --> '%s'.", outport, inport)
			else:
				logging.warning("Port vanished: %s", srcport)

	def quit(self):
		self.stay_alive = False
		self.queue.put(None)

	def close(self):
		if self.client:
			jacklib.deactivate(self.client)
			jacklib.client_close(self.client)


class JackPort:

	def __init__(self, lp_jack_port, name):
		self.lp_jack_port = lp_jack_port
		self.name = name

	def aliases(self):
		num_aliases, *aliases = jacklib.port_get_aliases(self.lp_jack_port)
		return list(aliases[:num_aliases])

	def pretty_name(self):
		pretty_name = jacklib.get_port_pretty_name(JackConnectionManager(), self.lp_jack_port)
		if pretty_name:
			try:
				client, port = port_name.split(':', 1)
			except ValueError:
				pass
			else:
				return client + ':' + pretty_name


class JackConnectError(RuntimeError):
	pass


#  end kitbash/connection_manager.py
