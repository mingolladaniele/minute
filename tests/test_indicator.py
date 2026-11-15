from minute import indicator as ind


def test_default_position_top_centre():
    assert ind.default_position(1920, 78, 1.0) == (921, 8)
    assert ind.default_position(2560, 117, 1.5) == (1221, 12)


def test_stop_only_on_the_red_button():
    w, h = 78, 30
    assert ind.on_stop_button(61, 15, w, h, 1.0)
    assert ind.on_stop_button(61 + 8, 15, w, h, 1.0)
    assert not ind.on_stop_button(61 + 10, 15, w, h, 1.0)
    assert not ind.on_stop_button(17, 15, w, h, 1.0)
    assert ind.on_stop_button(92, 22, 117, 45, 1.5)


def test_release_after_drag_does_nothing():
    calls = []
    pill = ind.Indicator.__new__(ind.Indicator)
    pill.on_click, pill.on_stop = (lambda: calls.append("click")), (lambda: calls.append("stop"))
    pill.on_moved = lambda x, y: calls.append(("moved", x, y))
    pill.w, pill.h, pill.scale, pill.x, pill.y = 78, 30, 1.0, 500, 40
    pill._moved = True
    pill._release(61, 15)
    assert calls == [("moved", 500, 40)]
    pill._moved = False
    pill._release(61, 15)
    pill._release(17, 15)
    assert calls[1:] == ["stop", "click"]
