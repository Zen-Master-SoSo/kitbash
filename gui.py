#  kitbash/gui.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys
import os
import argparse
import logging
import json
import glob
from tempfile import mkstemp
from functools import partial
from signal import signal, SIGINT, SIGTERM
from recent_items_list import RecentItemsList
from qt_extras import ShutUpQT, DevilBox
from qt_extras.list_layout import VListLayout
from midi_notes import MIDI_DRUM_PITCHES
from jack_midi_looper.looper_widget import LooperWidget

# PyQt5 imports
from PyQt5 import uic
from PyQt5.QtCore import (
	Qt,
	pyqtSignal,
	pyqtSlot,
	QObject,
	QTimer,
	QEvent,
	QSettings,
	QThreadPool,
	QRunnable,
	QPoint
)
from PyQt5.QtWidgets import (
	QApplication,
	QMainWindow,
	QMessageBox,
	QFileDialog,
	QAction,
	QActionGroup,
	QMenu,
	QSizePolicy
)

from kitbash import (
	loops_database,
	APPLICATION_NAME,
	PACKAGE_DIR
)
from kitbash.looper import MultiPortLooper
from kitbash.drumkit import Drumkit
from kitbash.drumkit_widget import DrumKitWidget
from kitbash.synth import Synth
from kitbash.icons import (
	PIXMAP_AUDIO_OFF,
	PIXMAP_AUDIO_ON
)
from kitbash.connection_manager import (
	JackConnectionManager,
	JackPort,
	JackConnectError
)


