#  kitbash/utils/import_loops.py
#
#  Copyright 2024 liyang <liyang@veronica>
#
import sys, logging, argparse
from kitbash.loops import Loops

def main():
	parser = argparse.ArgumentParser()
	parser.epilog = """
	Write your help text!
	"""
	parser.add_argument('Directory', type=str, nargs='?',
		help='Path to search for midi files to import.')
	parser.add_argument("--delete", "-d", action="store_true",
		help="Erase all rows in the database first.")
	parser.add_argument("--nuke", "-n", action="store_true",
		help="Nuke the entire database and reinitialize the database schema.")
	parser.add_argument("--verbose", "-v", action="store_true",
		help="Show more detailed debug information.")
	options = parser.parse_args()

	log_level = logging.DEBUG if options.verbose else logging.ERROR
	log_format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	logging.basicConfig(level = log_level, format = log_format)

	if options.nuke:
		Loops.init_schema()
	elif options.delete:
		Loops.delete_all()
	if options.Directory:
		Loops.import_dirs(options.Directory)


if __name__ == "__main__":
	sys.exit(main())


#  end kitbash/utils/import_loops.py
