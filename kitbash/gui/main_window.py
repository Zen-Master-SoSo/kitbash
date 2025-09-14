#  kitbash/gui/main_window.py
#
#  Copyright 2025 liyang <liyang@veronica>
#
"""
Provides MainWindow class and
"""
import os, logging, json
from os.path import dirname, basename, realpath, exists, join, splitext
from collections import deque
from functools import partial
from signal import signal, SIGINT, SIGTERM

from PyQt5 import uic
from PyQt5.QtCore import	Qt, QObject, pyqtSignal, pyqtSlot, QSize, QTimer, \
							QThreadPool, QRunnable, QPoint, QCoreApplication
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, \
							QLabel, QFrame, QSizePolicy, QPushButton, QCheckBox, \
							QMainWindow, QMessageBox, QFileDialog, \
							QAction, QActionGroup, QMenu, \
							QGroupBox, QRadioButton
from PyQt5.QtGui import		QIcon

from qt_extras import ShutUpQT, SigBlock, DevilBox
from qt_extras.list_layout import VListLayout
from recent_items_list import RecentItemsList
from midi_notes import MIDI_DRUM_PITCHES
from liquiphy import LiquidSFZ
from conn_jack import JackConnectionManager
from jack_midi_split import MidiSplitter
from sfzen.drumkits import Drumkit, PercussionInstrument
from sfzen import	SAMPLES_ABSPATH, SAMPLES_RESOLVE, SAMPLES_COPY, \
					SAMPLES_SYMLINK, SAMPLES_HARDLINK

from kitbash.gui import group_expanded_icon, group_hidden_icon, remove_icon, \
						GeometrySaver
from kitbash import styles, set_application_style, settings, \
					APPLICATION_NAME, PACKAGE_DIR, \
					KEY_STYLE, KEY_SAMPLES_MODE, \
					KEY_RECENT_DRUMKIT_FOLDER, KEY_RECENT_DRUMKITS, \
					KEY_RECENT_PROJECT_FOLDER, KEY_RECENT_PROJECTS


