#  kitbash/kitbash/install.py
#
#  Copyright 2026 Leon Dionne <ldionne@dridesign.sh.cn>
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
Install phoney-dictate as an application on XDG-compliant systems (like gnome).
"""
import logging
from os.path import dirname, join
from xdg_soso import XDGSetup

class KitbashSetup(XDGSetup):

	def __init__(self):
		super().__init__('kitbash', 'Kitbash')
		self._comment = "Bash together new .SFZ drumkits from pieces of existing ones."
		self._vendor_name = 'zen_soso'
		self._application_icon = join(dirname(__file__), 'res', 'kitbash-icon.svg')
		self._categories = ['AudioVideo', 'Audio']
		self._keywords = ['Audio', 'Sound', 'midi', 'SFZ', 'Drumkit']

if __name__ == '__main__':
	logging.basicConfig(level = logging.DEBUG,
		format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s")
	installer = KitbashSetup()
	installer.install()


#  end kitbash/kitbash/install.py
