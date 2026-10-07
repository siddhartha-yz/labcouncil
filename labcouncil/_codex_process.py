"""Linux child launcher: stop inference if the owning worker disappears."""
import ctypes
import os
import signal
import sys

if __name__ == '__main__':
    parent = int(sys.argv[1])
    if sys.platform != 'linux':
        raise SystemExit('Codex adapter currently requires Linux parent-death fencing')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), 'Cannot fence Codex child')
    if os.getppid() != parent:
        raise SystemExit('Owner already exited')
    os.execv(sys.argv[2], sys.argv[2:])
