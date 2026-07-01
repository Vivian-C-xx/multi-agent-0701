MENTOR_STEPS = {"ipo_analysis", "flowchart", "debugging"}
CODE_HINTS = ("```", "def ", "for ", "print(")


def should_handle_step(step):
    return step in MENTOR_STEPS


def looks_like_code(text):
    return any(hint in text for hint in CODE_HINTS)
