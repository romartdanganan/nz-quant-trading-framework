from scripts import notify


def test_send_toast_swallows_missing_winotify(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "winotify":
            raise ImportError("no winotify")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    notify.send_toast("title", "message")  # must not raise


def test_send_toast_swallows_show_failure(monkeypatch):
    class FakeNotification:
        def __init__(self, **kwargs):
            pass

        def show(self):
            raise RuntimeError("no notification service")

    fake_module = type("m", (), {"Notification": FakeNotification})
    monkeypatch.setitem(__import__("sys").modules, "winotify", fake_module)

    notify.send_toast("title", "message")  # must not raise
