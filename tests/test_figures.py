from experiments import figures


def test_chart_excludes_paired_context_limited_rounds(monkeypatch):
    def decision(round_number, player, action, usage=None):
        return {'round': round_number, 'player': player, 'step': 'action',
                'decision': action, 'valid': True, 'usage': usage}
    exp = {'decisions': [
        decision(1, 'jev', 'ROCK'),
        decision(1, 'laya', 'PAPER', {'context_limit': 512, 'input_tokens': 512}),
        decision(2, 'jev', 'SCISSORS'),
        decision(2, 'laya', 'ROCK'),
    ]}
    monkeypatch.setattr(figures, 'load', lambda *args: exp)
    assert figures.shares('plan', ['run'], 'jev', 'action', 'rps') == ({'SCISSORS': 1}, 1)
    assert figures.shares('plan', ['run'], 'laya', 'action', 'rps') == ({'ROCK': 1}, 1)
