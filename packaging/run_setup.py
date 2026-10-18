"""Entry point of JobFinder-Setup.exe (PyInstaller, one file with the app folder zipped inside)."""
import sys

from job_finder.installer import setup_main

sys.exit(setup_main(sys.argv))
