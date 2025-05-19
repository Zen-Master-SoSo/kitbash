#  kitbash/gui.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys, os, argparse, logging, json, glob
from collections import deque
from functools import partial
from signal import signal, SIGINT, SIGTERM
from recent_items_list import RecentItemsList
from qt_extras import ShutUpQT, SigBlock, DevilBox
from qt_extras.list_layout import VListLayout
from midi_notes import MIDI_DRUM_PITCHES
from liquiphy import LiquidSFZ
from jack_connection_manager import JackConnectionManager, JackConnectError
from jack_midi_split import MidiSplitter

# PyQt5 imports
from PyQt5 import uic
from PyQt5.QtCore import	Qt, pyqtSignal, pyqtSlot, QObject, QTimer, \
							QThreadPool, QRunnable, QPoint, QCoreApplication
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, \
							QAction, QActionGroup, QMenu, QLabel, QVBoxLayout, \
							QGroupBox, QRadioButton
from PyQt5.QtGui import		QIcon

from kitbash import settings, APPLICATION_NAME, PACKAGE_DIR, \
					SAMPLES_RESOLVE, SAMPLES_COPY, SAMPLES_SYMLINK, \
					SAMPLES_HARDLINK, SAMPLES_ABSPATH
from kitbash.drumkit import Drumkit
from kitbash.drumkit_widget import DrumkitWidget


