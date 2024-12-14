#  kitbash/drumkit_widget.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging
from os.path import basename
from functools import partial

from PyQt5.QtCore import Qt
from PyQt5.QtCore import QObject
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QIcon
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QFrame
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtWidgets import QPushButton

from qt_extras import SigBlock
from liquiphy import LiquidSFZ
from kitbash import PACKAGE_DIR
from kitbash.synth import Synth
from kitbash.icons import (
	ICON_EXPANDED,
	ICON_HIDDEN,
	ICON_CLOSE,
	PIXMAP_AUDIO_OFF,
	PIXMAP_AUDIO_ON
)


class DrumkitWidget(QFrame):

	sig_inst_toggle = pyqtSignal(QObject, str, bool, bool)
	sig_synth_ready = pyqtSignal(QObject)
	sig_remove_drumkit = pyqtSignal(QObject)

	def __init__(self, filename, parent):
		super().__init__(parent)
		self.looper = parent.looper
		self.filename = filename
		self.moniker = basename(self.filename)
		self.drumkit = None

		self.synth = Synth(self.moniker)
		self.synth.sig_ports_ready.connect(self.slot_synth_ports_ready)
		self.synth.load(self.filename)

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

		self.hide_button = QPushButton(self)
		self.hide_button.setIcon(ICON_EXPANDED())
		self.hide_button.setIconSize(QSize(16,16))
		self.hide_button.setFixedWidth(20)
		self.hide_button.setFixedHeight(20)
		self.hide_button.setCheckable(True)
		self.hide_button.toggled.connect(self.hide)
		top_layout.addWidget(self.hide_button)

		self.audio_indicator = QLabel(self)
		self.audio_indicator.setPixmap(PIXMAP_AUDIO_OFF())
		top_layout.addWidget(self.audio_indicator)

		self.lbl_use_count = QLabel(self)
		self.lbl_use_count.setText('(0)')
		self.lbl_use_count.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		top_layout.addWidget(self.lbl_use_count)

		label = QLabel(self)
		label.setText(self.filename)
		top_layout.addWidget(label)

		top_layout.addStretch(20)

		remove_button = QPushButton(self)
		remove_button.setIcon(ICON_CLOSE())
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

	@pyqtSlot()
	def slot_synth_ports_ready(self):
		"""
		Received from Synth when all ports are registered.
		Notifies MainWindow so the KitbashLooper can connect a new port to this
		widget's synth.
		"""
		self.sig_synth_ready.emit(self)

	def drumkit_loaded(self):
		"""
		Called when KitLoader is finshed loading and interpreted SFZ.
		KitLoader sets the "drumkit" attribute of this widget.
		"""
		for group in self.drumkit.groups.values():
			if group.empty():
				continue
			group_frame = GroupFrame(group, self)
			group_frame.group_id = group.group_id
			group_frame.group_button.clicked.connect(partial(self.group_clicked, group_frame))
			for inst in group.instruments.values():
				inst_button = InstrumentButton(inst, group_frame)
				inst_button.toggled.connect(partial(self.instrument_toggled, inst_button))
				group_frame.group_layout.addWidget(inst_button)
			group_frame.group_layout.addStretch()
			self.groups.addWidget(group_frame)

	@pyqtSlot(QFrame)
	def group_clicked(self, group_frame):
		"""
		Tied to a GroupButton click event.
		"group_frame" is the QFrame which contains the clicked GroupButton and various
		InstrumentButton instances.
		InstrumentButton signals are not suppressed, and so trigger "sig_inst_toggle".
		"""
		group_button = group_frame.findChild(GroupButton)
		for inst_button in group_frame.findChildren(InstrumentButton):
			inst_button.setChecked(group_button.isChecked())

	@pyqtSlot(QPushButton)
	def instrument_toggled(self, button):
		"""
		Tied to an InstrumentButton toggle event.
		"inst_id" is a string key, enumerated in the DrumkitClass.
		"button" is the InstrumentButton which was toggled.
		"""
		self.sig_inst_toggle.emit(self, button.inst_id, button.isChecked(), self.ctrl_pressed())
		self.update_count()

	@pyqtSlot()
	def remove_clicked(self):
		"""
		Tied to the "remove" button click.
		"""
		self.sig_remove_drumkit.emit(self)

	@pyqtSlot(bool)
	def hide(self, state):
		"""
		"Roll up" this DrumkitWidget.
		"""
		if state:
			self.initial_height = self.height()
			self.frm_groups.hide()
			self.setFixedHeight(30)
			self.hide_button.setIcon(ICON_HIDDEN())
		else:
			self.frm_groups.show()
			self.setFixedHeight(self.initial_height)
			self.hide_button.setIcon(ICON_EXPANDED())

	def update_count(self):
		"""
		Updates the "use count" label with the number of selected instruments.
		"""
		use_count = len([ b for b in self.frm_groups.findChildren(InstrumentButton) if b.isChecked() ])
		self.lbl_use_count.setText('(%d)' % use_count)
		self.audio_indicator.setPixmap(
			PIXMAP_AUDIO_ON() if bool(use_count) and not self.looper.bashed_exclusive \
			else PIXMAP_AUDIO_OFF())
		font = self.lbl_use_count.font()
		font.setBold(bool(use_count))
		self.lbl_use_count.setFont(font)

	def ctrl_pressed(self):
		"""
		Returns (bool) True if the CTRL key is being pressed. Useful for making
		multiple selections.
		"""
		return QApplication.keyboardModifiers() == Qt.ControlModifier

	def deselect_parent_group(self, inst_id):
		"""
		Called whenever an InstrumentButton is deselected.
		"""
		inst_button = self.findChild(InstrumentButton, inst_id)
		inst_button.parentWidget().findChild(GroupButton).setChecked(False)

	def deselect_instrument(self, inst_id):
		"""
		Called from MainWindow when a button with the same inst_id is selected
		exclusively (not CTRL key pressed).
		"""
		button = self.findChild(InstrumentButton, inst_id)
		if button:	# May not exist, as not all Drumkits use the same instruments
			button.setChecked(False)
			button.parentWidget().findChild(GroupButton).setChecked(False)
			self.update_count()

	def selected_instrument_ids(self):
		"""
		Returns a list of instrument ids from selected instrument buttons.
		"""
		return [ button.inst_id \
				for button in self.findChildren(InstrumentButton) \
				if button.isChecked() ]

	def select_all(self):
		for type_ in [GroupButton, InstrumentButton]:
			buttons = self.findChildren(type_)
			with SigBlock(* buttons):
				for button in buttons:
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
					inst_button.inst_id : inst_button.isChecked() \
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
					if inst_button.inst_id in sel['instruments']:
						inst_button.setChecked(sel['instruments'][inst_button.inst_id])
					else:
						logging.warning('Button "%s" not found in project def', inst_button.inst_id)
			else:
				logging.warning('Group "%s" not found in project def', group_frame.group_id)

	def __str__(self):
		return f"<DrumkitWidget {self.moniker}>"


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
