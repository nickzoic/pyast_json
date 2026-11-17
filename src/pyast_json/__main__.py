"""``python -m pyast_json`` runs the command line interface."""
import sys

from .cli import main

sys.exit(main())
