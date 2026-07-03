#  kitbash/kitbash/gui/main_window.py
#
#  Copyright 2025-2026 Leon Dionne <ldionne@dridesign.sh.cn>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
"""
Provides MainWindow.
"""
import logging, json
from tempfile import mkstemp
from os import getcwd, unlink
from os.path import dirname, realpath, exists, join, splitext
from functools import partial
from signal import signal, SIGINT, SIGTERM
from PyQt5 import uic
from PyQt5.QtCore import Qt, QObject, pyqtSlot, QTimer, QThreadPool, QPoint, QCoreApplication
from PyQt5.QtWidgets import (
	QApplication, QMainWindow, QMessageBox, QFileDialog, QAction, QActionGroup, QMenu)
from PyQt5.QtGui import QIcon
from qt_extras import ShutUpQT, SigBlock, DevilBox
from qt_extras.list_layout import VListLayout
from recent_items_list import RecentItemsList
from sfzen import SAMPLES_ABSPATH
from sfzen.drumkits import Drumkit
from kitbash import (
	APPLICATION_NAME, PACKAGE_DIR, DEFAULT_STYLE,
	styles, set_application_style, get_setting, set_setting, GeometrySaver,
	KEY_STYLE, KEY_SAMPLES_MODE, KEY_RECENT_DRUMKIT_FOLDER, KEY_RECENT_DRUMKITS,
	KEY_RECENT_PROJECT_FOLDER, KEY_RECENT_PROJECTS)
from kitbash.worker_threads import KitLoader, KitBasher
from kitbash.jack_audio import Audio
from kitbash.gui.drumkit_widget import DrumkitWidget
from kitbash.gui.kit_save_dialog import KitSaveDialog


UPDATES_DEBOUNCE = 680
MESSAGE_TIMEOUT = 2400


