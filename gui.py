#  kitbash/gui.py
#
#  Copyright 2024 liyang <liyang@veronica>
#

import sys, os, logging, json, glob
from pprint import pprint
from functools import partial
from signal import signal, SIGINT, SIGTERM
from recent_items_list import RecentItemsList
from qt_extras import SigBlock, ShutUpQT, DevilBox
from qt_extras.list_layout import HListLayout, VListLayout
from simple_carla.qt import CarlaQt, QtPlugin
from sfzdb import SFZ

# PyQt5 imports
from PyQt5 import uic
from PyQt5.QtCore import	Qt, pyqtSignal, pyqtSlot, QObject, QPoint, QTimer, QEvent, QSettings, QThreadPool, QRunnable
from PyQt5.QtGui import		QIcon
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, QInputDialog, \
							QAction, QActionGroup, QMenu, QSpacerItem, QSizePolicy

from kitbash.drumkit import Drumkit
from kitbash.drumkit_widget import DrumKitWIdget
from kitbash.looper_widget import LooperWidget

APPLICATION_NAME = "kitbash"
FILES_TYPE = "SFZ (*.sfz)"


class MainWindow(QMainWindow):

	instance = None	# Enforce singleton

	def __new__(cls, options):
		if cls.instance is None:
			cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self, options):
		super().__init__()
		self._options = options
		my_dir = os.path.dirname(__file__)
		with ShutUpQT():
			uic.loadUi(os.path.join(my_dir, 'res', 'main_window.ui'), self)
		#self.setWindowIcon(QIcon(os.path.join(my_dir, 'res', 'icon.png')))
		self.settings = QSettings("ZenSoSo", APPLICATION_NAME)
		geometry = self.settings.value("geometry")
		if geometry is not None:
			self.restoreGeometry(geometry)
		self.recent_projects = RecentItemsList(self.settings.value("recent_projects", defaultValue=[]))
		self.recent_drumkits = RecentItemsList(self.settings.value("recent_drumkits", defaultValue=[]))

		self.looper_widget = LooperWidget(self)
		self.looper_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
		self.frm_looper.layout().addWidget(self.looper_widget)

		self.drumkit_widgets = VListLayout(end_space = 10)
		self.drumkit_widgets.setContentsMargins(0,0,0,0)
		self.drumkit_widgets.setSpacing(2)
		self.drums_scroll_contents.setLayout(self.drumkit_widgets)
		self.threadpool = QThreadPool()
		self.threadpool.setMaxThreadCount(1)

		self.fill_style_menu()
		self.load_current_style()
		self.show_hide_window_elements()
		self.connect_actions()
		signal(SIGINT, self.system_signal)
		signal(SIGTERM, self.system_signal)

		CarlaQt(APPLICATION_NAME)
		self.connect_host_callbacks()
		self.update_timer = QTimer()
		self.update_timer.setInterval(int(1 / 4 * 1000))
		self.update_timer.timeout.connect(self.slot_timer_timeout)

		self.project_file = None
		self.project_definition = None
		self.project_loading = False

		QTimer.singleShot(0, self.layout_complete)

	# -----------------------------------------------------------------
	# Setup functions:

	def show_hide_window_elements(self):
		show_looper = int(self.settings.value("show_looper", 1)) == 1
		show_looper = int(self.settings.value("show_looper", 1)) == 1
		show_statusbar = int(self.settings.value("show_statusbar", 1)) == 1
		self.frm_looper.setVisible(show_looper)
		self.frm_statusbar.setVisible(show_statusbar)
		self.action_Looper.setChecked(show_looper)
		self.action_Statusbar.setChecked(show_statusbar)
		self.action_Looper.toggled.connect(self.show_looper)
		self.action_Statusbar.toggled.connect(self.show_statusbar)
		self.action_CollapseKits.triggered.connect(self.action_collapse_kits)
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

	def connect_host_callbacks(self):
		carla = CarlaQt.instance
		carla.set_ui_parent(self)
		carla.sig_EngineStarted.connect(self.slot_EngineStarted)
		carla.sig_EngineStopped.connect(self.slot_EngineStopped)
		carla.sig_PluginRemoved.connect(self.slot_PluginRemoved)
		carla.sig_LastPluginRemoved.connect(self.slot_LastPluginRemoved)
		carla.sig_PortsChanged.connect(self.slot_PortsChanged)
		carla.sig_ProcessModeChanged.connect(self.slot_ProcessModeChanged)
		carla.sig_TransportModeChanged.connect(self.slot_TransportModeChanged)
		carla.sig_BufferSizeChanged.connect(self.slot_BufferSizeChanged)
		carla.sig_SampleRateChanged.connect(self.slot_SampleRateChanged)
		carla.sig_CancelableAction.connect(self.slot_CancelableAction)
		carla.sig_Info.connect(self.slot_Info)
		carla.sig_Error.connect(self.slot_Error)
		carla.sig_ApplicationError.connect(self.slot_ApplicationError)
		carla.sig_Quit.connect(self.slot_Quit)

	@pyqtSlot()
	def layout_complete(self):
		self.start_carla_engine()

	@pyqtSlot(str, str, bool, bool)
	def slot_group_select(self, kitname, group_id, state, ctrl_state):
		if state and not ctrl_state:
			for drumkit_widget in self.drumkit_widgets:
				if drumkit_widget.drumkit.name != kitname:
					drumkit_widget.deselect_group(group_id)

	@pyqtSlot(str, str, bool, bool)
	def slot_inst_select(self, kitname, inst_id, state, ctrl_state):
		if state and not ctrl_state:
			for drumkit_widget in self.drumkit_widgets:
				if drumkit_widget.drumkit.name != kitname:
					drumkit_widget.deselect_inst(inst_id)

	# -----------------------------------------------------------------
	# Style functions:

	def fill_style_menu(self):
		"""
		Fill a style menu with the list of discovered styles
		(see discover styles)
		"""
		self._styles = { '.'.join(os.path.basename(path).split('.')[:-1]): path \
						for path in glob.glob(os.path.join(my_dir, 'styles', '*.css')) }
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
		raise NotImplemented()

	def load_project(self, filename):
		if os.path.exists(filename):
			logging.debug("LOADING PROJECT " + filename)
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

	def is_clear(self):
		return len(self.drumkit_widgets) == 0

	def clear(self):
		logging.debug("CLEARING")
		for widget in reversed(self.drumkit_widgets):
			widget.remove()

	def execute_project_load(self):
		self.project_clearing = False
		self.project_loading = True
		self.set_dirty(False)
		try:
			with open(self.project_file, 'r') as fh:
				self.project_definition = json.load(fh)
		except json.JSONDecodeError as e:
			DevilBox('There was a problem decoding "{0}"' + \
				'\nAre you sure it is a kitbash project?'.format(self.project_file))
		else:
			self.recent_projects.select(self.project_file)
			self.settings.setValue("recent_project_folder", os.path.dirname(self.project_file))
			self.settings.setValue("recent_projects", self.recent_projects.items)
			for drumkit in self.project_definition:
				self.load_drumkit(drumkit.sfz_filename)

	def load_drumkit(self, filename):
		if os.path.exists(filename):
			widget = DrumKitWIdget(filename, self)
			self.drumkit_widgets.append(widget)
			widget.sig_group_select.connect(self.slot_group_select)
			widget.sig_inst_select.connect(self.slot_inst_select)
			worker = KitLoader(filename)
			worker.signals.sig_complete.connect(self.drumkit_loaded)
			self.threadpool.start(worker)
			self.recent_drumkits.select(filename)
			self.settings.setValue("recent_drumkit_folder", os.path.dirname(filename))
		else:
			self.recent_drumkits.remove(filename)
			DevilBox(f"File not found: {filename}")
		self.settings.setValue("recent_drumkits", self.recent_drumkits.items)

	@pyqtSlot(Drumkit)
	def drumkit_loaded(self, drumkit):
		saved_selections = self.project_definition[drumkit.filename] \
			if self.project_loading and drumkit.filename in self.project_definition \
			else None
		self.drumkit_widget(drumkit.filename).drumkit_loaded(drumkit, saved_selections)
		if self.project_loading:
			for widget in self.drumkit_widgets:
				if widget.drumkit is None:
					return
			self.project_loading = False

	def drumkit_widget(self, filename):
		for widget in self.drumkit_widgets:
			if widget.filename == filename:
				return widget

	def set_dirty(self, state=True):
		self._dirty = state
		title = APPLICATION_NAME if self.project_file is None else f"{self.project_file} [{APPLICATION_NAME}]"
		self.setWindowTitle("* " + title if self._dirty else title)

	def permission_to_clear(self):
		if self.is_clear():
			return True
		dlg = QMessageBox(
			QMessageBox.Warning,
			"Verify clear all",
			"Are you sure you want to remove all existing plugins?",
			QMessageBox.Ok | QMessageBox.Cancel,
			self
		)
		return dlg.exec() == QMessageBox.Ok

	def setup_after_load(self):
		# Called after loading a saved project:
		pass

	# -----------------------------------------------------------------
	# QMainWindow overloads (see also: "timerEvent")

	def eventFilter(self, source, event):
		if event.type() == QEvent.KeyPress:
			key = event.key()
		return super().eventFilter(source, event)

	def closeEvent(self, event):
		logging.debug('MainWindow close()')
		CarlaQt.instance.delete()
		self.settings.setValue("geometry", self.saveGeometry())
		self.save_geometry()
		self.settings.sync()
		event.accept()

	# -----------------------------------------------------------------
	# Signal handler

	def system_signal(self, sig, frame):
		logging.debug("Caught signal - shutting down")
		self.close()

	# -----------------------------------------------------------------
	# UI handling slots:

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
		with open(self.project_file, 'w') as fh:
			json.dump(self.compile_sfz_parts(), fh, indent="\t")
			self.set_dirty(False)

	@pyqtSlot()
	def action_load_kit(self):
		filename = QFileDialog.getOpenFileName(self,
			"Load SFZ Drumkit",
			self.settings.value("recent_sfz_folder", ""),
			"SFZ file (*.sfz)"
		)[0]
		if filename != "":
			self.load_drumkit(filename)

	# -----------------------------------------------------------------
	# Carla management:

	def start_carla_engine(self):
		if CarlaQt.instance.engine_init("JACK"):
			return logging.debug('======= Engine started ========')
		audioError = CarlaQt.instance.get_last_error()
		if audioError:
			DevilBox("Could not connect to JACK audio backend; possible reasons:\n%s" % audioError)
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

	@pyqtSlot()
	def slot_PortsChanged(self):
		pass

	@pyqtSlot(QObject)
	def slot_PluginRemoved(self, plugin):
		pass

	@pyqtSlot()
	def slot_LastPluginRemoved(self):
		logging.debug('Got sig_LastPluginRemoved')
		pass

	@pyqtSlot(int, int, int, int, float, str)
	def slot_EngineStarted(self, plugin_count, process_mode, transport_mode, buffer_size, sample_rate, driver_name):
		self.update_timer.start()

	@pyqtSlot()
	def slot_EngineStopped(self):
		logging.debug("======= Engine stopped ========")
		self.update_timer.stop()
		self.refresh_xruns(0.0, 0)

	@pyqtSlot(int)
	def slot_ProcessModeChanged(self, int):
		pass

	@pyqtSlot(int, str)
	def slot_TransportModeChanged(self, transport_mode, extra_info):
		logging.debug(transport_mode)
		logging.debug(extra_info)

	@pyqtSlot(int)
	def slot_BufferSizeChanged(self, size):
		self.refresh_buffer_size(size)

	@pyqtSlot(float)
	def slot_SampleRateChanged(self, rate):
		self.refresh_sample_rate(int(rate))

	@pyqtSlot(int, bool, str)
	def slot_CancelableAction(self, plugin_id, started, action):
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

	@pyqtSlot()
	def slot_ProjectLoadFinished(self):
		logging.debug("project loading finished")

	@pyqtSlot(str)
	def slot_Info(self, info):
		QMessageBox.information(self, "Information", info)

	@pyqtSlot(str)
	def slot_Error(self, error):
		DevilBox("Error:" + error)

	@pyqtSlot(str, str, str, int)
	def slot_ApplicationError(self, err_type, err_message, err_file, err_line):
		DevilBox('{0} "{1}" in {2}, line {3}'.format(err_type, err_message, err_file, err_line))

	@pyqtSlot()
	def slot_Quit(self):
		#self.kill_timers()
		self._project_is_loading = False


class KitLoaderSignals(QObject):

	sig_complete = pyqtSignal(Drumkit)


class KitLoader(QRunnable):

	def __init__(self, sfz_filename):
		super().__init__()
		self.sfz_filename = sfz_filename
		self.signals = KitLoaderSignals()

	@pyqtSlot()
	def run(self):
		drumkit = Drumkit(self.sfz_filename)
		self.signals.sig_complete.emit(drumkit)



# -----------------------------------------------------------------
# main()

def main():
	import argparse
	global my_dir

	p = argparse.ArgumentParser()
	p.epilog = """
	Write your help text!
	"""
	p.add_argument('Filename', type=str, nargs='*', help='SFZ file[s] to include at startup')
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

	my_dir = os.path.split(os.path.abspath(__file__))[0]
	app = QApplication([])
	main_window = MainWindow(options)
	main_window.show()
	sys.exit(app.exec())


if __name__ == "__main__":
	sys.exit(main())


#  end kitbash/gui.py
