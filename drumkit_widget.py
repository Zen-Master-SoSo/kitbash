#  kitbash/drumkit_widget.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import logging
from os.path import basename
from functools import partial

from PyQt5.QtCore import Qt, QObject, pyqtSignal, pyqtSlot, QSize
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QApplication, QLayout, QVBoxLayout, QHBoxLayout, \
							QLabel, QFrame, QSizePolicy, QPushButton, QCheckBox

from qt_extras import SigBlock
from liquiphy import LiquidSFZ
from kitbash import PACKAGE_DIR
from kitbash.drumkit import Drumkit, PercussionInstrument
from kitbash.icons import (
	GROUP_EXPANDED,
	GROUP_HIDDEN,
	ICON_REMOVE,
	PIXMAP_AUDIO_OFF,
	PIXMAP_AUDIO_ON
)


class DrumkitWidget(QFrame):
	"""
	Graphical representation of a drumkit.
	"""

	sig_inst_toggle = pyqtSignal(QObject, str, bool, bool)
	sig_remove_drumkit = pyqtSignal(QObject)

	def __init__(self, filename, parent):
		super().__init__(parent)
		self.sfz_filename = filename
		self.moniker = basename(self.sfz_filename)
		self.drumkit = None
		self.synth = None
		self.port_number = None

		self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
		self.setFrameStyle(QFrame.Panel)
		self.setFrameShadow(QFrame.Sunken)
		self.setObjectName('drumkit_widget')

		main_layout = QVBoxLayout()
		main_layout.setContentsMargins(1,1,1,1)
		main_layout.setSpacing(0)

		frm_title = QFrame()
		frm_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
		frm_title.setObjectName('frm_title')

		top_layout = QHBoxLayout()
		top_layout.setContentsMargins(2,2,2,2)
		top_layout.setSpacing(0)

		self.hide_button = QPushButton(self)
		self.hide_button.setIcon(GROUP_EXPANDED())
		self.hide_button.setIconSize(QSize(16,16))
		self.hide_button.setFixedWidth(20)
		self.hide_button.setFixedHeight(20)
		self.hide_button.setCheckable(True)
		self.hide_button.toggled.connect(self.slot_hide)
		top_layout.addWidget(self.hide_button)

		self.lbl_audio_indicator = QLabel(self)
		self.lbl_audio_indicator.setPixmap(PIXMAP_AUDIO_OFF())
		top_layout.addWidget(self.lbl_audio_indicator)

		label = QLabel(self)
		label.setText(self.sfz_filename)
		top_layout.addWidget(label)

		self.lbl_use_count = QLabel(self)
		self.lbl_use_count.setText('(0)')
		top_layout.addWidget(self.lbl_use_count)

		top_layout.addStretch(20)

		remove_button = QPushButton(self)
		remove_button.setIcon(ICON_REMOVE())
		remove_button.setIconSize(QSize(16,16))
		remove_button.clicked.connect(self.slot_remove_clicked)
		top_layout.addWidget(remove_button)

		frm_title.setLayout(top_layout)

		main_layout.addWidget(frm_title)

		self.frm_groups = QFrame(self)
		self.frm_groups.setObjectName('frm_groups')
		self.groups = QHBoxLayout()
		self.groups.setContentsMargins(1,1,1,1)
		self.groups.setSpacing(0)

		self.frm_groups.setLayout(self.groups)
		main_layout.addWidget(self.frm_groups)
		self.setLayout(main_layout)

	def ready(self):
		"""
		Returns "True" if this DrumkitWidget has a synth assigned and a bashed kit.
		"""
		return not self.synth is None and not self.drumkit is None

	@pyqtSlot(Drumkit)
	def slot_drumkit_loaded(self, drumkit):
		"""
		Called when KitLoader is finshed loading and interpreted SFZ.
		Fills the groups and instruments of this the DrumkitWidget.
		"""
		self.drumkit = drumkit
		for group in self.drumkit.groups.values():
			if group.empty():
				continue
			group_frame = GroupFrame(group, self)
			group_frame.group_id = group.group_id
			group_frame.group_button.clicked.connect(partial(self.slot_group_clicked, group_frame))
			for inst in group.instruments.values():
				inst_button = InstrumentButton(inst, group_frame)
				inst_button.toggled.connect(partial(self.slot_instrument_toggled, inst_button))
				inst_button.sig_mouse_press.connect(self.slot_instrument_pressed)
				inst_button.sig_mouse_release.connect(self.slot_instrument_released)
				group_frame.group_layout.addWidget(inst_button)
			group_frame.group_layout.addStretch()
			self.groups.addWidget(group_frame)
		self.groups.addStretch()

	@pyqtSlot(QFrame)
	def slot_group_clicked(self, group_frame):
		"""
		Triggered by a GroupButton click event.
		"group_frame" is the QFrame which contains the clicked GroupButton and various
		InstrumentButton instances.
		InstrumentButton signals are not suppressed, and trigger "sig_inst_toggle".
		"""
		group_button = group_frame.findChild(GroupButton)
		for inst_button in group_frame.findChildren(InstrumentButton):
			inst_button.setChecked(group_button.isChecked())

	@pyqtSlot(PercussionInstrument)
	def slot_instrument_pressed(self, inst):
		"""
		Triggered by InstrumentButton mouse press.
		Sends a "noteon" to this widget's synth.
		"""
		self.synth.noteon(0, inst.pitch, 120)

	@pyqtSlot(PercussionInstrument)
	def slot_instrument_released(self, inst):
		"""
		Triggered by InstrumentButton mouse relase.
		Sends a "v" to this widget's synth.
		"""
		self.synth.noteoff(0, inst.pitch)

	@pyqtSlot(QPushButton)
	def slot_instrument_toggled(self, button):
		"""
		Triggered by an InstrumentButton toggle event.
		"inst_id" is a string key, enumerated in the DrumkitClass.
		"button" is the InstrumentButton which was toggled.
		"""
		self.sig_inst_toggle.emit(self, button.inst.inst_id,
			button.isChecked(), self.ctrl_pressed())
		self.update_count()

	@pyqtSlot()
	def slot_remove_clicked(self):
		"""
		Triggered by the "remove" button click event.
		"""
		self.sig_remove_drumkit.emit(self)

	@pyqtSlot(bool)
	def slot_hide(self, state):
		"""
		"Roll up" this DrumkitWidget.
		"""
		if state:
			self.initial_height = self.height()
			self.frm_groups.hide()
			self.setFixedHeight(30)
			self.hide_button.setIcon(GROUP_HIDDEN())
		else:
			self.frm_groups.show()
			self.setFixedHeight(self.initial_height)
			self.hide_button.setIcon(GROUP_EXPANDED())

	def update_count(self):
		"""
		Updates the "use count" label with the number of selected instruments.
		Sets the audio indicator pixmap based on if playing or not.
		"""
		use_count = len([ b for b in self.frm_groups.findChildren(InstrumentButton) if b.isChecked() ])
		self.lbl_use_count.setText('(%d)' % use_count)
		self.lbl_audio_indicator.setPixmap(PIXMAP_AUDIO_ON() if bool(use_count) else PIXMAP_AUDIO_OFF())
		font = self.lbl_use_count.font()
		font.setBold(bool(use_count))
		self.lbl_use_count.setFont(font)

	def ctrl_pressed(self):
		"""
		Returns (bool) True if the CTRL key is being pressed. Useful for making
		multiple selections.
		"""
		return QApplication.keyboardModifiers() == Qt.ControlModifier

	def inst_button(self, inst_id):
		"""
		Returns the instrument button identified by the given inst_id.
		"""
		return self.findChild(InstrumentButton, inst_id)

	def deselect_parent_group(self, inst_id):
		"""
		Called whenever an InstrumentButton is deselected.
		The parent group button is deselected.
		"""
		inst_button = self.inst_button(inst_id)
		inst_button.parentWidget().findChild(GroupButton).setChecked(False)

	def reselect_parent_group(self, inst_id):
		"""
		Called whenever an InstrumentButton is selected.
		The parent group button is selected if all of its' InstrumentButtons are
		selected.
		"""
		group = self.inst_button(inst_id).parentWidget()
		if all(inst_button.isChecked() for inst_button in group.findChildren(InstrumentButton)):
			group.findChild(GroupButton).setChecked(True)

	def deselect_instrument(self, inst_id):
		"""
		Called from MainWindow when a button with the same inst_id is selected
		exclusively (not CTRL key pressed).
		"""
		button = self.inst_button(inst_id)
		if button:	# May not exist, as not all Drumkits use the same instruments
			button.setChecked(False)
			self.update_count()

	def selected_instrument_ids(self):
		"""
		Returns a list of instrument ids from selected instrument buttons.
		"""
		return [ button.inst.inst_id \
				for button in self.findChildren(InstrumentButton) \
				if button.isChecked() ]

	def select_all(self):
		"""
		Select all instruments - does not trigger signals.
		Called when this is the first DrumkitWidget added to a project.
		"""
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
					inst_button.inst.inst_id : inst_button.isChecked() \
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
					if inst_button.inst.inst_id in sel['instruments']:
						inst_button.setChecked(sel['instruments'][inst_button.inst.inst_id])
					else:
						logging.warning('Button "%s" not found in project def', inst_button.inst.inst_id)
			else:
				logging.warning('Group "%s" not found in project def', group_frame.group_id)

	def __str__(self):
		return f"<DrumkitWidget {self.moniker}>"