# pylint: disable-next = missing-class-docstring
class MainWindow(QMainWindow, GeometrySaver):

	instance = None
	options = None

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
		# Setup signals
		signal(SIGINT, self.system_signal)
		signal(SIGTERM, self.system_signal)
		# Internal variables:
		self.recent_projects = RecentItemsList(get_setting(KEY_RECENT_PROJECTS, []))
		self.recent_drumkits = RecentItemsList(get_setting(KEY_RECENT_DRUMKITS, []))
		self.base_xruns = self.current_xruns = 0
		self.bashed_kit = None
		self.dirty = False
		self.project_definition = None
		self.project_filename = None
		self.project_loading = False
		self.saved_sfz_filename = None
		self.saved_sfz_samples_mode = None
		_, self.tempfile = mkstemp(prefix = 'kitbash', suffix = '.sfz')
		# Setup update_timer which will trigger a rewrite of the output SFZ only after an interval:
		self.update_timer = QTimer()
		self.update_timer.setSingleShot(True)
		self.update_timer.setInterval(UPDATES_DEBOUNCE)
		self.update_timer.timeout.connect(self.slot_timer_timeout)
		# Setup background threadpool for KitLoader and KitBasher workers
		self.background_threadpool = QThreadPool()
		# Setup jack audio
		self.audio = Audio()
		# Setup GUI elements
		self.fill_style_menu()
		self.setup_kits_area()
		self.restore_geometry()
		self.connect_signals()
		self.update_ui()
		QTimer.singleShot(0, self.layout_complete)

	@pyqtSlot()
	def layout_complete(self):
		self.audio.connect()
		if self.options.Filename:
			self.load_project(self.options.Filename)

	def setup_kits_area(self):
		self.drumkit_widgets = VListLayout(end_space = 10)
		self.drumkit_widgets.setContentsMargins(0,0,0,0)
		self.drumkit_widgets.setSpacing(2)
		self.kits_area.setLayout(self.drumkit_widgets)

	def connect_signals(self):
		self.action_collapse_kits.triggered.connect(self.slot_collapse_kits)
		self.action_new_project.triggered.connect(self.slot_new_project)
		self.action_open_project.triggered.connect(self.slot_open_project)
		self.action_save_project.triggered.connect(self.slot_save_project)
		self.action_save_project_as.triggered.connect(self.slot_save_project_as)
		self.action_save_bashed_kit.triggered.connect(self.slot_save_kit)
		self.action_save_kit_as.triggered.connect(self.slot_save_kit_as)
		self.action_add_drumkit.triggered.connect(self.slot_add_drumkit)
		self.action_remove_all_kits.triggered.connect(self.slot_remove_all_kits)
		self.action_reload_style.triggered.connect(self.slot_reload_style)
		self.menu_recent_project.aboutToShow.connect(self.slot_show_recent_projects)
		self.menu_recent_drumkits.aboutToShow.connect(self.slot_show_recent_drumkits)
		self.kits_area.setContextMenuPolicy(Qt.CustomContextMenu)
		self.kits_area.customContextMenuRequested.connect(self.slot_kits_context_menu)
		self.b_new.clicked.connect(self.slot_new_project)
		self.b_open_project.clicked.connect(self.slot_open_project)
		self.b_save_project.clicked.connect(self.slot_save_project)
		self.b_save_kit.clicked.connect(self.slot_save_kit)
		self.b_copy_path.clicked.connect(self.slot_copy_kit_path)
		self.b_add_drumkit.clicked.connect(self.slot_add_drumkit)
		self.b_xruns.clicked.connect(self.slot_xruns_clicked)
		self.cmb_midi_srcs.currentTextChanged.connect(
			self.audio.slot_midi_src_selected)
		self.cmb_audio_sinks.currentTextChanged.connect(
			self.audio.slot_audio_sink_selected)
		self.audio.sig_sources_changed.connect(
			self.slot_sources_changed)
		self.audio.sig_sinks_changed.connect(
			self.slot_sinks_changed)

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
		self.b_save_project.setEnabled(has_kits)
		self.b_save_kit.setEnabled(has_kits)
		self.b_copy_path.setVisible(bool(self.saved_sfz_filename))

	# -----------------------------------------------------------------
	# Style functions:

	def fill_style_menu(self):
		"""
		Fill the style menu with the list of discovered styles.
		"""
		current_style = get_setting(KEY_STYLE, DEFAULT_STYLE)
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
		set_setting(KEY_STYLE, style)
		set_application_style()
		self.statusbar.showMessage(f'Set style "{style}"', MESSAGE_TIMEOUT)

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
			'saved_sfz_filename'		: self.saved_sfz_filename,
			'saved_sfz_samples_mode'	: self.saved_sfz_samples_mode,
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
		logging.debug('load_project %s', filename)
		if exists(filename):
			try:
				with open(filename, 'r', encoding = 'utf-8') as fh:
					self.project_definition = json.load(fh)
			except json.JSONDecodeError as e:
				DevilBox('There was a problem decoding:\n' +
					f'"{filename}"\n' + \
					f'"{e}"\n' + \
					'Are you sure it is a kitbash project?')
				self.unregister_recent_project(filename)
			else:
				if len(self.drumkit_widgets):
					self.clear()
				self.project_filename = realpath(filename)
				self.register_recent_project()
				self.project_loading = True
				self.saved_sfz_filename = self.project_definition['saved_sfz_filename']
				self.saved_sfz_samples_mode = self.project_definition['saved_sfz_samples_mode']
				for sfzfile in self.project_definition['drumkits'].keys():
					self.load_drumkit(sfzfile)
				self.statusbar.showMessage(f'Loaded project {self.project_filename}', MESSAGE_TIMEOUT)
		else:
			self.unregister_recent_project(filename)
			DevilBox(f"Project not found: {filename}")

	def save_project(self):
		with open(self.project_filename, 'w', encoding = 'utf-8') as fh:
			json.dump(self.compile_project_def(), fh, indent="\t")
		self.register_recent_project()
		self.set_dirty(False)
		self.statusbar.showMessage(f'Saved project at {self.project_filename}', MESSAGE_TIMEOUT)

	def save_kit(self):
		kit = self.bashed_kit.simplified()
		kit.default_path = dirname(self.saved_sfz_filename)
		try:
			kit.save_as(self.saved_sfz_filename, self.saved_sfz_samples_mode)
			logging.debug('Saved bashed SFZ at %s', self.saved_sfz_filename)
			self.statusbar.showMessage(f'Saved {self.saved_sfz_filename}', MESSAGE_TIMEOUT)
		except OSError as e:
			DevilBox('Hardlinks between devices are not allowed.\n' +\
				'Choose a different path or sample mode.' if e.errno == 18 \
				else str(e))

	def register_recent_project(self):
		self.recent_projects.bump(self.project_filename)
		set_setting(KEY_RECENT_PROJECT_FOLDER, dirname(self.project_filename))
		set_setting(KEY_RECENT_PROJECTS, self.recent_projects.items)

	def unregister_recent_project(self, filename):
		self.recent_projects.remove(filename)
		set_setting(KEY_RECENT_PROJECTS, self.recent_projects.items)

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
		self.saved_sfz_filename = None
		self.saved_sfz_samples_mode = None
		self.dirty = False
		for widget in reversed(self.drumkit_widgets):
			self.slot_remove_drumkit(widget)
		self.statusbar.showMessage('Cleared', MESSAGE_TIMEOUT)
		self.set_dirty(False)

	# -----------------------------------------------------------------
	# Quit / close / signals

	# pylint: disable-next = invalid-name
	def closeEvent(self, event):
		"""
		PyQt closeEvent overload.
		"""
		if self.okay_to_clear():
			self.audio.quit()
			self.save_geometry()
			if exists(self.tempfile):
				unlink(self.tempfile)
			logging.debug('Total %d xruns', self.current_xruns)
			event.accept()
		else:
			event.ignore()

	def system_signal(self, *_):
		"""
		Catch system signals SIGINT and SIGTERM
		"""
		logging.debug('Caught signal - shutting down')
		self.statusbar.showMessage('Caught signal - shutting down', MESSAGE_TIMEOUT)
		self.close()

	# -----------------------------------------------------------------
	# JACK audio / source / sink management

	@pyqtSlot(int)
	def slot_jack_ready(self, samplerate):
		self.lbl_jack_state.setText(f'JACK samplerate: {samplerate}')

	@pyqtSlot()
	def slot_jack_down(self):
		self.lbl_jack_state.setText('JACK is down')

	@pyqtSlot()
	def slot_sources_changed(self):
		with SigBlock(self.cmb_midi_srcs):
			self.cmb_midi_srcs.clear()
			self.cmb_midi_srcs.addItem('')
			for port in self.audio.conn_man.output_ports():
				if port.is_midi:
					self.cmb_midi_srcs.addItem(port.name)
			if self.audio.synth.connected_midi_src_port:
				self.cmb_midi_srcs.setCurrentText(self.audio.midi_src)

	@pyqtSlot()
	def slot_sinks_changed(self):
		with SigBlock(self.cmb_audio_sinks):
			self.cmb_audio_sinks.clear()
			self.cmb_audio_sinks.addItem('')
			valid_clients = set(
				port.client_name for port in self.audio.conn_man.input_ports()
				if port.is_audio )
			for client in valid_clients:
				self.cmb_audio_sinks.addItem(client)
			if self.audio.synth.connected_audio_sink_ports:
				self.cmb_audio_sinks.setCurrentText(self.audio.audio_sink)

	@pyqtSlot(str)
	def slot_midi_connected(self, port_name):
		self.statusbar.showMessage(f'Connected to "{port_name}"', MESSAGE_TIMEOUT)

	# -----------------------------------------------------------------
	# Drumkit load / delete / instrument selection

	def load_drumkit(self, filename):
		"""
		Adds a Drumkit.
		1. called at project load
		2. triggered by "Edit -> Load Drumkit" menu
		3. triggered by kits_area custom context menu
		"""
		if exists(filename):
			drumkit_widget = DrumkitWidget(filename, self)
			self.drumkit_widgets.append(drumkit_widget)
			QApplication.instance().processEvents()
			worker = KitLoader(drumkit_widget)
			worker.signals.sig_loaded.connect(self.slot_drumkit_loaded)
			self.background_threadpool.start(worker)
			if not self.project_loading:
				self.recent_drumkits.bump(filename)
				set_setting(KEY_RECENT_DRUMKIT_FOLDER, dirname(filename))
		else:
			self.recent_drumkits.remove(filename)
			DevilBox(f"File not found: {filename}")
		if not self.project_loading:
			set_setting(KEY_RECENT_DRUMKITS, self.recent_drumkits.items)

	@pyqtSlot(QObject, Drumkit)
	def slot_drumkit_loaded(self, drumkit_widget, drumkit):
		"""
		Called when KitLoader is finshed loading and interpreted SFZ.
		If ready when project_loading, applies saved selections.
		"""
		drumkit_widget.set_drumkit(drumkit)
		drumkit_widget.sig_inst_toggle.connect(self.slot_inst_toggle)
		drumkit_widget.sig_note_on.connect(self.slot_note_on)
		drumkit_widget.sig_note_off.connect(self.slot_note_off)
		drumkit_widget.sig_remove_drumkit.connect(self.slot_remove_drumkit)
		if self.project_loading:
			drumkit_widget.apply_selections(
				self.project_definition['drumkits'][drumkit_widget.sfz_filename])
			if all(drumkit_widget.ready() for drumkit_widget in self.drumkit_widgets):
				self.project_loading = False
				self.set_dirty(False)
		else:
			self.statusbar.showMessage(f'Loaded {drumkit_widget.moniker}', MESSAGE_TIMEOUT)
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
		self.drumkit_widgets.remove(drumkit_widget)
		drumkit_widget.deleteLater()
		self.statusbar.showMessage(f'Deleted {drumkit_widget.moniker}', MESSAGE_TIMEOUT)
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
		self.set_dirty()
		self.update_timer.start()
		self.statusbar.showMessage('Preparing to update ...', MESSAGE_TIMEOUT)

	@pyqtSlot()
	def slot_timer_timeout(self):
		"""
		Triggered by update_timer after changes have been made.
		"""
		worker = KitBasher(self.drumkit_widgets)
		worker.signals.sig_bashed.connect(self.slot_drumkit_bashed)
		self.background_threadpool.start(worker)

	@pyqtSlot(Drumkit)
	def slot_drumkit_bashed(self, bashed_kit):
		"""
		Triggered from KitBasher signal when bashing is finished.
		"""
		self.bashed_kit = bashed_kit
		with open(self.tempfile, 'w') as fob:
			self.bashed_kit.write(fob)
		self.audio.synth.load(self.tempfile)	# pylint: disable = no-member
		self.statusbar.showMessage('Drumkit updated', MESSAGE_TIMEOUT)

	@pyqtSlot(int)
	def slot_note_on(self, pitch):
		self.synth.noteon(0, pitch, self.spn_velocity.value())

	@pyqtSlot(int)
	def slot_note_off(self, pitch):
		self.synth.noteoff(0, pitch)

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
				get_setting(KEY_RECENT_PROJECT_FOLDER, ""),
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
			get_setting(KEY_RECENT_PROJECT_FOLDER, getcwd() \
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
		if self.saved_sfz_filename is None:
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
			int(get_setting(KEY_SAMPLES_MODE, SAMPLES_ABSPATH)) \
			if self.saved_sfz_samples_mode is None \
			else self.saved_sfz_samples_mode)
		if dlg.exec_() and dlg.selected_file:
			self.saved_sfz_filename = dlg.selected_file
			self.saved_sfz_samples_mode = dlg.samples_mode
			self.save_kit()

	@pyqtSlot()
	def slot_add_drumkit(self):
		"""
		Triggered by "Edit -> Add Drumkit" menu, and kits_area custom context menu..
		"""
		QCoreApplication.setAttribute(Qt.AA_DontUseNativeDialogs, False)
		filename = QFileDialog.getOpenFileName(self,
			"Load Drumkit",
			get_setting(KEY_RECENT_DRUMKIT_FOLDER, ''),
			"SFZ file (*.sfz)"
		)[0]
		if filename != '':
			self.load_drumkit(filename)

	@pyqtSlot()
	def slot_copy_kit_path(self):
		QApplication.instance().clipboard().setText(self.saved_sfz_filename)
		self.statusbar.showMessage(f'Copied "{self.saved_sfz_filename}" to clipboard.',
			MESSAGE_TIMEOUT)



#  end kitbash/kitbash/gui/main_window.py