class MainWindow(QMainWindow):

	instance = None
	options = None
	sig_ports_complete = pyqtSignal()

	def __new__(cls, options):
		if cls.instance is None:
			cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self, options):
		if self.options:
			return
		super().__init__()
		self.options = options
		with ShutUpQT():
			uic.loadUi(os.path.join(PACKAGE_DIR, 'res', 'main_window.ui'), self)
		#self.setWindowIcon(QIcon(os.path.join(PACKAGE_DIR, 'res', 'icon.png')))
		geometry = settings().value("geometry/MainWindow", None)
		if geometry is not None:
			self.restoreGeometry(geometry)
		self.recent_projects = RecentItemsList(settings().value("recent_projects", defaultValue=[]))
		self.recent_drumkits = RecentItemsList(settings().value("recent_drumkits", defaultValue=[]))
		self.project_filename = None
		self.project_definition = None
		self.project_loading = False
		self.dirty = False
		self.sfz_filename = None
		self.bashed_kit = None
		self.bashed_sfz_filename = None
		self.bashed_sfz_samples_mode = None
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
		self.midi_splitter = MidiSplitter(APPLICATION_NAME)
		self.splitter_assignments = [ None for i in range(16) ]
		# Setup signals
		signal(SIGINT, self.system_signal)
		signal(SIGTERM, self.system_signal)
		self.set_dirty(False)
		self.instantiate_synth(self)
		if self.options.Filename:
			QTimer.singleShot(10, partial(self.load_project, self.options.Filename))

	def setup_window_elements(self):
		self.drumkit_widgets = VListLayout(end_space = 10)
		self.drumkit_widgets.setContentsMargins(0,0,0,0)
		self.drumkit_widgets.setSpacing(2)
		self.kits_area.setLayout(self.drumkit_widgets)

	def connect_actions(self):
		self.action_collapse_kits.triggered.connect(self.slot_collapse_kits)
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

	def update_ui(self):
		title = APPLICATION_NAME \
			if self.project_filename is None \
			else f"{self.project_filename} [{APPLICATION_NAME}]"
		self.setWindowTitle("* " + title if self.dirty else title)
		has_kits = bool(len(self.drumkit_widgets))
		self.action_collapse_kits.setEnabled(has_kits)
		self.action_collapse_kits.setChecked(has_kits)
		self.action_new_project.setEnabled(has_kits)
		self.action_save_project.setEnabled(has_kits and self.dirty)
		self.action_save_bashed_kit.setEnabled(has_kits)
		self.b_save_kit.setEnabled(has_kits)

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
		self.dirty = state
		self.update_ui()

	def compile_project_def(self):
		return {
			widget.sfz_filename : widget.saved_selections() \
			for widget in self.drumkit_widgets
		}

	def load_recent_project(self, filename):
		if self.permission_to_clear():
			self.load_project(filename)

	def load_project(self, filename):
		"""
		Called internally - NOT FROM GUI SIGNALS.
		Starts project load; saves recent file name.
		Permission to clear must already have been given.
		"""
		if os.path.exists(filename):
			try:
				with open(filename, 'r') as fh:
					self.project_definition = json.load(fh)
			except json.JSONDecodeError as e:
				DevilBox('There was a problem decoding:\n' +
					f'"{filename}"\n' + \
					f'"{e}"\n' + \
					'Are you sure it is a kitbash project?')
			else:
				if len(self.drumkit_widgets):
					self.clear()
				self.project_filename = filename
				self.register_recent_project()
				self.project_loading = True
				for filename in self.project_definition.keys():
					self.load_drumkit(filename)
		else:
			self.recent_projects.remove(filename)
			settings().setValue("recent_projects", self.recent_projects.items)
			DevilBox(f"Project not found: {filename}")

	def save_project(self):
		with open(self.project_filename, 'w') as fh:
			json.dump(self.compile_project_def(), fh, indent="\t")
		self.register_recent_project()
		self.set_dirty(False)

	def register_recent_project(self):
		self.recent_projects.select(self.project_filename)
		settings().setValue("recent_project_folder", os.path.dirname(self.project_filename))
		settings().setValue("recent_projects", self.recent_projects.items)

	def permission_to_clear(self):
		if not self.dirty:
			return True
		dlg = QMessageBox(
			QMessageBox.Warning,
			"Save changes?",
			"There are changes to the current project.\nDo you want to save changes?",
			QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
			self
		)
		ret = dlg.exec()
		if ret == QMessageBox.Save:
			self.slot_save_project()
			return True
		elif ret == QMessageBox.Cancel:
			return False
		else:
			return True

	def clear(self):
		self.project_filename = None
		for widget in reversed(self.drumkit_widgets):
			self.slot_remove_drumkit(widget)
		self.set_dirty(False)

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
		with SigBlock(self.cmb_midi_srcs):
			self.cmb_midi_srcs.clear()
			self.cmb_midi_srcs.addItem('')
			for port in self.conn_man.output_ports():
				if port.is_midi and APPLICATION_NAME not in port.name:
					self.cmb_midi_srcs.addItem(port.name)
			if self.current_midi_source:
				self.cmb_midi_srcs.setCurrentText(self.current_midi_source)

	def fill_cmb_sinks(self):
		with SigBlock(self.cmb_audio_sinks):
			self.cmb_audio_sinks.clear()
			items = ['']
			items.extend(self.conn_man.physical_playback_clients())
			self.cmb_audio_sinks.addItems(items)
			if self.current_audio_sink:
				self.cmb_audio_sinks.setCurrentText(self.current_audio_sink)

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
		if self.current_audio_sink:
			liquid_client_names = [ self.synth.client_name ] if self.synth else []
			for drumkit_widget in self.drumkit_widgets:
				if drumkit_widget.synth and drumkit_widget.synth.client_name:
					liquid_client_names.append(drumkit_widget.synth.client_name)
			for audio_sink_port in self.audio_sink_ports:
				for src_port in self.conn_man.get_port_connections(audio_sink_port):
					if src_port.client_name in liquid_client_names:
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
		if action and self.new_synth and 'liquidsfz' in client_name:
			self.new_synth.client_name = client_name

	def jack_port_registration(self, port, action):
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
				self.sig_ports_complete.emit()
		elif port.is_output and port.is_midi and APPLICATION_NAME not in port.name:
			self.fill_cmb_sources()

	@pyqtSlot()
	def slot_ports_complete(self):
		associated_object = self.synth_creation_queue.popleft()
		associated_object.synth = self.new_synth
		if len(self.synth_creation_queue):
			self.start_new_synth()
		else:
			self.new_synth = None
		self.connect_audio_sink(associated_object.synth)
		if isinstance(associated_object, DrumkitWidget):
			logging.debug('%s ports complete', associated_object)
			src = self.midi_splitter.output_ports[associated_object.port_number].name
			tgt = associated_object.synth.input_port.name
			self.conn_man.connect_by_name(src, tgt)
			self.check_drumkit_ready(associated_object)
		else:
			self.connect_midi_source(associated_object.synth)

	# -----------------------------------------------------------------
	# Drumkit load / delete / instrument selection

	def load_drumkit(self, filename):
		if os.path.exists(filename):
			drumkit_widget = DrumkitWidget(filename, self)
			available_ports = self.available_port_numbers()
			if len(available_ports):
				drumkit_widget.port_number = available_ports[0]
			else:
				DevilBox('Not enough ports (Maximum 16)')
			self.drumkit_widgets.append(drumkit_widget)
			drumkit_widget.sig_inst_toggle.connect(self.slot_inst_toggle)
			drumkit_widget.sig_remove_drumkit.connect(self.slot_remove_drumkit)
			self.instantiate_synth(drumkit_widget)
			worker = KitLoader(drumkit_widget)
			worker.signals.sig_loaded.connect(drumkit_widget.slot_drumkit_loaded)
			worker.signals.sig_widget_loaded.connect(self.slot_drumkit_widget_loaded)
			self.background_threadpool.start(worker)
			self.recent_drumkits.select(filename)
			settings().setValue("recent_drumkit_folder", os.path.dirname(filename))
		else:
			self.recent_drumkits.remove(filename)
			DevilBox(f"File not found: {filename}")
		settings().setValue("recent_drumkits", self.recent_drumkits.items)

	@pyqtSlot(DrumkitWidget)
	def slot_drumkit_widget_loaded(self, drumkit_widget):
		"""
		Called when KitLoader is finshed loading and interpreted SFZ.
		"""
		logging.debug('%s loaded', drumkit_widget)
		self.action_collapse_kits.setEnabled(True)
		self.check_drumkit_ready(drumkit_widget)

	def check_drumkit_ready(self, drumkit_widget):
		if not drumkit_widget.synth is None and not drumkit_widget.drumkit is None:
			logging.debug('%s ready on port %s', drumkit_widget, drumkit_widget.port_number)
			if self.project_loading:
				drumkit_widget.apply_selections(self.project_definition[drumkit_widget.sfz_filename])
				self.check_project_load_complete()
			else:
				if len(self.drumkit_widgets) == 1:
					drumkit_widget.select_all()
					self.midi_splitter.assign_all_notes(drumkit_widget.port_number)
				self.set_dirty()

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
		if state:
			if not ctrl_state:
				for drumkit_widget in self.drumkit_widgets:
					if not drumkit_widget is source_widget:
						drumkit_widget.deselect_instrument(inst_id)
			source_widget.reselect_parent_group(inst_id)
		# Deselect the GroupButton if instrument deselected:
		else:
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
		self.set_dirty()

	@pyqtSlot(bool)
	def slot_preview_toggle(self, state):
		"""
		Select bashed sfz for play preview; deselect all drumkits.
		"""
		self.midi_splitter.bypassed = state
		self.b_preview.setIcon(QIcon.fromTheme('audio-volume-high' \
			if state else 'audio-volume-muted'))

	@pyqtSlot(Drumkit)
	def slot_drumkit_bashed(self, bashed_kit):
		"""
		Triggered from KitBasher signal when bashing is finished.
		"""
		self.bashed_kit = bashed_kit
		try:
			bashed_kit.save_as(self.bashed_sfz_filename, self.bashed_sfz_samples_mode)
			self.synth.load(self.bashed_sfz_filename)
			logging.debug('Loaded bashed .sfz at %s', self.bashed_sfz_filename)
			self.b_preview.setEnabled(True)
		except OSError as e:
			DevilBox('Hardlinks between devices are not allowed.\n' +\
				'Choose a different path or sample mode.' if e.errno == 18 \
				else str(e))

	def used_port_numbers(self):
		"""
		Returns a set of MidiSplitter port numbers assigned to drumkit widget's synth
		"""
		return set(drumkit_widget.port_number \
			for drumkit_widget in self.drumkit_widgets)

	def available_port_numbers(self):
		"""
		Returns a list of MidiSplitter port numbers not yet assigned to drumkit widget's synth
		"""
		return list(self.drumkit_port_ranges ^ self.used_port_numbers())

	# -----------------------------------------------------------------
	# Quit / close / signals

	def closeEvent(self, event):
		logging.debug('MainWindow close()')
		self.synth.quit()
		for drumkit_widget in self.drumkit_widgets:
			drumkit_widget.synth.quit()
		settings().setValue("geometry/MainWindow", self.saveGeometry())
		logging.debug('Total %d xruns', self.current_xruns)
		event.accept()

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
			action.triggered.connect(partial(self.load_recent_project, filename))
			actions.append(action)
		self.menu_RecentProject.addActions(actions)

	@pyqtSlot()
	def slot_new_project(self):
		if self.permission_to_clear():
			self.clear()

	@pyqtSlot()
	def slot_open_project(self):
		if self.permission_to_clear():
			QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, False)
			filename = QFileDialog.getOpenFileName(self,
				"Open saved project",
				settings().value("recent_project_folder", ""),
				"Kitbash project (*.json)"
			)[0]
			if filename != '':
				self.load_project(filename)

	@pyqtSlot()
	def slot_save_project(self):
		if self.project_filename is None:
			QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, False)
			filename, _ = QFileDialog.getSaveFileName(
				self,
				"Save Kitbash project ...",
				"kitbash.json",
				"Kitbash project (*.json)"
			)
			if filename == '':
				return
			self.project_filename = filename
		self.save_project()

	@pyqtSlot()
	def slot_save_bashed_kit(self):
		"""
		See also: slot_drumkit_bashed
		"""
		dlg = FileSaveDialog(self)
		if dlg.exec_() and dlg.selected_file:
			self.bashed_sfz_filename = dlg.selected_file
			self.bashed_sfz_samples_mode = dlg.samples_mode
			worker = KitBasher(self.drumkit_widgets)
			worker.signals.sig_bashed.connect(self.slot_drumkit_bashed)
			self.background_threadpool.start(worker)

	@pyqtSlot()
	def slot_load_kit(self):
		QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, False)
		filename = QFileDialog.getOpenFileName(self,
			"Load Drumkit",
			settings().value("recent_drumkit_folder", ''),
			"SFZ file (*.sfz)"
		)[0]
		if filename != '':
			self.load_drumkit(filename)


