# ============================================================
# modules/direction.py — LEFT / CENTER / RIGHT zone computation
# ============================================================


def get_direction(center_x: float, frame_width: int, left_boundary: float = 0.33, right_boundary: float = 0.66) -> str:
    """
    Determine the directional zone of an object based on its horizontal center position.

    The camera frame is divided into three equal vertical zones:
        [0 – 33%] → LEFT
        [33% – 66%] → CENTER
        [66% – 100%] → RIGHTz 

    Args:
        center_x: Horizontal center coordinate of the object's bounding box (pixels).
        frame_width: Total width of the frame (pixels).
        left_boundary: Fractional boundary between LEFT and CENTER (default 0.33).
        right_boundary: Fractional boundary between CENTER and RIGHT (default 0.66).

    Returns:
        Direction string: "LEFT", "CENTER", or "RIGHT".
    """
    if frame_width <= 0:
        return "CENTER"

    relative_x = center_x / frame_width

    if relative_x < left_boundary:
        return "LEFT"
    elif relative_x > right_boundary:
        return "RIGHT"
    else:
        return "CENTER"


def direction_to_hindi(direction: str) -> str:
    """
    Convert a direction label to its Hindi equivalent (Roman script for TTS).

    Args:
        direction: "LEFT", "CENTER", or "RIGHT".

    Returns:
        Hindi direction string for voice output.
    """
    mapping = {
        "LEFT": "baayi taraf",
        "CENTER": "aage",
        "RIGHT": "daayi taraf",
    }
    return mapping.get(direction.upper(), "aage")