class GroupFrame(QFrame):
	"""
	QFrame which contains one GroupButton and one or more InstrumentButton
	"""

	def __init__(self, group, parent):
		super().__init__(parent)
		self.setFrameShape(QFrame.NoFrame)
		self.setObjectName(group.group_id)	# GroupFrame identified by group_id
		self.group_layout = QVBoxLayout()
		self.group_layout.setSpacing(0)
		self.group_layout.setContentsMargins(0,0,0,0)
		self.setLayout(self.group_layout)
		self.group_button = GroupButton(self)		# GroupButton has no unique object name
		self.group_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		self.group_button.setText(group.name)
		self.group_button.setCheckable(True)
		self.group_layout.addWidget(self.group_button)


class GroupButton(QPushButton):
	"""
	Defined here to provide a distinct .css class name.
	"""


class InstrumentButton(QPushButton):
	"""
	Custom button with a contained InstrumentLabel and QCheckBox.
	The InstrumentLabel traps mouse press events, while the QCheckBox mirrors the
	"checked" state of this QPushButton.
	"""

	sig_mouse_press = pyqtSignal(PercussionInstrument)
	sig_mouse_release = pyqtSignal(PercussionInstrument)

	def __init__(self, inst, parent):
		super().__init__(parent)
		self.inst = inst
		self.setObjectName(inst.inst_id)
		self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
		lo = QHBoxLayout()
		lo.setContentsMargins(0,0,0,0)
		lo.setSpacing(0)
		lo.setSizeConstraint(QLayout.SetMinimumSize)
		self.setLayout(lo)
		self.setCheckable(True)
		lo.addWidget(InstrumentLabel(inst, self))
		lo.addStretch()
		self.checkbox = QCheckBox(self)
		self.checkbox.stateChanged.connect(self.slot_checkbox_state_change)
		lo.addWidget(self.checkbox)

	@pyqtSlot(int)
	def slot_checkbox_state_change(self, state):
		"""
		Triggered when contained checkbox is clicked.
		"""
		self.setChecked(state == Qt.Checked)

	def checkStateSet(self):
		"""
		Extends QAbstractButton.checkStateSet.
		This is called in response to the gui setting the "checked" property of this QPushButton.
		"""
		with SigBlock(self.checkbox):
			self.checkbox.setChecked(self.isChecked())

	def mousePressEvent(self, event):
		"""
		Overrides mouse so that only the contained checkbox will toggle this widget's state.
		"""
		event.accept()
		self.mouse_press()

	def mouseReleaseEvent(self, event):
		"""
		Overrides mouse so that only the contained checkbox will toggle this widget's state.
		"""
		event.accept()
		self.mouse_release()

	def mouse_press(self):
		"""
		Called from contained label. Sets the "down" state of this widget,
		(which is identified in the CSS as the ":pressed" pseudo-selector).
		"""
		self.setDown(True)
		self.sig_mouse_press.emit(self.inst)

	def mouse_release(self):
		"""
		Called from contained label. Unsets the "down" state of this widget,
		(which is identified in the CSS as the ":pressed" pseudo-selector).
		"""
		self.setDown(False)
		self.sig_mouse_release.emit(self.inst)


class InstrumentLabel(QLabel):

	def __init__(self, inst, parent):
		super().__init__(parent)
		self.setText(inst.name)
		self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)

	def mousePressEvent(self, event):
		self.parent().mouse_press()
		event.accept()

	def mouseReleaseEvent(self, event):
		self.parent().mouse_release()
		event.accept()

#  end kitbash/drumkit_widget.py