class DrumkitWidget(QFrame):
	"""
	Graphical representation of a drumkit.
	"""

	sig_inst_toggle = pyqtSignal(QObject, str, bool, bool)
	sig_remove_drumkit = pyqtSignal(QObject)

	def __init__(self, filename, parent):
		super().__init__(parent)
		self.sfz_filename = filename
		self.moniker = basename(self.sfz_filename)
		self.drumkit = None
		self.synth = None
		self.port_number = None
		self.initial_height = None
		self.velocity = None

		self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)

		main_layout = QVBoxLayout()
		main_layout.setContentsMargins(1,1,1,1)
		main_layout.setSpacing(0)

		frm_top = QFrame()
		frm_top.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
		frm_top.setObjectName('frm_top')

		lo_top = QHBoxLayout()
		lo_top.setContentsMargins(2,2,2,2)
		lo_top.setSpacing(0)

		self.hide_button = QPushButton(self)
		self.hide_button.setIcon(group_expanded_icon())
		self.hide_button.setIconSize(QSize(16,16))
		self.hide_button.setCheckable(True)
		self.hide_button.toggled.connect(self.slot_hide)
		lo_top.addWidget(self.hide_button)

		label = QLabel(self)
		label.setText(self.sfz_filename)
		lo_top.addWidget(label)

		self.lbl_use_count = QLabel(self)
		self.lbl_use_count.setText('(0)')
		lo_top.addWidget(self.lbl_use_count)

		lo_top.addStretch(20)

		remove_button = QPushButton(self)
		remove_button.setIcon(remove_icon())
		remove_button.setIconSize(QSize(16,16))
		remove_button.clicked.connect(self.slot_remove_clicked)
		lo_top.addWidget(remove_button)

		frm_top.setLayout(lo_top)

		main_layout.addWidget(frm_top)

		self.frm_groups = QFrame(self)
		self.frm_groups.setObjectName('frm_groups')
		self.groups = QHBoxLayout()
		self.groups.setContentsMargins(1,1,1,1)
		self.groups.setSpacing(0)

		self.frm_groups.setLayout(self.groups)
		main_layout.addWidget(self.frm_groups)
		self.setLayout(main_layout)

	def ready(self):
		"""
		Returns "True" if this DrumkitWidget has a synth assigned and a bashed kit.
		"""
		return not self.synth is None and not self.drumkit is None

	@pyqtSlot(Drumkit)
	def slot_drumkit_loaded(self, drumkit):
		"""
		Called when KitLoader is finshed loading and interpreted SFZ.
		Fills the groups and instruments of this the DrumkitWidget.
		"""
		self.drumkit = drumkit
		for group in self.drumkit.groups.values():
			if group.empty():
				continue
			group_frame = GroupFrame(group, self)
			group_frame.group_button.clicked.connect(partial(self.slot_group_clicked, group_frame))
			for inst in group.instruments.values():
				inst_button = InstrumentButton(inst, group_frame)
				inst_button.toggled.connect(partial(self.slot_instrument_toggled, inst_button))
				inst_button.sig_mouse_press.connect(self.slot_instrument_pressed)
				inst_button.sig_mouse_release.connect(self.slot_instrument_released)
				group_frame.group_layout.addWidget(inst_button)
			group_frame.group_layout.addStretch()
			self.groups.addWidget(group_frame)
		self.groups.addStretch()

	@pyqtSlot(QFrame)
	def slot_group_clicked(self, group_frame):
		"""
		Triggered by a GroupButton click event.
		"group_frame" is the QFrame which contains the clicked GroupButton and various
		InstrumentButton instances.
		InstrumentButton signals are not suppressed, and trigger "sig_inst_toggle".
		"""
		group_button = group_frame.findChild(GroupButton)
		for inst_button in group_frame.findChildren(InstrumentButton):
			inst_button.setChecked(group_button.isChecked())

	@pyqtSlot(int)
	def slot_velocity_change(self, velocity):
		self.velocity = velocity

	@pyqtSlot(PercussionInstrument)
	def slot_instrument_pressed(self, inst):
		"""
		Triggered by InstrumentButton mouse press.
		Sends a "noteon" to this widget's synth.
		"""
		self.synth.noteon(0, inst.pitch, self.velocity)

	@pyqtSlot(PercussionInstrument)
	def slot_instrument_released(self, inst):
		"""
		Triggered by InstrumentButton mouse relase.
		Sends a "v" to this widget's synth.
		"""
		self.synth.noteoff(0, inst.pitch)

	@pyqtSlot(QPushButton)
	def slot_instrument_toggled(self, button):
		"""
		Triggered by an InstrumentButton toggle event.
		"inst_id" is a string key, enumerated in the DrumkitClass.
		"button" is the InstrumentButton which was toggled.
		"""
		self.sig_inst_toggle.emit(self, button.inst.inst_id,
			button.isChecked(), self.ctrl_pressed())
		self.update_count()

	@pyqtSlot()
	def slot_remove_clicked(self):
		"""
		Triggered by the "remove" button click event.
		"""
		self.sig_remove_drumkit.emit(self)

	@pyqtSlot(bool)
	def slot_hide(self, state):
		"""
		"Roll up" this DrumkitWidget.
		"""
		if state:
			self.initial_height = self.height()
			self.frm_groups.hide()
			self.hide_button.setIcon(group_hidden_icon())
		else:
			self.frm_groups.show()
			self.hide_button.setIcon(group_expanded_icon())

	def update_count(self):
		"""
		Updates the "use count" label with the number of selected instruments.
		Sets the audio indicator pixmap based on if playing or not.
		"""
		use_count = len([ b for b in self.frm_groups.findChildren(InstrumentButton) if b.isChecked() ])
		self.lbl_use_count.setText('(%d)' % use_count)
		font = self.lbl_use_count.font()
		font.setBold(bool(use_count))
		self.lbl_use_count.setFont(font)

	def ctrl_pressed(self):
		"""
		Returns (bool) True if the CTRL key is being pressed. Useful for making
		multiple selections.
		"""
		return QApplication.keyboardModifiers() == Qt.ControlModifier

	def inst_button(self, inst_id):
		"""
		Returns the instrument button identified by the given inst_id.
		"""
		return self.findChild(InstrumentButton, inst_id)

	def deselect_parent_group(self, inst_id):
		"""
		Called whenever an InstrumentButton is deselected.
		The parent group button is deselected.
		"""
		inst_button = self.inst_button(inst_id)
		inst_button.parentWidget().findChild(GroupButton).setChecked(False)

	def reselect_parent_group(self, inst_id):
		"""
		Called whenever an InstrumentButton is selected.
		The parent group button is selected if all of its' InstrumentButtons are
		selected.
		"""
		group = self.inst_button(inst_id).parentWidget()
		if all(inst_button.isChecked() for inst_button in group.findChildren(InstrumentButton)):
			group.findChild(GroupButton).setChecked(True)

	def deselect_instrument(self, inst_id):
		"""
		Called from MainWindow when a button with the same inst_id is selected
		exclusively (not CTRL key pressed).
		"""
		button = self.inst_button(inst_id)
		if button:	# May not exist, as not all Drumkits use the same instruments
			button.setChecked(False)
			self.update_count()

	def selected_instrument_ids(self):
		"""
		Returns a list of instrument ids from selected instrument buttons.
		"""
		return [ button.inst.inst_id \
				for button in self.findChildren(InstrumentButton) \
				if button.isChecked() ]

	@pyqtSlot()
	def slot_select_all(self):
		"""
		Select all instruments.
		Triggered by kits_area context menu.
		Called when this is the first DrumkitWidget added to a project.
		"""
		for type_ in [GroupButton, InstrumentButton]:
			for button in self.findChildren(type_):
				button.setChecked(True)
		self.update_count()

	def saved_selections(self):
		"""
		Returns dictionary of button states for saving with project.
		"""
		return {
			group_frame.group_id : {
				'group' 		: group_frame.findChild(GroupButton).isChecked(),
				'instruments'	: {
					inst_button.inst.inst_id : inst_button.isChecked() \
					for inst_button in group_frame.findChildren(InstrumentButton)
				}
			}
			for group_frame in self.findChildren(GroupFrame)
		}

	def apply_selections(self, selections):
		"""
		Restores button states from dictionary when loading project.
		"""
		for group_frame in self.findChildren(GroupFrame):
			if group_frame.group_id in selections:
				sel = selections[group_frame.group_id]
				group_button = group_frame.findChild(GroupButton)
				with SigBlock(group_button):
					group_button.setChecked(sel['group'])
				for inst_button in group_frame.findChildren(InstrumentButton):
					if inst_button.inst.inst_id in sel['instruments']:
						inst_button.setChecked(sel['instruments'][inst_button.inst.inst_id])
					else:
						logging.warning('Button "%s" not found in project def', inst_button.inst.inst_id)
			else:
				logging.warning('Group "%s" not found in project def', group_frame.group_id)

	def __str__(self):
		return f"<DrumkitWidget {self.moniker}>"


