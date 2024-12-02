#  kitbash/gui.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys, os, argparse, logging, json, glob
from functools import partial
from signal import signal, SIGINT, SIGTERM
from recent_items_list import RecentItemsList
from qt_extras import ShutUpQT, DevilBox
from qt_extras.list_layout import VListLayout
from simple_carla import PatchbayClient, PatchbayPort
from simple_carla.qt import CarlaQt
from midi_notes import MIDI_DRUM_PITCHES
from jack import JackError

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
	QSize,
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

from jack_midi_looper import Pause
from jack_midi_looper.looper_widget import LooperWidget

from kitbash import (
	loops_database,
	APPLICATION_NAME,
	PACKAGE_DIR
)
from kitbash.looper import MultiPortLooper
from kitbash.drumkit import Drumkit
from kitbash.drumkit_widget import DrumKitWidget
from kitbash.icons import (
	PIXMAP_AUDIO_OFF,
	PIXMAP_AUDIO_ON
)



class MainWindow(QMainWindow):

	instance = None	# Enforce singleton

	def __new__(cls, options):
		if cls.instance is None:
			cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self, options):
		super().__init__()
		self.options = options
		with ShutUpQT():
			uic.loadUi(os.path.join(PACKAGE_DIR, 'res', 'main_window.ui'), self)
		#self.setWindowIcon(QIcon(os.path.join(PACKAGE_DIR, 'res', 'icon.png')))
		self.settings = QSettings("ZenSoSo", APPLICATION_NAME)
		geometry = self.settings.value("geometry")
		if geometry is not None:
			self.restoreGeometry(geometry)
		self.recent_projects = RecentItemsList(self.settings.value("recent_projects", defaultValue=[]))
		self.recent_drumkits = RecentItemsList(self.settings.value("recent_drumkits", defaultValue=[]))

		if self.options.no_audio:
			self.frm_looper.hide()
			self.looper = None
			self.lbl_audio_indicator.hide()

		else:
			self.looper = MultiPortLooper()
			self.looper_widget = LooperWidget(self, loops_database(), self.looper)
			self.looper_widget.single_loop = True
			self.looper_widget.columns = 8
			self.looper_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
			self.frm_looper.layout().addWidget(self.looper_widget)
			self.looper.signals.sig_state_changed.connect(self.looper_widget.play_button.setChecked)

			CarlaQt(APPLICATION_NAME)
			self.connect_host_callbacks()
			self.update_timer = QTimer()
			self.update_timer.setInterval(int(1 / 4 * 1000))
			self.update_timer.timeout.connect(self.slot_timer_timeout)

			self.looper_port_widgets = {}	# dict of DrumKitWidget, indexed on Jack.OwnMidiPort.name
			self.audio_playback_client = None

			self.lbl_audio_indicator.setPixmap(PIXMAP_AUDIO_OFF())

		self.drumkit_widgets = VListLayout(end_space = 10)
		self.drumkit_widgets.setContentsMargins(0,0,0,0)
		self.drumkit_widgets.setSpacing(2)
		self.kits_area.setLayout(self.drumkit_widgets)
		self.threadpool = QThreadPool()
		self.threadpool.setMaxThreadCount(1)

		self.fill_style_menu()
		self.load_current_style()
		self.show_hide_window_elements()
		self.connect_actions()
		signal(SIGINT, self.system_signal)
		signal(SIGTERM, self.system_signal)

		self.project_file = None
		self.project_definition = None
		self.project_loading = False

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

	def connect_host_callbacks(self):
		carla = CarlaQt.instance
		carla.set_ui_parent(self)
		carla.sig_EngineStarted.connect(self.slot_engine_started)
		carla.sig_EngineStopped.connect(self.slot_engine_stopped)
		carla.sig_PluginRemoved.connect(self.slot_plugin_removed)
		carla.sig_LastPluginRemoved.connect(self.slot_last_plugin_removed)
		carla.sig_PatchbayClientAdded.connect(self.slot_patchbay_client_added)
		carla.sig_PatchbayClientRemoved.connect(self.slot_patchbay_client_removed)
		carla.sig_PatchbayPortAdded.connect(self.slot_patchbay_port_added)
		carla.sig_PatchbayPortRemoved.connect(self.slot_patchbay_port_removed)
		carla.sig_ProcessModeChanged.connect(self.slot_process_mode_changed)
		carla.sig_TransportModeChanged.connect(self.slot_transport_mode_changed)
		carla.sig_BufferSizeChanged.connect(self.slot_buffersize_changed)
		carla.sig_SampleRateChanged.connect(self.slot_samplerate_changed)
		carla.sig_CancelableAction.connect(self.slot_carla_cancel)
		carla.sig_Info.connect(self.slot_carla_info)
		carla.sig_Error.connect(self.slot_carla_error)
		carla.sig_ApplicationError.connect(self.slot_application_error)
		carla.sig_Quit.connect(self.slot_quit)

	@pyqtSlot()
	def layout_complete(self):
		if not self.options.no_audio:
			self.start_carla_engine()

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
		if self.looper:
			with Pause(self.looper):
				drumkit_widget.set_looper_jack_port(*self.looper.add_port())
			self.looper_port_widgets[drumkit_widget.port_name] = drumkit_widget
			if self.audio_playback_client is None:
				self.select_audio_playback_client()
			drumkit_widget.synth.connect_outputs_to(self.audio_playback_client)

	@pyqtSlot(QObject)
	def slot_remove_drumkit(self, drumkit_widget):
		if self.looper:
			self.looper.delete_port(drumkit_widget.port_number)
			drumkit_widget.synth.delete()
		self.drumkit_widgets.remove(drumkit_widget)
		drumkit_widget.deleteLater()
		self.set_dirty()

	def drumkit_widget(self, filename):
		for widget in self.drumkit_widgets:
			if widget.filename == filename:
				return widget

	def select_audio_playback_client(self):
		client_name = self.looper.first_physical_playback_client()
		if client_name is None:
			logging.warning('No physical playback client found')
		else:
			logging.debug('Found physical playback client "%s"', client_name)
			self.audio_playback_client = CarlaQt.instance.system_client_by_name(client_name)
			if self.audio_playback_client is None:
				return logging.warning('Carla did not find system playback client "%s"', client_name)
			self.lbl_audio_client.setText(client_name)

	# -----------------------------------------------------------------
	# QMainWindow overloads (see also: "timerEvent")

	def eventFilter(self, source, event):
		if event.type() == QEvent.KeyPress:
			key = event.key()
		return super().eventFilter(source, event)

	def closeEvent(self, event):
		logging.debug('MainWindow close()')
		if not self.options.no_audio:
			CarlaQt.instance.delete()
		self.settings.setValue("geometry", self.saveGeometry())
		self.settings.sync()
		event.accept()

	# -----------------------------------------------------------------
	# Signal handler

	def system_signal(self, sig, frame):
		logging.debug('Caught signal - shutting down')
		self.close()

	# -----------------------------------------------------------------
	# UI handling slots:

	@pyqtSlot(bool)
	def slot_preview_toggle(state):
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
				action = QAction('Remove "%s"' % clicked_drumkit_widget.moniker, self)
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

	# -----------------------------------------------------------------
	# Carla management:

	def start_carla_engine(self):
		if CarlaQt.instance.engine_init("JACK"):
			logging.debug('======= Engine started ========')
		else:
			audio_error = CarlaQt.instance.get_last_error()
			if audio_error:
				DevilBox("Could not connect to JACK audio backend; possible reasons:\n%s" % audio_error)
			else:
				DevilBox("Could not connect to JACK audio backend")

	@pyqtSlot()
	def slot_timer_timeout(self):
		info = CarlaQt.instance.get_runtime_engine_info()
		self.refresh_xruns(info['load'], info['xruns'])

	def refresh_xruns(self, load, xruns):
		pass

	def refresh_buffer_size(self, size):
		pass

	def refresh_sample_rate(self, rate):
		pass

	@pyqtSlot(bool)
	def slot_clear_xruns(self):
		CarlaQt.instance.clear_engine_xruns()

	@pyqtSlot()
	def slot_cancel_action_click(self):
		CarlaQt.instance.cancel_engine_action()

	# -----------------------------------------------------------------
	# Slots which catch signals from Carla

	@pyqtSlot(PatchbayClient)
	def slot_patchbay_client_added(self, client):
		pass

	@pyqtSlot(PatchbayClient)
	def slot_patchbay_client_removed(self, client):
		logging.debug('slot_patchbay_client_removed %s', client)
		if client is self.audio_playback_client:
			self.audio_playback_client = None

	@pyqtSlot(PatchbayPort)
	def slot_patchbay_port_added(self, port):
		if port.port_name in self.looper_port_widgets:
			self.looper_port_widgets[port.port_name].set_carla_looper_port(port)

	@pyqtSlot(PatchbayPort)
	def slot_patchbay_port_removed(self, port):
		pass

	@pyqtSlot(QObject)
	def slot_plugin_removed(self, plugin):
		pass

	@pyqtSlot()
	def slot_last_plugin_removed(self):
		logging.debug('Got sig_LastPluginRemoved')
		pass

	@pyqtSlot(int, int, int, int, float, str)
	def slot_engine_started(self, plugin_count, process_mode, transport_mode, buffer_size, sample_rate, driver_name):
		self.update_timer.start()
		self.select_audio_playback_client()

	@pyqtSlot()
	def slot_engine_stopped(self):
		logging.debug('======= Engine stopped ========')
		self.update_timer.stop()
		self.refresh_xruns(0.0, 0)

	@pyqtSlot(int)
	def slot_process_mode_changed(self, process_mode):
		pass

	@pyqtSlot(int, str)
	def slot_transport_mode_changed(self, transport_mode, extra_info):
		logging.debug(transport_mode)
		logging.debug(extra_info)

	@pyqtSlot(int)
	def slot_buffersize_changed(self, size):
		self.refresh_buffer_size(size)

	@pyqtSlot(float)
	def slot_samplerate_changed(self, rate):
		self.refresh_sample_rate(int(rate))

	@pyqtSlot(int, bool, str)
	def slot_carla_cancel(self, plugin_id, started, action):
		if self._cancel_action_dialog is not None:
			self._cancel_action_dialog.close()
		if started:
			self._cancel_action_dialog = QMessageBox(self)
			self._cancel_action_dialog.setIcon(QMessageBox.Information)
			self._cancel_action_dialog.setWindowTitle(self.tr("Action in progress"))
			self._cancel_action_dialog.setText(action)
			self._cancel_action_dialog.setInformativeText(self.tr("An action is in progress, please wait..."))
			self._cancel_action_dialog.setStandardButtons(QMessageBox.Cancel)
			self._cancel_action_dialog.setDefaultButton(QMessageBox.Cancel)
			self._cancel_action_dialog.buttonClicked.connect(self.slot_cancel_action_click)
			self._cancel_action_dialog.show()
		else:
			self._cancel_action_dialog = None

	@pyqtSlot(str)
	def slot_carla_info(self, info):
		QMessageBox.information(self, "Information", info)

	@pyqtSlot(str)
	def slot_carla_error(self, error):
		DevilBox("Error:" + error)

	@pyqtSlot(str, str, str, int)
	def slot_application_error(self, err_type, err_message, err_file, err_line):
		DevilBox(f'{err_type} "{err_message}" in {err_file}, line {err_line}')

	@pyqtSlot()
	def slot_quit(self):
		#self.kill_timers()
		self._project_is_loading = False


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
	p.add_argument("--no-audio", "-q", action="store_true", help="Do not load Carla and Jack drivers")
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
	except JackError:
		DevilBox('Could not connect to JACK server. Is it running?')
		sys.exit(1)
	main_window.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	sys.exit(main())


#  end kitbash/gui.py
