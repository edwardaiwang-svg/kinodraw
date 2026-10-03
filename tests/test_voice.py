from kinodraw import voice


def test_long_espeak_data_path_is_copied_somewhere_short(tmp_path, monkeypatch):
    deep = tmp_path / ('d' * 60) / ('e' * 60) / 'espeak-ng-data'
    deep.mkdir(parents=True)
    (deep / 'phontab').write_bytes(b'x')
    import espeakng_loader
    monkeypatch.setattr(espeakng_loader, 'get_data_path', lambda: str(deep))
    monkeypatch.setattr(voice.platformdirs, 'user_cache_dir', lambda name: str(tmp_path / 'cache'))
    config = voice._espeak_config()
    assert len(config.data_path) < len(str(deep)) and (tmp_path / 'cache' / 'espeak-ng-data' / 'phontab').exists()


def test_alignment_follows_clause_marks():
    class T:
        def __init__(self, phoneme, start):
            self.phoneme, self.start = phoneme, start
    timings = [T('h', 0.0), T('a', 0.1), T(',', 0.2), T('b', 1.0), T('c', 1.1), T('.', 1.2)]
    times = voice.align('ha, bc.', timings, 'en')
    assert times[0] == 0.0 and times[4] >= 1.0          # the second clause starts after the comma's pause