class MainWindow(QMainWindow, GeometrySaver):

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
		set_application_style()
		with ShutUpQT():
			uic.loadUi(join(PACKAGE_DIR, 'gui', 'main_window.ui'), self)
		self.setWindowIcon(QIcon(join(PACKAGE_DIR, 'res', 'kitbash-icon.png')))
		self.restore_geometry()
		self.recent_projects = RecentItemsList(settings().value(KEY_RECENT_PROJECTS, []))
		self.recent_drumkits = RecentItemsList(settings().value(KEY_RECENT_DRUMKITS, []))
		self.dirty = False
		self.project_filename = None
		self.project_definition = None
		self.project_loading = False
		self.bashed_sfz_filename = None
		self.bashed_sfz_samples_mode = None
		self.drumkit_port_ranges = set( port_number for port_number in range(16) )
		self.synth_creation_queue = deque()
		self.new_synth = None
		self.current_midi_source = None
		self.current_audio_sink = None
		self.audio_sink_ports = []
		self.base_xruns = self.current_xruns = 0
		self.b_xruns.setText('0')
		self.fill_style_menu()
		self.setup_window_elements()
		self.connect_actions()
		self.clear()
		# Setup background threadpool for KitLoader and KitBasher workers
		self.background_threadpool = QThreadPool()
		self.setup_conn_man()
		# Fill sink/source menus:
		self.fill_cmb_sources()
		self.fill_cmb_sinks()
		# Setup signals
		# Note: sig_ports_complete is emitted from a JACK.Client process thread.
		# That is why we force use of QueuedConnection between that signal and the main GUI thread.
		self.sig_ports_complete.connect(self.slot_ports_complete, type = Qt.QueuedConnection)
		self.cmb_midi_srcs.currentTextChanged.connect(self.slot_midi_src_changed)
		self.cmb_audio_sinks.currentTextChanged.connect(self.slot_audio_sink_changed)
		# Setup MidiSplitter
		self.midi_splitter = MidiSplitter(APPLICATION_NAME)
		self.splitter_assignments = [ None for i in range(16) ]
		# Setup signals
		signal(SIGINT, self.system_signal)
		signal(SIGTERM, self.system_signal)
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
		self.action_save_project_as.triggered.connect(self.slot_save_project_as)
		self.action_save_bashed_kit.triggered.connect(self.slot_save_kit)
		self.action_save_kit_as.triggered.connect(self.slot_save_kit_as)
		self.action_add_drumkit.triggered.connect(self.slot_add_drumkit)
		self.b_add_drumkit.clicked.connect(self.slot_add_drumkit)
		self.action_remove_all_kits.triggered.connect(self.slot_remove_all_kits)
		self.action_reload_style.triggered.connect(self.slot_reload_style)
		self.menu_recent_project.aboutToShow.connect(self.slot_show_recent_projects)
		self.menu_recent_drumkits.aboutToShow.connect(self.slot_show_recent_drumkits)
		self.kits_area.setContextMenuPolicy(Qt.CustomContextMenu)
		self.kits_area.customContextMenuRequested.connect(self.slot_kits_context_menu)
		self.b_copy_path.clicked.connect(self.slot_copy_kit_path)
		self.b_xruns.clicked.connect(self.slot_xruns_clicked)

	def setup_conn_man(self):
		# Setup JackConnectionManager
		self.conn_man = JackConnectionManager()
		self.conn_man.on_error(self.jack_error)
		self.conn_man.on_xrun(self.jack_xrun)
		self.conn_man.on_shutdown(self.jack_shutdown)
		self.conn_man.on_client_registration(self.jack_client_registration)
		self.conn_man.on_port_registration(self.jack_port_registration)

	def update_ui(self):
		title = APPLICATION_NAME \
			if self.project_filename is None \
			else f"{self.project_filename} [{APPLICATION_NAME}]"
		self.setWindowTitle("* " + title if self.dirty else title)
		has_kits = bool(len(self.drumkit_widgets))
		self.action_collapse_kits.setEnabled(has_kits)
		self.action_collapse_kits.setChecked(has_kits)
		self.action_remove_all_kits.setEnabled(has_kits)
		self.action_new_project.setEnabled(has_kits)
		self.action_save_project.setEnabled(has_kits and self.dirty)
		self.action_save_project_as.setEnabled(has_kits)
		self.action_save_bashed_kit.setEnabled(has_kits)
		self.b_save_kit.setEnabled(has_kits)
		self.b_copy_path.setVisible(bool(self.bashed_sfz_filename))
		self.lbl_bashed_sfz_filename.setText(self.bashed_sfz_filename \
			if self.bashed_sfz_filename else '')

	# -----------------------------------------------------------------
	# Style functions:

	def fill_style_menu(self):
		"""
		Fill the style menu with the list of discovered styles.
		"""
		current_style = settings().value(KEY_STYLE)
		actions = QActionGroup(self)
		actions.setExclusive(True)
		for style_name in styles():
			action = QAction(style_name, self)
			action.triggered.connect(partial(self.select_style, style_name))
			action.setCheckable(True)
			action.setChecked(style_name == current_style)
			actions.addAction(action)
			self.menu_style.addAction(action)

	def select_style(self, style):
		settings().setValue(KEY_STYLE, style)
		set_application_style()

	@pyqtSlot()
	def slot_reload_style(self):
		set_application_style()

	# -----------------------------------------------------------------
	# Project loading / saving:

	def set_dirty(self, state = True):
		if not self.project_loading:
			self.dirty = state
			self.update_ui()

	def compile_project_def(self):
		return {
			'bashed_sfz_filename'		: self.bashed_sfz_filename,
			'bashed_sfz_samples_mode'	: self.bashed_sfz_samples_mode,
			'drumkits'					: {
				widget.sfz_filename : widget.saved_selections() \
				for widget in self.drumkit_widgets
			}
		}

	def load_recent_project(self, filename):
		if self.okay_to_clear():
			self.load_project(filename)

	def load_project(self, filename):
		"""
		Called internally - NOT FROM GUI SIGNALS.
		Starts project load; saves recent file name.
		Permission to clear must already have been given.
		"""
		if exists(filename):
			try:
				with open(filename, 'r', encoding = 'utf-8') as fh:
					self.project_definition = json.load(fh)
			except json.JSONDecodeError as e:
				DevilBox('There was a problem decoding:\n' +
					f'"{filename}"\n' + \
					f'"{e}"\n' + \
					'Are you sure it is a kitbash project?')
			else:
				if len(self.drumkit_widgets):
					self.clear()
				self.project_filename = realpath(filename)
				self.register_recent_project()
				self.project_loading = True
				self.bashed_sfz_filename = self.project_definition['bashed_sfz_filename']
				self.bashed_sfz_samples_mode = self.project_definition['bashed_sfz_samples_mode']
				for sfzfile in self.project_definition['drumkits'].keys():
					self.load_drumkit(sfzfile)
		else:
			self.recent_projects.remove(filename)
			settings().setValue(KEY_RECENT_PROJECTS, self.recent_projects.items)
			DevilBox(f"Project not found: {filename}")

	def save_project(self):
		with open(self.project_filename, 'w', encoding = 'utf-8') as fh:
			json.dump(self.compile_project_def(), fh, indent="\t")
		self.register_recent_project()
		self.set_dirty(False)

	def save_kit(self):
		worker = KitBasher(self.drumkit_widgets)
		worker.signals.sig_bashed.connect(self.slot_drumkit_bashed)
		self.background_threadpool.start(worker)

	def register_recent_project(self):
		self.recent_projects.bump(self.project_filename)
		settings().setValue(KEY_RECENT_PROJECT_FOLDER, dirname(self.project_filename))
		settings().setValue(KEY_RECENT_PROJECTS, self.recent_projects.items)

	def okay_to_clear(self):
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
		if ret == QMessageBox.Cancel:
			return False
		if ret == QMessageBox.Save:
			self.slot_save_project()
		return True

	def clear(self):
		self.project_filename = None
		self.project_definition = None
		self.project_loading = False
		self.bashed_kit = None
		self.bashed_sfz_filename = None
		self.bashed_sfz_samples_mode = None
		self.new_synth = None
		self.dirty = False
		for widget in reversed(self.drumkit_widgets):
			self.slot_remove_drumkit(widget)
		self.set_dirty(False)

	# -----------------------------------------------------------------
	# Quit / close / signals

	def closeEvent(self, event):
		"""
		PyQt closeEvent overload.
		"""
		if self.okay_to_clear():
			self.conn_man.close()
			for drumkit_widget in self.drumkit_widgets:
				drumkit_widget.synth.quit()
			self.save_geometry()
			logging.debug('Total %d xruns', self.current_xruns)
			event.accept()
		else:
			event.ignore()

	def system_signal(self, *_):
		"""
		Catch system signals SIGINT and SIGTERM
		"""
		logging.debug('Caught signal - shutting down')
		self.close()

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
		self.current_midi_source = value
		if self.current_midi_source:
			self.conn_man.connect_by_name(self.current_midi_source, self.midi_splitter.input_port.name)

	@pyqtSlot(str)
	def slot_audio_sink_changed(self, value):
		if self.current_audio_sink:
			liquid_client_names = [
				drumkit_widget.synth.client_name \
				for drumkit_widget in self.drumkit_widgets \
				if drumkit_widget.synth and drumkit_widget.synth.client_name
			]
			for audio_sink_port in self.audio_sink_ports:
				for src_port in self.conn_man.get_port_connections(audio_sink_port):
					if src_port.client_name in liquid_client_names:
						self.conn_man.disconnect(src_port, audio_sink_port)
		self.current_audio_sink = value
		if self.current_audio_sink:
			self.audio_sink_ports = [ port for port \
				in self.conn_man.physical_input_ports() \
				if port.client_name == self.current_audio_sink ]
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
		if action:
			if self.new_synth and 'liquidsfz' in client_name:
				self.new_synth.client_name = client_name
		else:
			if self.cmb_audio_sinks.findText(client_name, Qt.MatchStartsWith) > -1:
				self.fill_cmb_sinks()
			elif self.cmb_midi_srcs.findText(client_name, Qt.MatchStartsWith) > -1:
				self.fill_cmb_sources()

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
		elif APPLICATION_NAME not in port.name:
			if port.is_output and port.is_midi:
				self.fill_cmb_sources()
			elif port.is_input and port.is_audio:
				self.fill_cmb_sinks()

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
		"""
		Adds a drumkit.
		1. called at project load
		2. triggered by "Edit -> Load Drumkit" menu
		3. triggered by kits_area custom context menu
		"""
		if exists(filename):
			drumkit_widget = DrumkitWidget(filename, self)
			available_ports = self.available_port_numbers()
			if available_ports:
				drumkit_widget.port_number = available_ports[0]
			else:
				DevilBox('Not enough ports (Maximum 16)')
			self.drumkit_widgets.append(drumkit_widget)
			QApplication.instance().processEvents()
			self.instantiate_synth(drumkit_widget)
			worker = KitLoader(drumkit_widget)
			worker.signals.sig_loaded.connect(drumkit_widget.slot_drumkit_loaded)
			worker.signals.sig_widget_loaded.connect(self.slot_drumkit_widget_loaded)
			self.background_threadpool.start(worker)
			if not self.project_loading:
				self.recent_drumkits.bump(filename)
				settings().setValue(KEY_RECENT_DRUMKIT_FOLDER, dirname(filename))
		else:
			self.recent_drumkits.remove(filename)
			DevilBox(f"File not found: {filename}")
		if not self.project_loading:
			settings().setValue(KEY_RECENT_DRUMKITS, self.recent_drumkits.items)

	@pyqtSlot(DrumkitWidget)
	def slot_drumkit_widget_loaded(self, drumkit_widget):
		"""
		Called when KitLoader is finshed loading and interpreted SFZ.
		"""
		self.update_ui()
		self.check_drumkit_ready(drumkit_widget)

	def check_drumkit_ready(self, drumkit_widget):
		"""
		Check if any/all drumkit widget has a synth assigned and a bashed kit.
		1. called after KitLoader is finished,
		2. called after synth is assigned (ports ready)
		If ready when project_loading, applies saved selections.
		"""
		if drumkit_widget.ready():
			drumkit_widget.sig_inst_toggle.connect(self.slot_inst_toggle)
			drumkit_widget.sig_remove_drumkit.connect(self.slot_remove_drumkit)
			drumkit_widget.velocity = self.spn_velocity.value()
			self.spn_velocity.valueChanged.connect(drumkit_widget.slot_velocity_change)
			if self.project_loading:
				drumkit_widget.apply_selections(
					self.project_definition['drumkits'][drumkit_widget.sfz_filename])
				if all(drumkit_widget.ready() for drumkit_widget in self.drumkit_widgets):
					self.project_loading = False
					self.update_ui()
			else:
				if len(self.drumkit_widgets) == 1:
					drumkit_widget.slot_select_all()
				self.set_dirty()

	@pyqtSlot(QObject)
	def slot_remove_drumkit(self, drumkit_widget):
		"""
		Directly triggered by kits_area custom context menu;
		called in any place where a drumkit_widget needs to be removed,
		including clear(), slot_remove_all_kits().
		"""
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
			"source_widget": DrumkitWidget containing the button clicked
			"inst_id":       (str)  Identifies the button clicked
			"state":         (bool) True if "checked"
			"ctrl_state":    (bool) True if CTRL key pressed when clicking
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

	@pyqtSlot(Drumkit)
	def slot_drumkit_bashed(self, bashed_kit):
		"""
		Triggered from KitBasher signal when bashing is finished.
		"""
		try:
			bashed_kit.save_as(self.bashed_sfz_filename, self.bashed_sfz_samples_mode)
			self.lbl_bashed_sfz_filename.setText(self.bashed_sfz_filename)
			logging.debug('Saved bashed .sfz at %s', self.bashed_sfz_filename)
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
	# UI handling slots:

	@pyqtSlot()
	def slot_xruns_clicked(self):
		"""
		Triggered by b_xruns.click()
		"""
		self.base_xruns = self.current_xruns
		self.b_xruns.setText('0')

	@pyqtSlot(QPoint)
	def slot_kits_context_menu(self, position):
		"""
		Triggered by kits_area.customContextMenuRequested
		"""
		menu = QMenu()
		clicked_drumkit_widget = self.kits_area.childAt(position)
		if clicked_drumkit_widget is not None:
			while not isinstance(clicked_drumkit_widget, DrumkitWidget) and \
				clicked_drumkit_widget.parent() is not None:
				clicked_drumkit_widget = clicked_drumkit_widget.parent()
			if isinstance(clicked_drumkit_widget, DrumkitWidget):
				action = QAction('Select all', self)
				action.triggered.connect(clicked_drumkit_widget.slot_select_all)
				menu.addAction(action)
				action = QAction(f'Remove "{clicked_drumkit_widget.moniker}"', self)
				action.triggered.connect(partial(self.slot_remove_drumkit, clicked_drumkit_widget))
				menu.addAction(action)
		menu.addAction(self.action_add_drumkit)
		menu.addAction(self.action_remove_all_kits)
		menu.addAction(self.action_collapse_kits)
		menu.exec(self.kits_area.mapToGlobal(position))

	@pyqtSlot()
	def slot_remove_all_kits(self):
		"""
		Triggered by 'Edit -> Remove All Drumkits" menu and kits_area context menu.
		"""
		for drumkit_widget in reversed(self.drumkit_widgets):
			self.slot_remove_drumkit(drumkit_widget)

	@pyqtSlot()
	def slot_collapse_kits(self):
		"""
		Triggered by "View -> Collapse Kits"
		"""
		for widget in self.drumkit_widgets:
			widget.hide_button.setChecked(True)

	@pyqtSlot()
	def slot_show_recent_drumkits(self):
		"""
		Fills "recent_drumkits" menu before expanding
		"""
		self.menu_recent_drumkits.clear()
		actions = []
		for filename in self.recent_drumkits:
			action = QAction(filename, self)
			action.triggered.connect(partial(self.load_drumkit, filename))
			actions.append(action)
		self.menu_recent_drumkits.addActions(actions)

	@pyqtSlot()
	def slot_show_recent_projects(self):
		"""
		Fills "recent_projects" menu before expanding
		"""
		self.menu_recent_project.clear()
		actions = []
		for filename in self.recent_projects:
			action = QAction(filename, self)
			action.triggered.connect(partial(self.load_recent_project, filename))
			actions.append(action)
		self.menu_recent_project.addActions(actions)

	@pyqtSlot()
	def slot_new_project(self):
		"""
		Triggered by "File -> New"
		"""
		if self.okay_to_clear():
			self.clear()

	@pyqtSlot()
	def slot_open_project(self):
		"""
		Triggered by "File -> Open Project"
		"""
		if self.okay_to_clear():
			QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, False)
			filename = QFileDialog.getOpenFileName(self,
				"Open saved project",
				settings().value(KEY_RECENT_PROJECT_FOLDER, ""),
				"Kitbash project (*.json)"
			)[0]
			if filename != '':
				self.load_project(filename)

	@pyqtSlot()
	def slot_save_project(self):
		"""
		Triggered by "File -> Save Project"
		Opens the file save dialog if project_filename is None; calls "save_project".
		"""
		if self.project_filename is None:
			self.slot_save_project_as()
		else:
			self.save_project()

	@pyqtSlot()
	def slot_save_project_as(self):
		"""
		Triggered by "File -> Save Project As"
		Opens the file save dialog, sets project_filename, calls "save_project".
		"""
		QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, False)
		filename, _ = QFileDialog.getSaveFileName(
			self,
			"Save Kitbash project ...",
			settings().value(KEY_RECENT_PROJECT_FOLDER, os.getcwd() \
				if self.project_filename is None \
				else dirname(self.project_filename)),
			"Kitbash project (*.json)"
		)
		if filename :
			self.project_filename = realpath(
				filename \
				if splitext(filename)[-1].lower() == '.json' \
				else filename + '.json')
			self.save_project()

	@pyqtSlot()
	def slot_save_kit(self):
		if self.bashed_sfz_filename is None:
			self.slot_save_kit_as()
		else:
			self.save_kit()

	@pyqtSlot()
	def slot_save_kit_as(self):
		"""
		Triggered by "File -> Save bashed kit" menu
		See also: slot_drumkit_bashed
		"""
		dlg = KitSaveDialog(self,
			int(settings().value(KEY_SAMPLES_MODE, SAMPLES_ABSPATH)) \
			if self.bashed_sfz_samples_mode is None \
			else self.bashed_sfz_samples_mode)
		if dlg.exec_() and dlg.selected_file:
			self.bashed_sfz_filename = dlg.selected_file
			self.bashed_sfz_samples_mode = dlg.samples_mode
			self.set_dirty()
			self.save_kit()

	@pyqtSlot()
	def slot_add_drumkit(self):
		"""
		Triggered by "Edit -> Add Drumkit" menu, and kits_area custom context menu..
		"""
		QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, False)
		filename = QFileDialog.getOpenFileName(self,
			"Load Drumkit",
			settings().value(KEY_RECENT_DRUMKIT_FOLDER, ''),
			"SFZ file (*.sfz)"
		)[0]
		if filename != '':
			self.load_drumkit(filename)

	@pyqtSlot()
	def slot_copy_kit_path(self):
		QApplication.instance().clipboard().setText(self.lbl_bashed_sfz_filename.text())


