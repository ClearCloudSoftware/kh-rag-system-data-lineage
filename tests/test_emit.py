from kh_data_lineage.emit import AsyncEmitter

class FakeClient:
    def __init__(self, fail_times=0):
        self.calls, self._fail = 0, fail_times
    def emit(self, event):
        self.calls += 1
        if self.calls <= self._fail:
            raise RuntimeError("boom")

def test_emit_succeeds_first_try():
    c = FakeClient()
    AsyncEmitter(c)._emit_with_retry("evt")
    assert c.calls == 1

def test_emit_retries_then_succeeds():
    c = FakeClient(fail_times=2)
    AsyncEmitter(c, retries=3)._emit_with_retry("evt")
    assert c.calls == 3

def test_emit_swallows_persistent_failure():
    c = FakeClient(fail_times=99)
    AsyncEmitter(c, retries=3)._emit_with_retry("evt")   # must NOT raise
    assert c.calls == 3