class KitWorkerSignals(QObject):

	sig_loaded = pyqtSignal(Drumkit)
	sig_widget_loaded = pyqtSignal(DrumkitWidget, Drumkit)
	sig_bashed = pyqtSignal(Drumkit)


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
		self.signals.sig_bashed.emit(bashed_kit)


class JackLiquidSFZ(LiquidSFZ):

	def __init__(self, filename):
		self.client_name = None
		self.input_port = None
		self.output_ports = []
		super().__init__(filename, defer_start = True)


class FileSaveDialog(QFileDialog):

	def __init__(self, parent):
		QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs)
		super().__init__(parent)
		geometry = settings().value("geometry/FileSaveDialog", None)
		if geometry is not None:
			self.restoreGeometry(geometry)
		self.setWindowTitle("Save as .sfz")
		self.setFileMode(QFileDialog.AnyFile)
		self.setViewMode(QFileDialog.List)
		lbl = QLabel()
		self.layout().addWidget(lbl)
		gb = QGroupBox('Sample location')
		self.r_abspath = QRadioButton('Point to the original samples - absolute path')
		self.r_resolve = QRadioButton('Point to the original samples - relative')
		self.r_copy = QRadioButton('Copy to a new "./samples" folder')
		self.r_symlink = QRadioButton('Create symlinks in a new "./samples" folder')
		self.r_hardlink = QRadioButton('Hardlink the originals in a new "./samples" folder')
		self.r_abspath.clicked.connect(partial(self.slot_set_mode, SAMPLES_ABSPATH))
		self.r_resolve.clicked.connect(partial(self.slot_set_mode, SAMPLES_RESOLVE))
		self.r_copy.clicked.connect(partial(self.slot_set_mode, SAMPLES_COPY))
		self.r_symlink.clicked.connect(partial(self.slot_set_mode, SAMPLES_SYMLINK))
		self.r_hardlink.clicked.connect(partial(self.slot_set_mode, SAMPLES_HARDLINK))
		lo = QVBoxLayout()
		lo.setContentsMargins(2,2,2,2)
		lo.setSpacing(2)
		lo.addWidget(self.r_abspath)
		lo.addWidget(self.r_resolve)
		lo.addWidget(self.r_copy)
		lo.addWidget(self.r_symlink)
		lo.addWidget(self.r_hardlink)
		gb.setLayout(lo)
		self.samples_mode = int(settings().value("save_as_samples_mode", SAMPLES_HARDLINK))
		if self.samples_mode == SAMPLES_ABSPATH:
			self.r_abspath.setChecked(True)
		elif self.samples_mode == SAMPLES_RESOLVE:
			self.r_resolve.setChecked(True)
		elif self.samples_mode == SAMPLES_COPY:
			self.r_copy.setChecked(True)
		elif self.samples_mode == SAMPLES_SYMLINK:
			self.r_symlink.setChecked(True)
		else:
			self.r_hardlink.setChecked(True)
		self.layout().addWidget(gb)
		self.selected_file = None

	@pyqtSlot(int, bool)
	def slot_set_mode(self, mode, state):
		self.samples_mode = mode

	def accept(self):
		settings().setValue("save_as_samples_mode", self.samples_mode)
		selected_files = self.selectedFiles()
		self.selected_file = selected_files[0] if selected_files else None
		super().accept()

	def done(self, result):
		print('FileSaveDialog done')
		settings().setValue("geometry/FileSaveDialog", self.saveGeometry())
		super().done(result)

# -----------------------------------------------------------------
# main()

def main():

	p = argparse.ArgumentParser()
	p.epilog = """
	Write your help text!
	"""
	p.add_argument('Filename', type=str, help='SFZ file[s] to include at startup')
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
		main_window = MainWindow(options)
	except JackConnectError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	sys.exit(main())


#  end kitbash/gui.py
