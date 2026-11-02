"""Test setup for the notebook spike: the fake NCSS server answers quickly, since a full preset is 100+ files."""

import os

os.environ.setdefault('SPIKE_DELAY', '0')
os.environ.setdefault('SPIKE_PLAN_REFRESH', '0.2')
