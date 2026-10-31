"""Display-free smoke test of the Streamlit spike with Streamlit's own AppTest: the form, validation and a run."""

import time
from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).with_name('app.py'))


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_form_validates_and_runs() -> None:
    """Make an end date before the start, see the problem, fix it, run, and read the result."""
    app = AppTest.from_file(APP, default_timeout=30).run()
    _check(not app.exception, 'the page raised')
    app.date_input[1].set_value(date(2022, 1, 1)).run()
    _check(any('end' in error.value for error in app.error), 'no problem shown for the end date')
    app.date_input[1].set_value(date(2023, 2, 28)).run()
    _check(not app.error, 'a problem is still shown')
    next(b for b in app.button if b.label == 'Run').click().run()
    for _ in range(60):
        time.sleep(0.5)
        app.run()
        if any('Result: ' in s.value for s in app.subheader):
            break
    _check(any('Result: ok' in s.value for s in app.subheader), 'the run did not finish ok')
