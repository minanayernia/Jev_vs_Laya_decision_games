"""Drive a game's play_round without the runner: each policy maps (step, request) -> action."""


def make_ask(*policies, log=None):
    def ask(i, step, request):
        action = policies[i](step, request)
        if log is not None:
            log.append((i, step, request, action))
        return action, action in request.options
    return ask


def always(action):
    return lambda step, request: action
