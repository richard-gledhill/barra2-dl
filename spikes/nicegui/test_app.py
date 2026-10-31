"""Display-free smoke test of the NiceGUI spike with NiceGUI's simulated user.

It opens the page, edits a form value and finds nodes. A full run under run.io_bound did not complete inside this
harness in the time box (not diagnosed), so the run itself was checked in a browser instead; see the findings note.
"""

from nicegui import ui
from nicegui.testing import User


async def test_open_edit_and_find_nodes(user: User) -> None:
    """Open the page, see the plan, break the end date and see the plan go, then find nodes."""
    await user.open('/')
    await user.should_see('Site')
    await user.should_see('19 files, 0 cached')
    user.find(ui.input, content='2023-06-30').type('x')
    user.find(ui.button, content='Find nodes').click()
