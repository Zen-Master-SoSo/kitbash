#  kitbash/looper_widget.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os
from functools import partial
from PyQt5 import uic
from PyQt5.QtCore import Qt
from PyQt5.QtCore import pyqtSlot
from PyQt5.QtCore import QTimer
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QFrame
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QLCDNumber
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtWidgets import QSpinBox
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QGridLayout
from PyQt5.QtWidgets import QSizePolicy

from qt_extras import ShutUpQT

from kitbash.loops import Loops
from kitbash.looper import Looper, DEFAULT_BEATS_PER_MINUTE


class LooperWidget(QFrame):

	single_loop	= False # Set True to play one loop at a time
	columns = 6

	def __init__(self, parent):
		super().__init__(parent)
		my_dir = os.path.dirname(__file__)
		with ShutUpQT():
			uic.loadUi(os.path.join(my_dir, 'res', 'looper_widget.ui'), self)
		self.cmb_group.addItem('')
		self.cmb_group.addItems(Loops.groups())
		self.cmb_group.currentTextChanged.connect(self.group_changed)
		self.beat_spinner.valueChanged.connect(self.set_bpm)
		self.play_button.toggled.connect(self.play_toggle)
		self.loops_layout = QGridLayout()
		self.loops_layout.setContentsMargins(0,0,0,0)
		self.loops_layout.setSpacing(2)
		self.frm_loops.setLayout(self.loops_layout)
		self.loops_font = self.play_button.font()
		self.loops_font.setPointSize(8)
		self.looper = Looper()
		self.update_timer = QTimer()
		self.update_timer.setInterval(int(1 / 8 * 1000))
		self.update_timer.timeout.connect(self.slot_timer_timeout)

	@pyqtSlot()
	def slot_timer_timeout(self):
		self.beat.display(int(self.looper.beat + 1.0))

	@pyqtSlot(str)
	def group_changed(self, text):
		self.looper.stop()
		self.looper.clear()
		self.looper.remeasure()
		self.play_button.setChecked(False)
		for button in self.frm_loops.findChildren(QPushButton):
			self.loops_layout.removeWidget(button)
			button.deleteLater()
		if text == '':
			self.play_button.setEnabled(False)
			return
		ord_ = 0
		ids_to_load = Loops.group_loops(text)
		self.looper.load_loops([tup[0] for tup in ids_to_load])
		for tup in ids_to_load:
			button = QPushButton(tup[1], self.frm_loops)
			button.setFont(self.loops_font)
			button.setCheckable(True)
			button.loop_id = tup[0]
			button.toggled.connect(partial(self.loop_select, tup[0]))
			self.loops_layout.addWidget(button, int(ord_ / self.columns), ord_ % self.columns)
			ord_ += 1
		self.play_button.setEnabled(True)

	@pyqtSlot(int, bool)
	def loop_select(self, loop_id, state):
		if state and self.single_loop:
			for button in self.frm_loops.findChildren(QPushButton):
				if button.loop_id != loop_id:
					button.setChecked(False)
		self.looper.load_loop(loop_id).active = state

	@pyqtSlot(bool)
	def play_toggle(self, state):
		if state:
			self.update_timer.start()
			self.looper.play()
		else:
			self.update_timer.stop()
			self.looper.stop()

	@pyqtSlot(int)
	def set_bpm(self, bpm):
		self.looper.bpm = bpm

	def sizeHint(self):
		return QSize(490, 50)


#  end kitbash/looper_widget.py
