"""Private CLI supervisor: stop inference if its MiroFish parent disappears.

Executed as a standalone isolated Python process in its own process group.
The Codex child inherits that group and the parent's stdin/stdout/stderr pipes.
"""

import os
import signal
import subprocess
import sys
import time


def main():
    parent_pid = int(sys.argv[1])
    if os.getppid() != parent_pid:
        return 1
    child = subprocess.Popen(sys.argv[2:])
    while child.poll() is None:
        if os.getppid() != parent_pid:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        time.sleep(0.05)
    return child.returncode if child.returncode >= 0 else 128 - child.returncode


if __name__ == '__main__':
    sys.exit(main())