class MainWindow(QMainWindow):

	instance = None
	options = None

	def __new__(cls, options):
		if cls.instance is None:
			cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self, options):
		if not self.options is None:
			return
		self.options = options
		super().__init__()
		with ShutUpQT():
			uic.loadUi(os.path.join(PACKAGE_DIR, 'res', 'main_window.ui'), self)
		#self.setWindowIcon(QIcon(os.path.join(PACKAGE_DIR, 'res', 'icon.png')))
		self.settings = QSettings("ZenSoSo", APPLICATION_NAME)
		geometry = self.settings.value("geometry")
		if geometry is not None:
			self.restoreGeometry(geometry)
		self.recent_projects = RecentItemsList(self.settings.value("recent_projects", defaultValue=[]))
		self.recent_drumkits = RecentItemsList(self.settings.value("recent_drumkits", defaultValue=[]))
		self.project_file = None
		self.project_definition = None
		self.project_clearing = False
		self.project_loading = False
		self._dirty = False

		signal(SIGINT, self.system_signal)
		signal(SIGTERM, self.system_signal)

		self.threadpool = QThreadPool()
		self.threadpool.setMaxThreadCount(2)

		self.fill_style_menu()
		self.load_current_style()
		self.show_hide_window_elements()
		self.connect_actions()

		self.drumkit_widgets = VListLayout(end_space = 10)
		self.drumkit_widgets.setContentsMargins(0,0,0,0)
		self.drumkit_widgets.setSpacing(2)
		self.kits_area.setLayout(self.drumkit_widgets)

		if self.options.no_audio:
			self.conn_man = None
			self.looper = None
			self.synth = None
			self.frm_looper.hide()
			self.lbl_audio_indicator.hide()

		else:
			# Setup JackConnectionManager
			self.conn_man = JackConnectionManager()
			self.conn_man.sig_error.connect(self.slot_jack_error)
			self.conn_man.sig_port_registration.connect(self.slot_jack_port_registration)
			self.conn_man.sig_port_connect.connect(self.slot_jack_port_connect)
			self.conn_man.sig_port_rename.connect(self.slot_jack_port_rename)
			self.conn_man.sig_xrun.connect(self.slot_jack_xrun)
			self.conn_man.sig_shutdown.connect(self.slot_jack_shutdown)
			# Select audio playback client:
			playback_clients = self.conn_man.playback_clients()
			if playback_clients:
				client_name = playback_clients[0]
				self.lbl_audio_client.setText(client_name)
			else:
				logging.warning('No physical playback client found')
			# Setup looper
			self.looper = MultiPortLooper()
			self.looper_widget = LooperWidget(self, loops_database(), self.looper)
			self.looper_widget.single_loop = True
			self.looper_widget.columns = 8
			self.looper_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
			self.looper.signals.sig_state_changed.connect(self.looper_widget.play_button.setChecked)
			self.looper_port_widgets = {}	# dict of DrumKitWidget, indexed on Jack.OwnMidiPort.name
			# Setup synth - see slot_jack_port_registration
			self.synth = Synth()
			self.synth.sig_ready.connect(self.synth_ready)
			self.create_bashed_sfz()
			# Modify UI
			self.frm_looper.layout().addWidget(self.looper_widget)
			self.lbl_audio_indicator.setPixmap(PIXMAP_AUDIO_OFF())

		QTimer.singleShot(0, self.layout_complete)

	# -----------------------------------------------------------------
	# Setup functions:

	def show_hide_window_elements(self):
		show_looper = int(self.settings.value("show_looper", 1)) == 1
		show_statusbar = int(self.settings.value("show_statusbar", 1)) == 1
		if self.frm_looper:
			self.frm_looper.setVisible(show_looper)
			self.action_Looper.setChecked(show_looper)
			self.action_Looper.toggled.connect(self.show_looper)
		else:
			self.action_Looper.setEnabled(False)
		self.frm_statusbar.setVisible(show_statusbar)
		self.action_Statusbar.setChecked(show_statusbar)
		self.action_Statusbar.toggled.connect(self.show_statusbar)
		self.action_CollapseKits.triggered.connect(self.action_collapse_kits)
		self.action_CollapseKits.setEnabled(False)
		self.action_CollapseKits.setChecked(False)

	def connect_actions(self):
		# Menu actions
		self.action_NewProject.triggered.connect(self.action_new_project)
		self.action_OpenProject.triggered.connect(self.action_open_project)
		self.action_SaveProject.triggered.connect(self.action_save_project)
		self.action_LoadKit.triggered.connect(self.action_load_kit)
		self.action_ReloadStyle.triggered.connect(self.load_current_style)
		self.menu_RecentProject.aboutToShow.connect(self.action_show_recent_projects)
		self.menu_RecentDrumkits.aboutToShow.connect(self.action_show_recent_drumkits)
		self.kits_area.setContextMenuPolicy(Qt.CustomContextMenu)
		self.kits_area.customContextMenuRequested.connect(self.slot_kits_context_menu)
		self.b_preview.toggled.connect(self.slot_preview_toggle)

	@pyqtSlot()
	def layout_complete(self):
		pass

	@pyqtSlot(QObject, str, bool, bool)
	def slot_inst_toggle(self, source_widget, inst_id, state, ctrl_state):
		if state and not ctrl_state:
			for drumkit_widget in self.drumkit_widgets:
				if not drumkit_widget is source_widget:
					drumkit_widget.deselect_instrument(inst_id)
		elif not state:
			source_widget.deselect_parent_group(inst_id)
		if self.looper:
			self.looper.set_mapping(
				MIDI_DRUM_PITCHES[inst_id],
				source_widget.port_number if state else None)
		self.set_dirty()

	# -----------------------------------------------------------------
	# Style functions:

	def fill_style_menu(self):
		"""
		Fill a style menu with the list of discovered styles
		(see discover styles)
		"""
		self._styles = { '.'.join(os.path.basename(path).split('.')[:-1]): path \
						for path in glob.glob(os.path.join(PACKAGE_DIR, 'styles', '*.css')) }
		current_style = self.settings.value("style")
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
		self.settings.setValue('style', style)
		self.load_current_style()

	@pyqtSlot(bool)
	def load_current_style(self):
		"""
		Loads (or reloads) the current style defined in settings.
		"""
		style = self.settings.value("style", "system")
		with open(self._styles[style], 'r') as cssfile:
			QApplication.instance().setStyleSheet(cssfile.read())

	# -----------------------------------------------------------------
	# Project loading / saving:

	def compile_sfz_parts(self):
		raise NotImplementedError()

	def set_dirty(self, state=True):
		if not self.project_loading:
			self._dirty = state
			title = APPLICATION_NAME if self.project_file is None else f"{self.project_file} [{APPLICATION_NAME}]"
			self.setWindowTitle("* " + title if self._dirty else title)

	def compile_project_def(self):
		return {
			widget.filename : widget.saved_selections() \
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
			self.settings.setValue("recent_projects", self.recent_projects.items)
			DevilBox(f"Project not found: {filename}")

	def save_project(self):
		with open(self.project_file, 'w') as fh:
			json.dump(self.compile_project_def(), fh, indent="\t")
		self.register_recent_project()
		self.set_dirty(False)

	def register_recent_project(self):
		self.recent_projects.select(self.project_file)
		self.settings.setValue("recent_project_folder", os.path.dirname(self.project_file))
		self.settings.setValue("recent_projects", self.recent_projects.items)

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
			DevilBox('There was a problem decoding "{0}"' + \
				'\nAre you sure it is a kitbash project?'.format(self.project_file))
		else:
			self.register_recent_project()
			for filename in self.project_definition.keys():
				self.load_drumkit(filename)

	def check_project_load_complete(self):
		"""
		Determine if project loading is complete, reset "self.project_loading".
		Returns True if complete
		"""
		if any(widget is None for widget in self.drumkit_widgets):
			return False
		self.project_loading = False
		self.set_dirty(False)
		return True

	def load_drumkit(self, filename):
		if os.path.exists(filename):
			drumkit_widget = DrumKitWidget(filename, self)
			self.drumkit_widgets.append(drumkit_widget)
			drumkit_widget.sig_inst_toggle.connect(self.slot_inst_toggle)
			drumkit_widget.sig_synth_ready.connect(self.drumkit_synth_ready)
			drumkit_widget.sig_remove_drumkit.connect(self.slot_remove_drumkit)
			worker = KitLoader(drumkit_widget)
			worker.signals.sig_complete.connect(self.drumkit_loaded)
			self.threadpool.start(worker)
			self.recent_drumkits.select(filename)
			self.settings.setValue("recent_drumkit_folder", os.path.dirname(filename))
			self.set_dirty()
		else:
			self.recent_drumkits.remove(filename)
			DevilBox(f"File not found: {filename}")
		self.settings.setValue("recent_drumkits", self.recent_drumkits.items)

	@pyqtSlot(DrumKitWidget)
	def drumkit_loaded(self, drumkit_widget):
		"""
		Called from KitLoader when it is finished loading.
		Triggers filling of the DrumKitWidget, among other things.
		"""
		drumkit_widget.drumkit_loaded()
		self.action_CollapseKits.setEnabled(True)
		if self.project_loading:
			drumkit_widget.apply_selections(self.project_definition[drumkit_widget.filename])
			self.check_project_load_complete()

	@pyqtSlot(QObject)
	def drumkit_synth_ready(self, drumkit_widget):
		logging.debug('%s synth ready', drumkit_widget)
		drumkit_widget.port_number, drumkit_widget.port_name = self.looper.add_port()
		self.looper_port_widgets[drumkit_widget.port_name] = drumkit_widget
		src_port = self.conn_man.get_port_by_name(drumkit_widget.port_name)
		if src_port:
			self.conn_man.connect(src_port, drumkit_widget.synth.midi_in_port)
		else:
			logging.error('Did not find %s synth port "%s"', drumkit_widget, drumkit_widget.port_name)

	@pyqtSlot(QObject)
	def slot_remove_drumkit(self, drumkit_widget):
		if self.looper:
			self.looper.delete_port(drumkit_widget.port_number)
			drumkit_widget.synth.quit()
		self.drumkit_widgets.remove(drumkit_widget)
		drumkit_widget.deleteLater()
		self.set_dirty()

	def drumkit_widget(self, filename):
		for widget in self.drumkit_widgets:
			if widget.filename == filename:
				return widget

	@pyqtSlot()
	def synth_ready(self):
		"""
		Received from (Synth) self.synth when ready to play.
		"""
		src_port = self.conn_man.get_port_by_name('looper:bashed')
		if src_port:
			self.conn_man.connect(src_port, self.synth.midi_in_port)
		else:
			logging.error('Did not find %s synth port "%s"', self, 'looper:bashed')

	def create_bashed_sfz(self):
		bashed = Drumkit()
		for drumkit_widget in self.drumkit_widgets:
			for inst_id in drumkit_widget.selected_instrument_ids():
				bashed.import_instrument(inst_id, drumkit_widget.drumkit)
		fh, self.bashed_sfz_filename = mkstemp(prefix='kitbash', suffix='.sfz', text=True)
		with open(self.bashed_sfz_filename, 'w') as fob:
			bashed.write(fob)
		logging.debug('Created temporary .sfz at %s', self.bashed_sfz_filename)
		self.synth.load(self.bashed_sfz_filename)

	# -----------------------------------------------------------------
	# JackConnectionManager slots

	@pyqtSlot()
	def slot_jack_error(self, error):
		logging.error(error)

	@pyqtSlot(JackPort, int)
	def slot_jack_port_registration(self, port, action):
		logging.debug('%s %s', port, 'registered' if action else 'gone')
		if action and 'liquidsfz' in port.name:
			Synth.port_registered(port)

	@pyqtSlot(JackPort, JackPort, bool)
	def slot_jack_port_connect(self, port_a, port_b, connect):
		logging.debug('%s port connection: %s -> %s',
			('New' if connect else 'Closed'),
			port_a, port_b)

	@pyqtSlot(JackPort, str, str)
	def slot_jack_port_rename(self, port, old_name, new_name):
		logging.debug('Port %s name changed from "%s" to "%s"', port, old_name, new_name)

	@pyqtSlot()
	def slot_jack_shutdown(self):
		logging.warning('JACK server signalled shutdown')

	@pyqtSlot()
	def slot_jack_xrun(self):
		logging.warning('Xrun')

	# -----------------------------------------------------------------
	# QMainWindow overloads (see also: "timerEvent")

	def closeEvent(self, event):
		logging.debug('MainWindow close()')
		if not self.options.no_audio:
			self.synth.quit()
			for drumkit_widget in self.drumkit_widgets:
				drumkit_widget.synth.quit()
		self.settings.setValue("geometry", self.saveGeometry())
		self.settings.sync()
		event.accept()

	# -----------------------------------------------------------------
	# Signal handler

	def system_signal(self, *_):
		logging.debug('Caught signal - shutting down')
		self.close()

	# -----------------------------------------------------------------
	# UI handling slots:

	@pyqtSlot(bool)
	def slot_preview_toggle(self, state):
		"""
		Select bashed sfz for play preview; deselect all drumkits
		"""

	@pyqtSlot(QPoint)
	def slot_kits_context_menu(self, position):
		menu = QMenu()
		clicked_drumkit_widget = self.kits_area.childAt(position)
		if clicked_drumkit_widget is not None:
			while not isinstance(clicked_drumkit_widget, DrumKitWidget) and clicked_drumkit_widget.parent() is not None:
				clicked_drumkit_widget = clicked_drumkit_widget.parent()
			if isinstance(clicked_drumkit_widget, DrumKitWidget):
				action = QAction(f'Remove "{clicked_drumkit_widget.moniker}"', self)
				action.triggered.connect(partial(self.slot_remove_drumkit, clicked_drumkit_widget))
				menu.addAction(action)
		action = QAction('Add drumkit', self)
		action.triggered.connect(self.action_load_kit)
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

	@pyqtSlot(bool)
	def show_looper(self, state):
		self.frm_looper.setVisible(state)
		self.settings.setValue('show_looper', int(state))

	@pyqtSlot(bool)
	def show_statusbar(self, state):
		self.frm_statusbar.setVisible(state)
		self.settings.setValue('show_statusbar', int(state))

	@pyqtSlot()
	def action_collapse_kits(self):
		for widget in self.drumkit_widgets:
			widget.hide_button.setChecked(True)

	@pyqtSlot()
	def action_show_recent_drumkits(self):
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
	def action_show_recent_projects(self):
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
	def action_new_project(self):
		if self.permission_to_clear():
			self.clear()

	@pyqtSlot()
	def action_open_project(self):
		if not self.permission_to_clear():
			return
		filename = QFileDialog.getOpenFileName(self,
			"Open saved project",
			self.settings.value("recent_project_folder", ""),
			"Kitbash project (*.json)"
		)[0]
		if filename != "":
			self.load_project(filename)

	@pyqtSlot()
	def action_save_project(self):
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
	def action_load_kit(self):
		filename = QFileDialog.getOpenFileName(self,
			"Load SFZ Drumkit",
			self.settings.value("recent_drumkit_folder", ""),
			"SFZ file (*.sfz)"
		)[0]
		if filename != "":
			self.load_drumkit(filename)

	@pyqtSlot()
	def slot_timer_timeout(self):
		pass

	def refresh_xruns(self, load, xruns):
		pass

	def refresh_buffer_size(self, size):
		pass

	def refresh_sample_rate(self, rate):
		pass


class KitLoaderSignals(QObject):

	sig_complete = pyqtSignal(DrumKitWidget)


class KitLoader(QRunnable):

	def __init__(self, drumkit_widget):
		super().__init__()
		self.drumkit_widget = drumkit_widget
		self.signals = KitLoaderSignals()

	@pyqtSlot()
	def run(self):
		self.drumkit_widget.drumkit = Drumkit(self.drumkit_widget.filename)
		self.signals.sig_complete.emit(self.drumkit_widget)


# -----------------------------------------------------------------
# main()

def main():

	p = argparse.ArgumentParser()
	p.epilog = """
	Write your help text!
	"""
	p.add_argument('Filename', type=str, nargs='*', help='SFZ file[s] to include at startup')
	p.add_argument("--no-audio", "-q", action="store_true", help="Do not load LiquidSFZ and Jack interfaces")
	p.add_argument("--log-file", "-l", type=str, help="Log to this file")
	p.add_argument("--verbose", "-v", action="store_true", help="Show more detailed debug information")
	options = p.parse_args()

	#log_level = logging.DEBUG if options.verbose else logging.ERROR
	log_level = logging.DEBUG
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
