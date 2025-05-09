#  kitbash/gui.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys, os, argparse, logging, json, glob
from collections import deque
from tempfile import mkstemp
from functools import partial
from signal import signal, SIGINT, SIGTERM
from recent_items_list import RecentItemsList
from qt_extras import ShutUpQT, DevilBox
from qt_extras.list_layout import VListLayout
from midi_notes import MIDI_DRUM_PITCHES
from liquiphy import LiquidSFZ
from jack_connection_manager import JackConnectionManager, JackPort, JackConnectError
from jack_midi_split import MidiSplitter

# PyQt5 imports
from PyQt5 import uic
from PyQt5.QtCore import	Qt, pyqtSignal, pyqtSlot, QObject, QTimer, \
							QSettings, QThreadPool, QRunnable, QPoint
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, \
							QAction, QActionGroup, QMenu, QSizePolicy

from kitbash import settings, APPLICATION_NAME, PACKAGE_DIR, SAMPLES_SYMLINK, SAMPLES_ABSPATH
from kitbash.drumkit import Drumkit
from kitbash.drumkit_widget import DrumkitWidget
from kitbash.icons import PIXMAP_AUDIO_OFF, PIXMAP_AUDIO_ON


class MainWindow(QMainWindow):

	instance = None
	initialized = False
	sig_ports_complete = pyqtSignal(QObject)

	def __new__(cls):
		if cls.instance is None:
			cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self):
		if self.initialized:
			return
		super().__init__()
		self.initialized = True
		with ShutUpQT():
			uic.loadUi(os.path.join(PACKAGE_DIR, 'res', 'main_window.ui'), self)
		#self.setWindowIcon(QIcon(os.path.join(PACKAGE_DIR, 'res', 'icon.png')))
		geometry = settings().value("geometry")
		if geometry is not None:
			self.restoreGeometry(geometry)
		self.recent_projects = RecentItemsList(settings().value("recent_projects", defaultValue=[]))
		self.recent_drumkits = RecentItemsList(settings().value("recent_drumkits", defaultValue=[]))
		self.sfz_filename = None
		self.project_file = None
		self.project_definition = None
		self.project_clearing = False
		self.project_loading = False
		self.bashed_kit = None
		self.saved_sfz_filename = None
		self.dirty = False
		self.synth = None
		self.drumkit_port_ranges = set( port_number for port_number in range(16) )
		self.synth_creation_queue = deque()
		self.new_synth = None
		self.current_midi_source = None
		self.current_audio_sink = None
		self.audio_sink_ports = []
		self.base_xruns = self.current_xruns = 0
		self.b_xruns.setText('0')
		self.fill_style_menu()
		self.load_current_style()
		self.setup_window_elements()
		self.connect_actions()
		# Setup KitLoader threadpool
		self.background_threadpool = QThreadPool()
		self.background_threadpool.setMaxThreadCount(16)
		# Setup connection manager and synth creation pool
		self.conn_man = JackConnectionManager()
		self.conn_man.on_error(self.jack_error)
		self.conn_man.on_xrun(self.jack_xrun)
		self.conn_man.on_shutdown(self.jack_shutdown)
		self.conn_man.on_client_registration(self.jack_client_registration)
		self.conn_man.on_port_registration(self.jack_port_registration)
		# Fill sink/source menus:
		self.fill_cmb_sources()
		self.fill_cmb_sinks()
		# Setup signals
		self.sig_ports_complete.connect(self.slot_ports_complete)
		self.cmb_midi_srcs.currentTextChanged.connect(self.slot_midi_src_changed)
		self.cmb_audio_sinks.currentTextChanged.connect(self.slot_audio_sink_changed)
		# Setup MidiSplitter
		self.midi_splitter = MidiSplitter('kitbash')
		self.splitter_assignments = [ None for i in range(16) ]
		# Setup signals
		signal(SIGINT, self.system_signal)
		signal(SIGTERM, self.system_signal)
		# Allow Qt event loop to process layout ...
		QTimer.singleShot(0, self.layout_complete)

	def layout_complete(self):
		self.instantiate_synth(self)

	def setup_window_elements(self):
		self.lbl_audio_indicator.setPixmap(PIXMAP_AUDIO_OFF())
		self.drumkit_widgets = VListLayout(end_space = 10)
		self.drumkit_widgets.setContentsMargins(0,0,0,0)
		self.drumkit_widgets.setSpacing(2)
		self.kits_area.setLayout(self.drumkit_widgets)

	def connect_actions(self):
		self.action_collapse_kits.triggered.connect(self.slot_collapse_kits)
		self.action_collapse_kits.setEnabled(False)
		self.action_collapse_kits.setChecked(False)
		self.action_new_project.triggered.connect(self.slot_new_project)
		self.action_open_project.triggered.connect(self.slot_open_project)
		self.action_save_project.triggered.connect(self.slot_save_project)
		self.action_save_bashed_kit.triggered.connect(self.slot_save_bashed_kit)
		self.action_load_kit.triggered.connect(self.slot_load_kit)
		self.action_reload_style.triggered.connect(self.load_current_style)
		self.menu_RecentProject.aboutToShow.connect(self.slot_show_recent_projects)
		self.menu_RecentDrumkits.aboutToShow.connect(self.slot_show_recent_drumkits)
		self.kits_area.setContextMenuPolicy(Qt.CustomContextMenu)
		self.kits_area.customContextMenuRequested.connect(self.slot_kits_context_menu)
		self.b_preview.toggled.connect(self.slot_preview_toggle)
		self.b_xruns.clicked.connect(self.slot_xruns_clicked)

	# -----------------------------------------------------------------
	# Style functions:

	def fill_style_menu(self):
		"""
		Fill a style menu with the list of discovered styles
		(see discover styles)
		"""
		self._styles = { '.'.join(os.path.basename(path).split('.')[:-1]): path \
						for path in glob.glob(os.path.join(PACKAGE_DIR, 'styles', '*.css')) }
		current_style = settings().value("style")
		actions = QActionGroup(self)
		actions.setExclusive(True)
		for style_name in self._styles:
			action = QAction(style_name, self)
			action.triggered.connect(partial(self.select_style, style_name))
			action.setCheckable(True)
			action.setChecked(style_name == current_style)
			actions.addAction(action)
			self.menu_Style.addAction(action)

	def select_style(self, style):
		"""
		Selects a named style and saves selection in settings.
		"""
		settings().setValue('style', style)
		self.load_current_style()

	@pyqtSlot(bool)
	def load_current_style(self):
		"""
		Loads (or reloads) the current style defined in settings.
		"""
		style = settings().value("style", "system")
		with open(self._styles[style], 'r') as cssfile:
			QApplication.instance().setStyleSheet(cssfile.read())

	# -----------------------------------------------------------------
	# Project loading / saving:

	def set_dirty(self, state = True):
		if not self.project_loading:
			self.dirty = state
			title = APPLICATION_NAME \
				if self.project_file is None \
				else f"{self.project_file} [{APPLICATION_NAME}]"
			self.setWindowTitle("* " + title if self.dirty else title)

	def compile_project_def(self):
		return {
			widget.sfz_filename : widget.saved_selections() \
			for widget in self.drumkit_widgets
		}

	def load_project(self, filename):
		if os.path.exists(filename):
			logging.debug('LOADING PROJECT "%s"', filename)
			self.project_file = filename
			if self.is_clear():
				self.execute_project_load()
			else:
				self.project_clearing = True
				self.clear()
		else:
			self.recent_projects.remove(filename)
			settings().setValue("recent_projects", self.recent_projects.items)
			DevilBox(f"Project not found: {filename}")

	def save_project(self):
		with open(self.project_file, 'w') as fh:
			json.dump(self.compile_project_def(), fh, indent="\t")
		self.register_recent_project()
		self.set_dirty(False)

	def register_recent_project(self):
		self.recent_projects.select(self.project_file)
		settings().setValue("recent_project_folder", os.path.dirname(self.project_file))
		settings().setValue("recent_projects", self.recent_projects.items)

	def is_clear(self):
		return len(self.drumkit_widgets) == 0

	def permission_to_clear(self):
		if self.is_clear():
			return True
		dlg = QMessageBox(
			QMessageBox.Warning,
			"Verify clear all",
			"Are you sure you want to remove everything and start new?",
			QMessageBox.Ok | QMessageBox.Cancel,
			self
		)
		return dlg.exec() == QMessageBox.Ok

	def clear(self):
		logging.debug('CLEARING')
		for widget in reversed(self.drumkit_widgets):
			self.slot_remove_drumkit(widget)

	def execute_project_load(self):
		self.project_clearing = False
		self.project_loading = True
		try:
			with open(self.project_file, 'r') as fh:
				self.project_definition = json.load(fh)
		except json.JSONDecodeError as e:
			DevilBox('There was a problem decoding:\n' +
				f'"{self.project_file}"\n' + \
				f'"{e}"\n' + \
				'Are you sure it is a kitbash project?')
		else:
			self.register_recent_project()
			for filename in self.project_definition.keys():
				self.load_drumkit(filename)

	def check_project_load_complete(self):
		"""
		Determine if project loading is complete, reset "self.project_loading".
		Returns True if complete
		"""
		if any(drumkit_widget.drumkit is None for drumkit_widget in self.drumkit_widgets):
			return False
		self.project_loading = False
		self.set_dirty(False)
		return True

	# -----------------------------------------------------------------
	# Source / sink combo boxes

	def fill_cmb_sources(self):
		self.cmb_midi_srcs.addItem('')
		for port in self.conn_man.output_ports():
			if port.is_midi:
				self.cmb_midi_srcs.addItem(port.name)

	def fill_cmb_sinks(self):
		items = ['']
		items.extend(self.conn_man.physical_playback_clients())
		self.cmb_audio_sinks.addItems(items)

	@pyqtSlot(str)
	def slot_midi_src_changed(self, value):
		if self.current_midi_source:
			self.conn_man.disconnect_by_name(self.current_midi_source, self.midi_splitter.input_port.name)
			self.conn_man.disconnect_by_name(self.current_midi_source, self.synth.input_port.name)
		self.current_midi_source = value
		if self.current_midi_source:
			self.conn_man.connect_by_name(self.current_midi_source, self.midi_splitter.input_port.name)
			self.conn_man.connect_by_name(self.current_midi_source, self.synth.input_port.name)

	@pyqtSlot(str)
	def slot_audio_sink_changed(self, value):
		my_client_names = [ self.synth.client_name ] if self.synth else []
		for drumkit_widget in self.drumkit_widgets:
			my_client_names.append(drumkit_widget.client_name)
		if self.current_audio_sink:
			for audio_sink_port in self.audio_sink_ports:
				for src_port in self.conn_man.get_port_connections(audio_sink_port):
					if src_port.client_name in my_client_names:
						self.conn_man.disconnect(src_port, audio_sink_port)
		self.current_audio_sink = value
		if self.current_audio_sink:
			self.audio_sink_ports = [ port for port \
				in self.conn_man.physical_input_ports() \
				if port.client_name == self.current_audio_sink ]
			if self.synth:
				self.connect_audio_sink(self.synth)
			for drumkit_widget in self.drumkit_widgets:
				self.connect_audio_sink(drumkit_widget.synth)
		else:
			self.audio_sink_ports = []

	def connect_midi_source(self, synth):
		if self.current_midi_source:
			self.conn_man.connect_by_name(self.current_midi_source, synth.input_port.name)

	def connect_audio_sink(self, synth):
		for src,tgt in zip(synth.output_ports, self.audio_sink_ports):
			self.conn_man.connect(src, tgt)

	# -----------------------------------------------------------------
	# Synth / port management

	def instantiate_synth(self, associated_object):
		self.synth_creation_queue.append(associated_object)
		if self.new_synth is None:
			self.start_new_synth()

	def start_new_synth(self):
		self.new_synth = JackLiquidSFZ(self.synth_creation_queue[0].sfz_filename)
		self.new_synth.start()

	def jack_error(self, error_message):
		logging.error('JACK ERROR: %s', error_message)

	def jack_xrun(self, xruns):
		self.b_xruns.setText(str(xruns - self.base_xruns))
		self.current_xruns = xruns

	def jack_shutdown(self):
		logging.error('JACK is shutting down')
		self.close()

	def jack_client_registration(self, client_name, action):
		logging.debug('Client "%s" %s', client_name, 'registered' if action else 'gone')
		if action and self.new_synth and 'liquidsfz' in client_name:
			self.new_synth.client_name = client_name

	def jack_port_registration(self, port, action):
		logging.debug('Port "%s" %s', port, 'registered' if action else 'gone')
		if action and \
			self.new_synth and \
			self.new_synth.client_name and \
			self.new_synth.client_name in port.name:
			if port.is_input and port.is_midi:
				self.new_synth.input_port = port
			elif port.is_output and port.is_audio:
				self.new_synth.output_ports.append(port)
			else:
				logging.error('Incorrect port type: %s', port)
			if self.new_synth.input_port and len(self.new_synth.output_ports) == 2:
				logging.debug('%s ports complete', self.new_synth.client_name)
				associated_object = self.synth_creation_queue.popleft()
				associated_object.synth = self.new_synth
				if len(self.synth_creation_queue):
					self.start_new_synth()
				else:
					self.new_synth = None
				self.sig_ports_complete.emit(associated_object)

	@pyqtSlot(QObject)
	def slot_ports_complete(self, associated_object):
		self.connect_audio_sink(associated_object.synth)
		if isinstance(associated_object, DrumkitWidget):
			src = self.midi_splitter.output_ports[associated_object.port_number].name
			tgt = associated_object.synth.input_port.name
			logging.debug('Connecting %s to %s', src, tgt)
			self.conn_man.connect_by_name(src, tgt)
		else:
			self.connect_midi_source(associated_object.synth)

	# -----------------------------------------------------------------
	# Drumkit load / delete / instrument selection

	def load_drumkit(self, filename):
		if os.path.exists(filename):
			drumkit_widget = DrumkitWidget(filename, self)
			self.drumkit_widgets.append(drumkit_widget)
			available_ports = self.available_port_numbers()
			if len(available_ports):
				drumkit_widget.port_number = list(available_ports)[0]
			else:
				DevilBox('Not enough ports (Maximum 16)')
			drumkit_widget.sig_inst_toggle.connect(self.slot_inst_toggle)
			drumkit_widget.sig_remove_drumkit.connect(self.slot_remove_drumkit)
			self.instantiate_synth(drumkit_widget)
			worker = KitLoader(drumkit_widget)
			worker.signals.sig_loaded.connect(drumkit_widget.slot_drumkit_loaded)
			worker.signals.sig_widget_loaded.connect(self.slot_drumkit_widget_loaded)
			self.background_threadpool.start(worker)
			self.recent_drumkits.select(filename)
			settings().setValue("recent_drumkit_folder", os.path.dirname(filename))
			self.set_dirty()
		else:
			self.recent_drumkits.remove(filename)
			DevilBox(f"File not found: {filename}")
		settings().setValue("recent_drumkits", self.recent_drumkits.items)

	@pyqtSlot(DrumkitWidget)
	def slot_drumkit_widget_loaded(self, drumkit_widget):
		"""
		Called when KitLoader is finshed loading and interpreted SFZ.
		"""
		self.action_collapse_kits.setEnabled(True)
		if self.project_loading and drumkit_widget.port_number:
			drumkit_widget.apply_selections(self.project_definition[drumkit_widget.sfz_filename])
			self.check_project_load_complete()
		elif len(self.drumkit_widgets) == 1:
			drumkit_widget.select_all()
			self.midi_splitter.assign_all_notes(drumkit_widget.port_number)
			self.b_preview.setEnabled(True)

	@pyqtSlot(QObject)
	def slot_remove_drumkit(self, drumkit_widget):
		self.midi_splitter.clear_port_assignments(drumkit_widget.port_number)
		drumkit_widget.synth.quit()
		self.drumkit_widgets.remove(drumkit_widget)
		drumkit_widget.deleteLater()
		self.set_dirty()

	@pyqtSlot(QObject, str, bool, bool)
	def slot_inst_toggle(self, source_widget, inst_id, state, ctrl_state):
		"""
		Triggered by DrumkitWidget InstrumentButton toggle event.
		Parameters are:
			"source_widget": DrumkitWidget containing button clicked
			"inst_id": From the button that was clicked
			"state": (bool) True if "checked"
			"ctrl_state": (bool) True if CTRL key pressed when clicking
		"""
		# Deselect all other InstrumentButton if not CTRL key pressed:
		if state and not ctrl_state:
			for drumkit_widget in self.drumkit_widgets:
				if not drumkit_widget is source_widget:
					drumkit_widget.deselect_instrument(inst_id)
		# Deselect the GroupButton if instrument deselected:
		elif not state:
			source_widget.deselect_parent_group(inst_id)
		# Enable/disable routing midi events to the source_widget's synth:
		if state:
			self.midi_splitter.assign_note(
				MIDI_DRUM_PITCHES[inst_id],
				source_widget.port_number)
		else:
			self.midi_splitter.clear_note_assignment(
				MIDI_DRUM_PITCHES[inst_id],
				source_widget.port_number)
		self.b_preview.setEnabled(any(self.midi_splitter.note_assignments.values()))
		self.set_dirty()

	@pyqtSlot(bool)
	def slot_preview_toggle(self, state):
		"""
		Select bashed sfz for play preview; deselect all drumkits.
		"""
		self.midi_splitter.bypassed = state
		if state:
			# Going from no preview to preview state:
			logging.debug('Bashing current kits')
			if self.sfz_filename:
				os.unlink(self.sfz_filename)
			worker = KitBasher(self.drumkit_widgets)
			worker.signals.sig_bashed.connect(self.slot_drumkit_bashed)
			self.background_threadpool.start(worker)
		self.lbl_audio_indicator.setPixmap(PIXMAP_AUDIO_ON() if state else PIXMAP_AUDIO_OFF())

	@pyqtSlot(str)
	def slot_drumkit_bashed(self, filename):
		"""
		Triggered from KitBasher signal when bashing is finished.
		"""
		self.sfz_filename = filename
		self.synth.load(self.sfz_filename)
		logging.debug('Loaded .sfz at %s', self.sfz_filename)

	@pyqtSlot()
	def slot_save_bashed_kit(self):
		dlg = FileSaveDialog(self)
		if dlg.exec_() and dlg.selected_file:
			self.bashed_kit.save_as(dlg.selected_file, dlg.samples_mode)
			self.saved_sfz_filename = dlg.selected_file

	def used_port_numbers(self):
		"""
		Returns a set of MidiSplitter port numbers assigned to drumkit widget's synth
		"""
		return set(drumkit_widget.port_number \
			for drumkit_widget in self.drumkit_widgets\
			if drumkit_widget.synth)

	def available_port_numbers(self):
		"""
		Returns a set of MidiSplitter port numbers not yet assigned to drumkit widget's synth
		"""
		return self.drumkit_port_ranges ^ self.used_port_numbers()

	# -----------------------------------------------------------------
	# QMainWindow overloads (see also: "timerEvent")

	def closeEvent(self, event):
		logging.debug('MainWindow close()')
		self.synth.quit()
		for drumkit_widget in self.drumkit_widgets:
			drumkit_widget.synth.quit()
		if self.sfz_filename and os.path.exists(self.sfz_filename):
			os.unlink(self.sfz_filename)
		settings().setValue("geometry", self.saveGeometry())
		settings().sync()
		event.accept()

	# -----------------------------------------------------------------
	# System signal handler

	def system_signal(self, *_):
		logging.debug('Caught signal - shutting down')
		self.close()

	# -----------------------------------------------------------------
	# UI handling slots:

	@pyqtSlot()
	def slot_xruns_clicked(self):
		self.base_xruns = self.current_xruns
		self.b_xruns.setText('0')

	@pyqtSlot(QPoint)
	def slot_kits_context_menu(self, position):
		menu = QMenu()
		clicked_drumkit_widget = self.kits_area.childAt(position)
		if clicked_drumkit_widget is not None:
			while not isinstance(clicked_drumkit_widget, DrumkitWidget) and \
				clicked_drumkit_widget.parent() is not None:
				clicked_drumkit_widget = clicked_drumkit_widget.parent()
			if isinstance(clicked_drumkit_widget, DrumkitWidget):
				action = QAction(f'Remove "{clicked_drumkit_widget.moniker}"', self)
				action.triggered.connect(partial(self.slot_remove_drumkit, clicked_drumkit_widget))
				menu.addAction(action)
		action = QAction('Add drumkit', self)
		action.triggered.connect(self.slot_load_kit)
		menu.addAction(action)
		if len(self.drumkit_widgets) > 0:
			action = QAction('Remove all drumkits', self)
			action.triggered.connect(self.slot_remove_all_kits)
			menu.addAction(action)
		menu.exec(self.kits_area.mapToGlobal(position))

	@pyqtSlot()
	def slot_remove_all_kits(self):
		for drumkit_widget in reversed(self.drumkit_widgets):
			self.slot_remove_drumkit(drumkit_widget)

	@pyqtSlot()
	def slot_collapse_kits(self):
		for widget in self.drumkit_widgets:
			widget.hide_button.setChecked(True)

	@pyqtSlot()
	def slot_show_recent_drumkits(self):
		"""
		Fills "recent_drumkits" menu before expanding
		"""
		self.menu_RecentDrumkits.clear()
		actions = []
		for filename in self.recent_drumkits:
			action = QAction(filename, self)
			action.triggered.connect(partial(self.load_drumkit, filename))
			actions.append(action)
		self.menu_RecentDrumkits.addActions(actions)

	@pyqtSlot()
	def slot_show_recent_projects(self):
		"""
		Fills "recent_projects" menu before expanding
		"""
		self.menu_RecentProject.clear()
		actions = []
		for filename in self.recent_projects:
			action = QAction(filename, self)
			action.triggered.connect(partial(self.load_project, filename))
			actions.append(action)
		self.menu_RecentProject.addActions(actions)

	@pyqtSlot()
	def slot_new_project(self):
		if self.permission_to_clear():
			self.clear()

	@pyqtSlot()
	def slot_open_project(self):
		if not self.permission_to_clear():
			return
		filename = QFileDialog.getOpenFileName(self,
			"Open saved project",
			settings().value("recent_project_folder", ""),
			"Kitbash project (*.json)"
		)[0]
		if filename != "":
			self.load_project(filename)

	@pyqtSlot()
	def slot_save_project(self):
		if self.project_file is None:
			filename, _ = QFileDialog.getSaveFileName(
				self,
				"Save Kitbash project ...",
				"kitbash.json",
				"Kitbash project (*.json)"
			)
			if filename:
				self.project_file = filename
			else:
				return
		self.save_project()

	@pyqtSlot()
	def slot_load_kit(self):
		filename = QFileDialog.getOpenFileName(self,
			"Load SFZ Drumkit",
			settings().value("recent_drumkit_folder", ""),
			"SFZ file (*.sfz)"
		)[0]
		if filename != "":
			self.load_drumkit(filename)


