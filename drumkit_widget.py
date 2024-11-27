#  kitbash/drumkit_widget.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os, logging
from functools import partial

from PyQt5.QtCore import Qt
from PyQt5.QtCore import QObject
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QFrame
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtWidgets import QPushButton

from qt_extras import SigBlock
from kitbash.liquid import LiquidSFZ


class DrumKitWidget(QFrame):

	sig_inst_toggle = pyqtSignal(QObject, str, bool, bool)
	sig_synth_ready = pyqtSignal(QObject)
	sig_remove_drumkit = pyqtSignal(QObject)

	def __init__(self, filename, parent):
		super().__init__(parent)
		self.filename = filename
		self.carla_enable = not parent.options.no_audio
		if self.carla_enable:
			self.synth = LiquidSFZ(self.filename)
			self.synth.sig_Ready.connect(self.synth_ready)
			self.synth.add_to_carla()

		self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
		self.setFrameStyle(QFrame.Panel)
		self.setFrameShadow(QFrame.Sunken)
		self.setObjectName('drumkit_widget')

		main_layout = QVBoxLayout()
		main_layout.setContentsMargins(2,2,2,2)
		main_layout.setSpacing(0)

		frm_title = TitleFrame()
		frm_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

		top_layout = QHBoxLayout()
		top_layout.setContentsMargins(2,2,2,2)
		top_layout.setSpacing(0)

		my_dir = os.path.dirname(__file__)
		self.icon_expanded = QIcon(os.path.join(my_dir, 'res', 'group_expanded.svg'))
		self.icon_hidden = QIcon(os.path.join(my_dir, 'res', 'group_hidden.svg'))

		self.hide_button = QPushButton(self)
		self.hide_button.setIcon(self.icon_expanded)
		self.hide_button.setIconSize(QSize(16,16))
		self.hide_button.setFixedWidth(20)
		self.hide_button.setFixedHeight(20)
		self.hide_button.setCheckable(True)
		self.hide_button.toggled.connect(self.hide)
		top_layout.addWidget(self.hide_button)

		self.lbl_use_count = QLabel(self)
		self.lbl_use_count.setText('(0)')
		self.lbl_use_count.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		top_layout.addWidget(self.lbl_use_count)

		label = QLabel(self)
		label.setText(self.filename)
		top_layout.addWidget(label)

		top_layout.addStretch(20)

		remove_button = QPushButton(self)
		remove_button.setIcon(QIcon.fromTheme('window-close'))
		remove_button.setIconSize(QSize(16,16))
		remove_button.clicked.connect(self.remove_clicked)
		top_layout.addWidget(remove_button)

		frm_title.setLayout(top_layout)

		main_layout.addWidget(frm_title)

		self.frm_groups = QFrame(self)
		self.groups = QHBoxLayout()
		self.groups.setContentsMargins(2,2,2,2)
		self.groups.setSpacing(0)

		self.frm_groups.setLayout(self.groups)
		main_layout.addWidget(self.frm_groups)
		self.setLayout(main_layout)

	def drumkit_loaded(self):
		"""
		Called when KitLoader is finshed loading and interpreted SFZ.
		KitLoader sets the "drumkit" attribute of this widget.
		"""
		for group in self.drumkit.percussion_groups:
			if group.empty():
				continue
			group_frame = GroupFrame(group, self)
			group_frame.group_id = group.group_id
			group_frame.group_button.clicked.connect(partial(self.group_clicked, group_frame))
			for inst in group.instruments.values():
				inst_button = InstrumentButton(inst, group_frame)
				inst_button.toggled.connect(partial(self.instrument_toggled, inst.inst_id, inst_button))
				group_frame.group_layout.addWidget(inst_button)
			group_frame.group_layout.addStretch()
			self.groups.addWidget(group_frame)

	def set_looper_jack_port(self, port_number, port_name):
		"""
		Called from gui after synth ready.
		port_number, port_name are used Jack.MidiOwnPort.register()
		"""
		self.port_number = port_number
		self.port_name = port_name

	def set_carla_looper_port(self, port):
		"""
		Called when Carla sends notification that a patchbay client has been added,
		when the client_name matches the port name from Looper.add_port().
		"""
		self.carla_looper_port = port
		for liquid_port in self.synth.midi_ins():
			port.connect_to(liquid_port)

	@pyqtSlot(QFrame)
	def group_clicked(self, group_frame):
		group_button = group_frame.findChild(GroupButton)
		for inst_button in group_frame.findChildren(InstrumentButton):
			inst_button.setChecked(group_button.isChecked())

	@pyqtSlot(str, QPushButton)
	def instrument_toggled(self, inst_id, button):
		self.sig_inst_toggle.emit(self, inst_id, button.isChecked(), self.ctrl_pressed())
		self.update_count()

	@pyqtSlot()
	def remove_clicked(self):
		self.sig_remove_drumkit.emit(self)

	@pyqtSlot(bool)
	def hide(self, state):
		if state:
			self.initial_height = self.height()
			self.frm_groups.hide()
			self.setFixedHeight(30)
			self.hide_button.setIcon(self.icon_hidden)
		else:
			self.frm_groups.show()
			self.setFixedHeight(self.initial_height)
			self.hide_button.setIcon(self.icon_expanded)

	def update_count(self):
		use_count = len([ b for b in self.frm_groups.findChildren(InstrumentButton) if b.isChecked() ])
		self.lbl_use_count.setText('(%d)' % use_count)
		font = self.lbl_use_count.font()
		font.setBold(use_count > 0)
		self.lbl_use_count.setFont(font)

	def ctrl_pressed(self):
		return QApplication.keyboardModifiers() == Qt.ControlModifier

	def deselect_parent_group(self, inst_id):
		inst_button = self.findChild(InstrumentButton, inst_id)
		inst_button.parentWidget().findChild(GroupButton).setChecked(False)

	def deselect_instrument(self, inst_id):
		button = self.findChild(InstrumentButton, inst_id)
		if button:	# May not exist, as not all Drumkits use the same instruments
			button.setChecked(False)
			button.parentWidget().findChild(GroupButton).setChecked(False)
			self.update_count()

	def saved_selections(self):
		"""
		Returns dictionary of button states.
		"""
		return {
			group_frame.group_id : {
				'group' 		: group_frame.findChild(GroupButton).isChecked(),
				'instruments'	: {
					inst_button.inst_id : inst_button.isChecked() \
					for inst_button in group_frame.findChildren(InstrumentButton)
				}
			}
			for group_frame in self.findChildren(GroupFrame)
		}

	def apply_selections(self, selections):
		for group_frame in self.findChildren(GroupFrame):
			if group_frame.group_id in selections:
				sel = selections[group_frame.group_id]
				group_button = group_frame.findChild(GroupButton)
				with SigBlock(group_button):
					group_button.setChecked(sel['group'])
				for inst_button in group_frame.findChildren(InstrumentButton):
					if inst_button.inst_id in sel['instruments']:
						inst_button.setChecked(sel['instruments'][inst_button.inst_id])
					else:
						logging.warning(f'Button "{inst_button.inst_id}" not found in project def')
			else:
				logging.warning(f'Group "{group_frame.group_id}" not found in project def')

	@pyqtSlot(int)
	def synth_ready(self, plugin_id):
		"""
		Received from Carla when LiquidSFZ is ready to play.
		Notifies MainWindow so the MultiPortLooper can connect a new port to this
		widget's synth.
		"""
		self.sig_synth_ready.emit(self)

	def __str__(self):
		return "<DrumKitWidget %s>" % os.path.basename(self.filename)


class TitleFrame(QFrame):
	pass

class GroupFrame(QFrame):
	def __init__(self, group, parent):
		super().__init__(parent)
		self.setFrameShape(QFrame.NoFrame)
		self.setObjectName(group.group_id)	# GroupFrame identified by group_id
		self.group_layout = QVBoxLayout()
		self.group_layout.setSpacing(0)
		self.group_layout.setContentsMargins(1,1,1,1)
		self.setLayout(self.group_layout)
		self.group_button = GroupButton(self)		# GroupButton has no unique object name
		self.group_button.setText(group.name)
		self.group_button.setCheckable(True)
		self.group_layout.addWidget(self.group_button)

class GroupButton(QPushButton):
	pass

class InstrumentButton(QPushButton):
	def __init__(self, inst, parent):
		super().__init__(parent)
		self.inst_id = inst.inst_id
		self.setText(inst.name)
		self.setCheckable(True)
		self.setObjectName(inst.inst_id)	# InstrumentButton identified by inst_id


#  end kitbash/drumkit_widget.py
