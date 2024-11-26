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

from kitbash.liquid import LiquidSFZ


class DrumKitWIdget(QFrame):

	sig_group_select = pyqtSignal(str, str, bool, bool)
	sig_inst_select = pyqtSignal(str, str, bool, bool)
	sig_synth_ready = pyqtSignal(QObject)

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
		frm_title.setLayout(top_layout)

		main_layout.addWidget(frm_title)

		self.frm_groups = QFrame(self)
		self.groups = QHBoxLayout()
		self.groups.setContentsMargins(2,2,2,2)
		self.groups.setSpacing(0)

		self.frm_groups.setLayout(self.groups)
		main_layout.addWidget(self.frm_groups)
		self.setLayout(main_layout)

	def drumkit_loaded(self, drumkit):
		"""
		Called when KitLoader is finshed loading and interpreting SFZ.
		"""
		self.drumkit = drumkit
		for group in self.drumkit.percussion_groups:
			if group.empty():
				continue
			group_frame = GroupFrame(group, self)
			group_frame.group_button.clicked.connect(partial(self.group_select, group.group_id, group_frame.group_button))
			for inst in group.instruments.values():
				inst_button = InstrumentButton(inst, group_frame)
				inst_button.clicked.connect(partial(self.inst_select, inst.inst_id, inst_button))
				group_frame.group_layout.addWidget(inst_button)
			group_frame.group_layout.addStretch()
			self.groups.addWidget(group_frame)

	@pyqtSlot(str, QPushButton)
	def group_select(self, group_id, button):
		state = button.isChecked()
		for button in button.parentWidget().findChildren(InstrumentButton):
			button.setChecked(state)
		self.sig_group_select.emit(self.drumkit.name, group_id, button.isChecked(), self.ctrl_pressed())
		self.update_count()

	@pyqtSlot(str, QPushButton)
	def inst_select(self, inst_id, button):
		if button.isChecked():
			button.parentWidget().findChild(GroupButton).setChecked(False)
		self.sig_inst_select.emit(self.drumkit.name, inst_id, button.isChecked(), self.ctrl_pressed())
		self.update_count()

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

	def deselect_group(self, group_id):
		frame = self.findChild(GroupFrame, group_id)
		if frame is None:
			return logging.error('Could not find frame ' + group_id)
		for button in frame.findChildren(QPushButton):
			button.setChecked(False)
		self.update_count()

	def deselect_instrument(self, inst_id):
		button = self.findChild(InstrumentButton, inst_id)
		if button is None:
			return logging.error('Could not find button ' + inst_id)
		button.setChecked(False)
		button.parentWidget().findChild(GroupButton).setChecked(False)
		self.update_count()

	def saved_selections(self):
		"""
		Must return list of which instruments are selected (checked)
		"""
		raise NotImplemented()

	def restore_saved_selections(self, selections):
		raise NotImplemented()

	@pyqtSlot(int)
	def synth_ready(self, plugin_id):
		"""
		Received from Carla when LiquidSFZ is ready to play.
		Notifies MainWindow so the MultiPortLooper can connect a new port to this
		widget's synth.
		"""
		self.sig_synth_ready.emit(self)

	def __str__(self):
		return f"<DrumKitWIdget {self.filename}>"


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
		self.setText(inst.name)
		self.setCheckable(True)
		self.setObjectName(inst.inst_id)	# InstrumentButton identified by inst_id


#  end kitbash/drumkit_widget.py
