import sys
import os
import traceback
from datetime import datetime

# Make the app directory importable and set up a startup error log so we can
# see the real error when Passenger hides the traceback behind a generic 500.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _APP_DIR)

_ERROR_LOG = os.path.join(_APP_DIR, "passenger_errors.log")


def _log_error(exc):
    try:
        with open(_ERROR_LOG, "a") as f:
            f.write("\n===== %s =====\n" % datetime.utcnow().isoformat())
            f.write("Python: %s\n" % sys.version)
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        # Last resort: also dump to stderr so it shows in cPanel logs.
        sys.stderr.write(traceback.format_exc())


application = None
try:
    from app import app as application
except Exception as e:
    _log_error(e)
    raise