class KitWorkerSignals(QObject):

	sig_loaded = pyqtSignal(Drumkit)
	sig_widget_loaded = pyqtSignal(DrumkitWidget, Drumkit)
	sig_bashed = pyqtSignal(str)


class KitLoader(QRunnable):

	def __init__(self, drumkit_widget):
		super().__init__()
		self.drumkit_widget = drumkit_widget
		self.signals = KitWorkerSignals()

	@pyqtSlot()
	def run(self):
		drumkit = Drumkit(self.drumkit_widget.sfz_filename)
		self.signals.sig_loaded.emit(drumkit)
		self.signals.sig_widget_loaded.emit(self.drumkit_widget, drumkit)


class KitBasher(QRunnable):


	def __init__(self, drumkit_widgets):
		super().__init__()
		self.drumkit_widgets = drumkit_widgets
		self.signals = KitWorkerSignals()

	@pyqtSlot()
	def run(self):
		bashed_kit = Drumkit()
		for drumkit_widget in self.drumkit_widgets:
			for inst_id in drumkit_widget.selected_instrument_ids():
				bashed_kit.import_instrument(inst_id, drumkit_widget.drumkit)
		_, sfz_filename = mkstemp(prefix='kitbash', suffix='.sfz', text=True)
		bashed_kit.save_as(sfz_filename, SAMPLES_ABSPATH)
		logging.debug('Created .sfz at %s', sfz_filename)


