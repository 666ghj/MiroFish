"""
Tests for interview lifecycle hook installer (Task 20).
"""

from app.services.interviews.lifecycle import install_hooks


class _StubMgr:
    def __init__(self):
        self.ready = []
        self.completed = []

    def register_on_ready(self, fn):
        self.ready.append(fn)

    def register_on_completed(self, fn):
        self.completed.append(fn)


def test_install_hooks_registers_two_callables():
    mgr = _StubMgr()
    install_hooks(mgr)
    assert len(mgr.ready) == 1
    assert len(mgr.completed) == 1
    assert callable(mgr.ready[0])
    assert callable(mgr.completed[0])