class KitWorkerSignals(QObject):
	"""
	Signals common to KitLoader and KitBasher.
	(PyQt QRunnable does not support its own signals)
	"""
	sig_loaded = pyqtSignal(Drumkit)
	sig_widget_loaded = pyqtSignal(DrumkitWidget, Drumkit)
	sig_bashed = pyqtSignal(Drumkit)


class KitLoader(QRunnable):
	"""
	Loads a drumkit in a background thread and emits "sig_loaded" when done.
	"""

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
	"""
	Compiles a bashed kit and signals that its ready to be saved.
	"""

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
	"""
	Wraps a LiquidSFZ instance in order to hold references to jacklib ports created
	by JackConnectionManager.
	"""

	def __init__(self, filename):
		self.client_name = None
		self.input_port = None
		self.output_ports = []
		super().__init__(filename, defer_start = True)


class KitSaveDialog(QFileDialog, GeometrySaver):
	"""
	Custom file dialog with added option for choosing samples_mode.
	"""

	def __init__(self, parent, samples_mode):
		QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs)
		super().__init__(parent)
		self.samples_mode = samples_mode
		self.restore_geometry()
		self.setWindowTitle("Save bashed kit as .sfz")
		self.setFileMode(QFileDialog.AnyFile)
		self.setViewMode(QFileDialog.List)
		lbl = QLabel()
		self.layout().addWidget(lbl)
		gb = QGroupBox('Sample location')
		self.r_abspath = QRadioButton('Point to the original samples - absolute path')
		self.r_resolve = QRadioButton('Point to the original samples - relative path')
		self.r_copy = QRadioButton('Copy samples to the "./samples" folder')
		self.r_symlink = QRadioButton('Create symlinks in the "./samples" folder')
		self.r_hardlink = QRadioButton('Hardlink the originals in the "./samples" folder')
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
	def slot_set_mode(self, mode, _):
		"""
		Tiggered by any sample mode selection radio button.
		"""
		self.samples_mode = mode

	@pyqtSlot()
	def accept(self):
		"""
		Overloaded function saves preferred mode, sets "selected_file".
		"""
		settings().setValue(KEY_SAMPLES_MODE, self.samples_mode)
		selected_files = self.selectedFiles()
		if selected_files:
			self.selected_file = realpath(
				selected_files[0] \
				if splitext(selected_files[0])[-1].lower() == '.sfz' \
				else selected_files[0] + '.sfz')
		else:
			self.selected_file = None
		super().accept()

	def done(self, result):
		"""
		Overloaded function saves geometry.
		"""
		self.save_geometry()
		super().done(result)


