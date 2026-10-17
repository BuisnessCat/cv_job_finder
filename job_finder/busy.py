"""Whether Windows says the user is busy: a full-screen game, video or presentation. The automatic refresh waits
then, because the model and a game share the graphics card's memory."""
import ctypes
import sys

# SHQueryUserNotificationState answers: QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE
BUSY_STATES = {2, 3, 4}


def windows_busy() -> bool:
    """True while a full-screen app runs; on other systems or when Windows can't tell, False."""
    if sys.platform != "win32":
        return False
    state = ctypes.c_int()
    try:
        result = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except (AttributeError, OSError):
        return False
    return result == 0 and state.value in BUSY_STATES
