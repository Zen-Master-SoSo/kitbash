#  kitbash/drum_widget.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging
from functools import partial

from PyQt5.QtCore import Qt
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QWidget
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QFrame
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtWidgets import QPushButton


from kitbash.drumkit import Drumkit

class DrumWidget(QFrame):

	sig_group_select = pyqtSignal(str, str, bool, bool)
	sig_inst_select = pyqtSignal(str, str, bool, bool)

	def __init__(self, drumkit):
		super().__init__()
		self.drumkit = drumkit
		self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
		self.setFrameStyle(QFrame.Panel | QFrame.Raised)
		self.setObjectName('drum_widget')
		top_layout = QVBoxLayout()
		top_layout.setContentsMargins(2,2,2,2)
		top_layout.setSpacing(2)
		label = QLabel(self.drumkit.filename)
		label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
		label.setIndent(8)
		top_layout.addWidget(label)
		self.groups = QHBoxLayout()
		self.groups.setContentsMargins(2,2,2,2)
		self.groups.setSpacing(2)
		for group in self.drumkit.percussion_groups:
			if group.empty():
				continue
			group_frame = GroupFrame()
			group_frame.setFrameStyle(QFrame.Box)
			group_frame.setMidLineWidth(2)
			group_frame.setObjectName(group.group_id)	# GroupFrame identified by group_id
			group_layout = QVBoxLayout()
			group_layout.setSpacing(2)
			group_layout.setContentsMargins(0,0,0,0)
			group_button = GroupButton(group_frame)		# GroupButton has no unique object name
			group_button.setText(group.name)
			group_button.setCheckable(True)
			group_button.clicked.connect(partial(self.group_select, group.group_id, group_button))
			group_layout.addWidget(group_button)
			for inst in group.instruments.values():
				inst_button = InstrumentButton(group_frame)
				inst_button.setText(inst.name)
				inst_button.setCheckable(True)
				inst_button.setObjectName(inst.inst_id)	# InstrumentButton identified by inst_id
				inst_button.clicked.connect(partial(self.inst_select, inst.inst_id, inst_button))
				group_layout.addWidget(inst_button)
			group_layout.addStretch()
			group_frame.setLayout(group_layout)
			self.groups.addWidget(group_frame)
		top_layout.addLayout(self.groups)
		self.setLayout(top_layout)

	@pyqtSlot(str, QPushButton)
	def group_select(self, group_id, button):
		state = button.isChecked()
		frame = button.parentWidget()
		for button in button.parentWidget().findChildren(InstrumentButton):
			button.setChecked(state)
			button.setEnabled(not state)
		self.sig_group_select.emit(self.drumkit.name, group_id, button.isChecked(), self.ctrl_pressed())

	@pyqtSlot(str, QPushButton)
	def inst_select(self, inst_id, button):
		if button.isChecked():
			button.parentWidget().findChild(GroupButton).setChecked(False)
		self.sig_inst_select.emit(self.drumkit.name, inst_id, button.isChecked(), self.ctrl_pressed())

	def ctrl_pressed(self):
		return QApplication.keyboardModifiers() == Qt.ControlModifier

	def deselect_group(self, group_id):
		frame = self.findChild(GroupFrame, group_id)
		if frame is None:
			return logging.error('Could not find frame ' + group_id)
		for button in frame.findChildren(QPushButton):
			button.setChecked(False)

	def deselect_inst(self, inst_id):
		button = self.findChild(InstrumentButton, inst_id)
		if button is None:
			return logging.error('Could not find button ' + inst_id)
		button.setChecked(False)
		button.setEnabled(True)
		group_frame = button.parentWidget()
		group_frame.findChild(GroupButton).setChecked(False)
		for button in group_frame.findChildren(QPushButton):
			button.setEnabled(True)


class GroupFrame(QFrame):
	pass

class GroupButton(QPushButton):
	pass

class InstrumentButton(QPushButton):
	pass


#  end kitbash/drum_widget.py
