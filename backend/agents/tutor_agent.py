TUTOR_STEPS = {
    "topic_intro",
    "experience_feedback",
    "life_connection",
    "exercise_intake",
    "quiz",
    "quiz_explain_wait",
    "quiz_review",
    "plan_allocation",
    "self_evaluation",
}


def should_handle_step(step):
    return step in TUTOR_STEPS
