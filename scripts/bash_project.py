#  kitbash/scripts/bash_project.py
#
#  Copyright 2025 liyang <liyang@veronica>
#
"""
Bash kit from the command line
"""
import logging, argparse, sys, json
from kitbash import SAMPLES_RESOLVE, SAMPLES_COPY, SAMPLES_SYMLINK, \
					SAMPLES_HARDLINK, SAMPLES_ABSPATH
from kitbash.drumkit import Drumkit


def main():
	p = argparse.ArgumentParser()
	p.add_argument('Project', type=str, help='Kitbash project to load')
	p.add_argument('Target', type=str, nargs='?', help='Output .sfz filename')
	group = p.add_mutually_exclusive_group()
	group.add_argument("--abspath", "-a", action="store_true", help='Point to the original samples - absolute path')
	group.add_argument("--relative", "-r", action="store_true", help='Point to the original samples - relative path')
	group.add_argument("--copy", "-c", action="store_true", help='Copy samples to the "./samples" folder')
	group.add_argument("--symlink", "-s", action="store_true", help='Create symlinks in the "./samples" folder')
	group.add_argument("--hardlink", "-l", action="store_true", help='Hardlink samples in the "./samples" folder')
	p.add_argument("--dry-run", "-n", action="store_true", help="Do not make changes - just show what would be changed.")
	p.add_argument("--verbose", "-v", action="store_true", help="Show more detailed debug information")
	p.epilog = """
	Compiles a kitbash project into a single .sfz
	"""
	options = p.parse_args()
	if not options.Target and not options.dry_run:
		p.error('<Target> is required when not --dry-run')
	log_level = logging.DEBUG if options.verbose else logging.ERROR
	log_format = "[%(filename)24s:%(lineno)4d] %(levelname)-8s %(message)s"
	logging.basicConfig(stream = sys.stdout, level = log_level, format = log_format)

	try:
		with open(options.Project, 'r') as fh:
			project_def = json.load(fh)
	except FileNotFoundError:
		p.exit(f'"{options.Project[0]}" is not a file')
	except json.JSONDecodeError:
		p.exit(f'There was an error decoding "{options.Project[0]}"')

	bashed_kit = Drumkit()
	for source_file, groups in project_def.items():
		src = Drumkit(source_file)
		for group_name, group_settings in groups.items():
			for inst_id, used in group_settings['instruments'].items():
				if used:
					bashed_kit.import_instrument(inst_id, src)

	if options.dry_run:
		bashed_kit.write(sys.stdout)
	else:
		if options.abspath:
			samples_mode = SAMPLES_ABSPATH
		elif options.relative:
			samples_mode = SAMPLES_RESOLVE
		elif options.copy:
			samples_mode = SAMPLES_COPY
		elif options.symlink:
			samples_mode = SAMPLES_SYMLINK
		else:
			samples_mode = SAMPLES_HARDLINK
		bashed_kit.save_as(options.Target, samples_mode)


if __name__ == '__main__':
	main()


#  end kitbash/scripts/bash_project.py
