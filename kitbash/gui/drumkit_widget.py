#  kitbash/kitbash/gui/drumkit_widget.py
#
#  Copyright 2025-2026 Leon Dionne <ldionne@dridesign.sh.cn>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
"""
Provides MainWindow.
"""
import logging
from os.path import basename, join
from functools import partial, lru_cache
from PyQt5.QtCore import (Qt, QObject, pyqtSignal, pyqtSlot, QSize)
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, QLabel,
	QFrame, QSizePolicy, QPushButton, QCheckBox)
from qt_extras import SigBlock
from sfzen.drumkits import PercussionInstrument
from kitbash import PACKAGE_DIR


@lru_cache
def group_expanded_icon():
	"""
	Defers loading of QPixmaps until a QGuiApplication is instantiated.
	This is a Qt5 requirement.
	"""
	return QIcon(join(PACKAGE_DIR, 'res', 'group_expanded.svg'))

@lru_cache
def group_hidden_icon():
	return QIcon(join(PACKAGE_DIR, 'res', 'group_hidden.svg'))

@lru_cache
def remove_icon():
	return QIcon.fromTheme('edit-delete')


class DrumkitWidget(QFrame):
	"""
	Graphical representation of a Drumkit.
	"""

	sig_inst_toggle = pyqtSignal(QObject, str, bool, bool)
	sig_note_on = pyqtSignal(int)
	sig_note_off = pyqtSignal(int)
	sig_remove_drumkit = pyqtSignal(QObject)

	def __init__(self, filename, parent):
		super().__init__(parent)
		self.sfz_filename = filename
		self.moniker = basename(self.sfz_filename)
		self.drumkit = None
		self.port_number = None
		self.initial_height = None

		self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)

		main_layout = QVBoxLayout()
		main_layout.setContentsMargins(1,1,1,1)
		main_layout.setSpacing(0)

		frm_top = QFrame()
		frm_top.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
		frm_top.setObjectName('frm_top')

		lo_top = QHBoxLayout()
		lo_top.setContentsMargins(2,2,2,2)
		lo_top.setSpacing(0)

		self.hide_button = QPushButton(self)
		self.hide_button.setIcon(group_expanded_icon())
		self.hide_button.setIconSize(QSize(16,16))
		self.hide_button.setCheckable(True)
		self.hide_button.toggled.connect(self.slot_hide)
		lo_top.addWidget(self.hide_button)

		label = QLabel(self)
		label.setText(self.sfz_filename)
		lo_top.addWidget(label)

		self.lbl_use_count = QLabel(self)
		self.lbl_use_count.setText('(0)')
		lo_top.addWidget(self.lbl_use_count)

		lo_top.addStretch(20)

		remove_button = QPushButton(self)
		remove_button.setIcon(remove_icon())
		remove_button.setIconSize(QSize(16,16))
		remove_button.clicked.connect(self.slot_remove_clicked)
		lo_top.addWidget(remove_button)

		frm_top.setLayout(lo_top)

		main_layout.addWidget(frm_top)

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
		Returns "True" if this DrumkitWidget has a Drumkit assigned.
		"""
		return not self.drumkit is None

	def set_drumkit(self, drumkit):
		"""
		Called when KitLoader is finshed loading and interpreted Drumkit.
		Fills the groups and instruments of this the DrumkitWidget.
		"""
		self.drumkit = drumkit
		for group in self.drumkit.percussion_groups.values():
			if group.is_empty():
				continue
			group_frame = GroupFrame(group, self)
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
		"""
		self.sig_note_on.emit(inst.pitch)

	@pyqtSlot(PercussionInstrument)
	def slot_instrument_released(self, inst):
		"""
		Triggered by InstrumentButton mouse relase.
		"""
		self.sig_note_off.emit(inst.pitch)

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
			self.hide_button.setIcon(group_hidden_icon())
		else:
			self.frm_groups.show()
			self.hide_button.setIcon(group_expanded_icon())

	def update_count(self):
		"""
		Updates the "use count" label with the number of selected instruments.
		Sets the audio indicator pixmap based on if playing or not.
		"""
		use_count = len([ b for b in self.frm_groups.findChildren(InstrumentButton) if b.isChecked() ])
		self.lbl_use_count.setText(f'({use_count})')
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

	def selected_instruments(self):
		"""
		Returns a list of PercussionInstrument from selected instrument buttons.
		"""
		return [ button.inst \
				for button in self.findChildren(InstrumentButton) \
				if button.isChecked() ]

	@pyqtSlot()
	def slot_select_all(self):
		"""
		Select all instruments.
		Triggered by kits_area context menu.
		Called when this is the first DrumkitWidget added to a project.
		"""
		for type_ in [GroupButton, InstrumentButton]:
			for button in self.findChildren(type_):
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
		self.group_id = group.group_id
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
		self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		lo = QHBoxLayout()
		lo.setContentsMargins(0,0,0,0)
		lo.setSpacing(0)
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

	# pylint: disable-next = invalid-name
	def checkStateSet(self):
		"""
		Extends QAbstractButton.checkStateSet.
		This is called in response to the gui setting the "checked" property of this QPushButton.
		"""
		with SigBlock(self.checkbox):
			self.checkbox.setChecked(self.isChecked())

	# pylint: disable-next = invalid-name
	def mousePressEvent(self, event):
		"""
		Overrides mouse so that only the contained checkbox will toggle this widget's state.
		"""
		event.accept()
		self.mouse_press()

	# pylint: disable-next = invalid-name
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
	"""
	Label contained inside an InstrumentButton, delegating its' mouse press /
	release events to its' parent.
	"""

	def __init__(self, inst, parent):
		super().__init__(parent)
		self.setText(inst.name)
		self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)

	# pylint: disable-next = invalid-name
	def mousePressEvent(self, event):
		self.parent().mouse_press()
		event.accept()

	# pylint: disable-next = invalid-name
	def mouseReleaseEvent(self, event):
		self.parent().mouse_release()
		event.accept()


#  end kitbash/kitbash/gui/drumkit_widget.py