class JackLiquidSFZ(LiquidSFZ):

	def __init__(self, filename):
		self.client_name = None
		self.input_port = None
		self.output_ports = []
		super().__init__(filename, defer_start = True)

# -----------------------------------------------------------------
# main()

def main():

	p = argparse.ArgumentParser()
	p.epilog = """
	Write your help text!
	"""
	p.add_argument('Filename', type=str, nargs='*', help='SFZ file[s] to include at startup')
	p.add_argument("--log-file", "-l", type=str, help="Log to this file")
	p.add_argument("--verbose", "-v", action="store_true", help="Show more detailed debug information")
	options = p.parse_args()

	log_level = logging.DEBUG if options.verbose else logging.ERROR
	log_format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	if options.log_file:
		logging.basicConfig(
			filename = options.log_file,
			filemode = 'w',
			level = log_level,
			format = log_format
		)
	else:
		logging.basicConfig(
			level = log_level,
			format = log_format
		)

	#-----------------------------------------------------------------------
	# Annoyance fix per:
	# https://stackoverflow.com/questions/986964/qt-session-management-error
	try:
		del os.environ['SESSION_MANAGER']
	except KeyError:
		pass
	#-----------------------------------------------------------------------

	app = QApplication([])
	try:
		main_window = MainWindow()
	except JackConnectError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	sys.exit(main())


#  end kitbash/gui.py
