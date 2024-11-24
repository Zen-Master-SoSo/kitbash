#  kitbash/drumkit_widget.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os, logging
from functools import partial

from PyQt5.QtCore import Qt
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


class DrumKitWIdget(QFrame):

	sig_group_select = pyqtSignal(str, str, bool, bool)
	sig_inst_select = pyqtSignal(str, str, bool, bool)

	def __init__(self, filename, parent):
		super().__init__(parent)
		self.filename = filename

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

	def drumkit_loaded(self, drumkit, saved_selections):
		self.drumkit = drumkit
		for group in self.drumkit.percussion_groups:
			if group.empty():
				continue
			group_frame = GroupFrame()
			group_frame.setFrameShape(QFrame.NoFrame)
			group_frame.setObjectName(group.group_id)	# GroupFrame identified by group_id
			group_layout = QVBoxLayout()
			group_layout.setSpacing(0)
			group_layout.setContentsMargins(1,1,1,1)
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
		if saved_selections:
			self.restore_saved_selections(saved_selections)

	@pyqtSlot(str, QPushButton)
	def group_select(self, group_id, button):
		state = button.isChecked()
		for button in button.parentWidget().findChildren(InstrumentButton):
			button.setChecked(state)
			button.setEnabled(not state)
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
		self.update_count()

	def saved_selections(self):
		"""
		Must return list of which instruments are selected (checked)
		"""
		raise NotImplemented()

	def restore_saved_selections(self, selections):
		raise NotImplemented()


class TitleFrame(QFrame):
	pass

class GroupFrame(QFrame):
	pass

class GroupButton(QPushButton):
	pass

class InstrumentButton(QPushButton):
	pass


#  end kitbash/drumkit_widget.py
