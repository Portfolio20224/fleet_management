#!/usr/bin/env python
"""Point d'entree Django : gestion des commandes (runserver, migrate, seed_demo...)."""
import os
import sys

def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fleet_manager.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)

if __name__ == "__main__":
    main()
