# conftest.py — CloudEMS test configuratie
import sys
import os

# Voeg de root toe zodat imports werken zonder package-installatie
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