class GroupFrame(QFrame):
	"""
	QFrame which contains one GroupButton and one or more InstrumentButton
	"""

	def __init__(self, group, parent):
		super().__init__(parent)
		self.setFrameShape(QFrame.NoFrame)
		self.setObjectName(group.group_id)	# GroupFrame identified by group_id
		self.group_id = group.group_id
		self.group_layout = QVBoxLayout()
		self.group_layout.setSpacing(0)
		self.group_layout.setContentsMargins(0,0,0,0)
		self.setLayout(self.group_layout)
		self.group_button = GroupButton(self)		# GroupButton has no unique object name
		self.group_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		self.group_button.setText(group.name)
		self.group_button.setCheckable(True)
		self.group_layout.addWidget(self.group_button)


class GroupButton(QPushButton):
	"""
	Defined here to provide a distinct .css class name.
	"""


class InstrumentButton(QPushButton):
	"""
	Custom button with a contained InstrumentLabel and QCheckBox.
	The InstrumentLabel traps mouse press events, while the QCheckBox mirrors the
	"checked" state of this QPushButton.
	"""

	sig_mouse_press = pyqtSignal(PercussionInstrument)
	sig_mouse_release = pyqtSignal(PercussionInstrument)

	def __init__(self, inst, parent):
		super().__init__(parent)
		self.inst = inst
		self.setObjectName(inst.inst_id)
		self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		lo = QHBoxLayout()
		lo.setContentsMargins(0,0,0,0)
		lo.setSpacing(0)
		self.setLayout(lo)
		self.setCheckable(True)
		lo.addWidget(InstrumentLabel(inst, self))
		lo.addStretch()
		self.checkbox = QCheckBox(self)
		self.checkbox.stateChanged.connect(self.slot_checkbox_state_change)
		lo.addWidget(self.checkbox)

	@pyqtSlot(int)
	def slot_checkbox_state_change(self, state):
		"""
		Triggered when contained checkbox is clicked.
		"""
		self.setChecked(state == Qt.Checked)

	def checkStateSet(self):
		"""
		Extends QAbstractButton.checkStateSet.
		This is called in response to the gui setting the "checked" property of this QPushButton.
		"""
		with SigBlock(self.checkbox):
			self.checkbox.setChecked(self.isChecked())

	def mousePressEvent(self, event):
		"""
		Overrides mouse so that only the contained checkbox will toggle this widget's state.
		"""
		event.accept()
		self.mouse_press()

	def mouseReleaseEvent(self, event):
		"""
		Overrides mouse so that only the contained checkbox will toggle this widget's state.
		"""
		event.accept()
		self.mouse_release()

	def mouse_press(self):
		"""
		Called from contained label. Sets the "down" state of this widget,
		(which is identified in the CSS as the ":pressed" pseudo-selector).
		"""
		self.setDown(True)
		self.sig_mouse_press.emit(self.inst)

	def mouse_release(self):
		"""
		Called from contained label. Unsets the "down" state of this widget,
		(which is identified in the CSS as the ":pressed" pseudo-selector).
		"""
		self.setDown(False)
		self.sig_mouse_release.emit(self.inst)


class InstrumentLabel(QLabel):
	"""
	Label contained inside an InstrumentButton, delegating its' mouse press /
	release events to its' parent.
	"""

	def __init__(self, inst, parent):
		super().__init__(parent)
		self.setText(inst.name)
		self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)

	def mousePressEvent(self, event):
		self.parent().mouse_press()
		event.accept()

	def mouseReleaseEvent(self, event):
		self.parent().mouse_release()
		event.accept()


#  end kitbash/gui/main_window.py
