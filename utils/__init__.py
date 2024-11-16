#  kitbash/utils.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import os, logging
from pretty_repr import Repr

def inspect(obj):
	print(type(obj).__name__)
	for k in dir(obj):
		if k[0] != '_':
			print("%s : " % k, end='')
			try:
				print(type(getattr(obj, k)).__name__)
			except Exception as e:
				print("Error " + str(e))

	print()


#  end kitbash/utils.py
