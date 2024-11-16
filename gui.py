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
from simple_carla.qt import CarlaQt, QtPlugin, QtWidgetPlugin
from sfzdb import SFZ

# PyQt5 imports
from PyQt5 import uic
from PyQt5.QtCore import	Qt, pyqtSignal, pyqtSlot, QObject, QPoint, QTimer, QEvent, QSettings, QThreadPool, QRunnable
from PyQt5.QtGui import		QIcon
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, QInputDialog, \
							QAction, QActionGroup, QMenu, QSpacerItem

from kitbash.drumkit import Drumkit
from kitbash.drum_widget import DrumWidget


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
		self.setWindowIcon(QIcon(os.path.join(my_dir, 'res', 'icon-90.png')))
		self.settings = QSettings("ZenSoSo", APPLICATION_NAME)
		geometry = self.settings.value("geometry")
		if geometry is not None:
			self.restoreGeometry(geometry)

		self.drum_widgets = VListLayout()
		self.drum_widgets.setContentsMargins(0,0,0,0)
		self.drums_scroll_contents.setLayout(self.drum_widgets)
		self.threadpool = QThreadPool()
		self.threadpool.setMaxThreadCount(1)

		self._recent_files = RecentItemsList(self.settings.value("recent_files", defaultValue=[]))
		self.fill_style_menu()
		self.load_current_style()
		self.show_hide_window_elements()
		self.connect_actions()
		signal(SIGINT, self.system_signal)
		signal(SIGTERM, self.system_signal)
		CarlaQt(APPLICATION_NAME)
		self.connect_host_callbacks()
		self.slow_timer = QTimer()
		self.slow_timer.setInterval(int(1 / 4 * 1000))
		self.slow_timer.timeout.connect(self.slot_timer_timeout)
		QTimer.singleShot(0, self.layout_complete)

	# -----------------------------------------------------------------
	# Setup functions:

	def show_hide_window_elements(self):
		show_toolbar = int(self.settings.value("show_toolbar", 1)) == 1
		show_statusbar = int(self.settings.value("show_statusbar", 1)) == 1
		#self.frm_toolbar.setVisible(show_toolbar)
		self.frm_statusbar.setVisible(show_statusbar)
		#self.action_Toolbar.setChecked(show_toolbar)
		self.action_Statusbar.setChecked(show_statusbar)
		#self.action_Toolbar.toggled.connect(self.show_toolbar)
		self.action_Statusbar.toggled.connect(self.show_statusbar)

	def connect_actions(self):
		# Menu actions
		self.action_New.triggered.connect(self.action_new)
		self.action_Open.triggered.connect(self.action_open_file)
		self.action_Save.triggered.connect(self.action_save)
		self.action_ReloadStyle.triggered.connect(self.load_current_style)
		# Pushbutton events
		#self.b_xruns.clicked.connect(self.slot_clear_xruns)
		#QApplication.instance().installEventFilter(self)

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
		import random
		for sfz_filename in random.sample(glob.glob('/home/liyang/docs/sfz/Drumsets/**/*.sfz', recursive=True), 4):
			#logging.debug('Starting worker to load ' + sfz_filename)
			worker = KitLoader(sfz_filename)
			worker.signals.sig_complete.connect(self.slot_drumkit_loaded)
			self.threadpool.start(worker)

	@pyqtSlot(Drumkit)
	def slot_drumkit_loaded(self, drumkit):
		#logging.debug('Finished loading ' + drumkit.name)
		widget = DrumWidget(drumkit)
		self.drum_widgets.append(widget)
		widget.sig_group_select.connect(self.slot_group_select)
		widget.sig_inst_select.connect(self.slot_inst_select)

	@pyqtSlot(str, str, bool, bool)
	def slot_group_select(self, kitname, group_id, state, ctrl_state):
		if state and not ctrl_state:
			for drum_widget in self.drum_widgets:
				if drum_widget.drumkit.name != kitname:
					drum_widget.deselect_group(group_id)

	@pyqtSlot(str, str, bool, bool)
	def slot_inst_select(self, kitname, inst_id, state, ctrl_state):
		if state and not ctrl_state:
			for drum_widget in self.drum_widgets:
				if drum_widget.drumkit.name != kitname:
					drum_widget.deselect_inst(inst_id)

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

	@pyqtSlot()
	def action_show_recent(self):
		"""
		Fills "recent files" menu before expanding
		Setup thusly:
			self.menuOpen_Recent.aboutToShow.connect(self.action_show_recent)
		"""
		self.menuOpen_Recent.clear()
		actions = []
		for filename in RECENT_FILES:
			action = QAction(filename, self)
			action.triggered.connect(partial(self.load_project, filename))
			actions.append(action)
		self.menuOpen_Recent.addActions(actions)

	def compile_sfz_parts(self):
		raise NotImplemented()

	def load_project(self, filename):
		logging.debug("LOADING PROJECT " + filename)
		self.project_file = filename
		self.set_dirty(False)
		if self.is_clear():
			self.cleared_to_load()
		else:
			MainWindow.project_clearing = True
			self.clear()

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

	def clear(self):
		logging.debug("CLEARING")
		for widget in reversed(self.drum_widgets):
			widget.remove()

	def cleared_to_load(self):
		MainWindow.project_loading = True
		try:
			dlg = ProjectLoadDialog(self, self.project_file)
		except json.JSONDecodeError as e:
			DevilBox('There was a problem decoding "{0}"'.format(self.project_file))
		else:
			if dlg.exec():
				self.project_file = self.project_file
				RECENT_FILES.select(self.project_file)
				self.settings.setValue("recent_project_folder", os.path.dirname(self.project_file))
				self.settings.setValue("RECENT_FILES", RECENT_FILES.items)
				self.setup_after_load()
				self.set_dirty(False)
		MainWindow.project_loading = False
		MainWindow.project_clearing = False

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
		self.settings.setValue("geometry", self.saveGeometry())
		self.save_geometry()
		self.settings.sync()
		#self.kill_timers()
		event.accept()

	# -----------------------------------------------------------------
	# Signal handler

	def system_signal(self, sig, frame):
		logging.debug("Caught signal - shutting down")
		self.close()

	# -----------------------------------------------------------------
	# UI handling slots:

	@pyqtSlot(bool)
	def show_toolbar(self, state):
		self.frm_toolbar.setVisible(state)
		self.settings.setValue('show_toolbar', int(state))

	@pyqtSlot(bool)
	def show_statusbar(self, state):
		self.frm_statusbar.setVisible(state)
		SETTINGS.setValue('show_statusbar', int(state))

	@pyqtSlot(bool)
	def action_new(self, checked):
		if self.permission_to_clear():
			self.clear()

	@pyqtSlot(bool)
	def action_open_file(self, checked):
		if not self.permission_to_clear():
			return
		filename = QFileDialog.getOpenFileName(self,
			"Open saved project",
			self.settings.value("recent_project_folder", ""),
			FILES_TYPE
		)[0]
		if filename != "":
			self.load_project(filename)
			self.project_file = filename

	@pyqtSlot(bool)
	def action_save(self, checked):
		if self.project_file is None:
			filename, _ = QFileDialog.getSaveFileName(
				self,
				"Save SFZ ...",
				"kitbash.sfz",
				FILES_TYPE
			)
			if filename:
				self.project_file = filename
			else:
				return
		with open(self.project_file, 'w') as fh:
			json.dump(self.compile_sfz_parts(), fh, indent="\t")
			self.set_dirty(False)

	# -----------------------------------------------------------------
	# Carla management:

	def start_carla_engine(self):
		if Carla.instance.engine_init("JACK", APPLICATION_NAME):
			return logging.debug('======= Engine started ========')
		audioError = Carla.instance.get_last_error()
		if audioError:
			DevilBox("Could not connect to JACK audio backend; possible reasons:\n%s" % audioError)
		else:
			DevilBox("Could not connect to JACK audio backend")

	@pyqtSlot()
	def slot_timer_timeout(self):
		info = Carla.instance.get_runtime_engine_info()
		self.refresh_xruns(info['load'], info['xruns'])

	def refresh_xruns(self, load, xruns):
		self.b_xruns.setText("%s Xrun%s" % (
			str(xruns) if (xruns >= 0) else "--",
			"" if (xruns == 1) else "s"
		))
		self.load_indicator.setValue(int(load))

	def refresh_buffer_size(self, size):
		if self._buffer_size == size:
			return
		self._buffer_size = size
		self.lbl_buffer_size.setText(str(size))

	def refresh_sample_rate(self, rate):
		if self._sample_rate == rate:
			return
		self._sample_rate = rate
		self.lbl_sample_rate.setText(str(rate))

	@pyqtSlot(bool)
	def slot_clear_xruns(self):
		Carla.instance.clear_engine_xruns()

	@pyqtSlot()
	def slot_cancel_action_click(self):
		Carla.instance.cancel_engine_action()

	# -----------------------------------------------------------------
	# Slots which catch signals from Carla

	@pyqtSlot()
	def slot_PortsChanged(self):
		pass

	@pyqtSlot(QObject)
	def slot_PluginRemoved(self, plugin):
		if isinstance(plugin, SharedPluginWidget):
			self.shared_plugin_layout.remove(plugin)
		else:
			self.track_widget(plugin.port, plugin.slot).plugin_removed(plugin)

	@pyqtSlot()
	def slot_LastPluginRemoved(self):
		logging.debug('Got sig_LastPluginRemoved')
		pass

	@pyqtSlot(int, int, int, int, float, str)
	def slot_EngineStarted(self, plugin_count, process_mode, transport_mode, buffer_size, sample_rate, driver_name):
		self.frm_frame.setEnabled(True)
		self.frm_time.setEnabled(True)
		self.frm_events.setEnabled(True)
		self.refresh_buffer_size(buffer_size)
		self.refresh_sample_rate(int(sample_rate))
		self.refresh_xruns(0.0, 0)
		self.slow_timer.start()

	@pyqtSlot()
	def slot_EngineStopped(self):
		logging.debug("======= Engine stopped ========")
		self.slow_timer.stop()
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
			filename=options.log_file,
			filemode='w',
			level= log_level,
			format=log_format
		)
	else:
		logging.basicConfig(
			level= log_level,
			format=log_format
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
