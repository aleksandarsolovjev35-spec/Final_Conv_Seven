"""Сводка last_health моделей для HMI.

Один свежий кадр — одна строка на пару камера/модель. Голосования и
нескольких прогонов нет.
"""


def summarize_model_health(model_health) -> list[dict]:
    """Собрать UI-строки по паре camera/model из last_health."""
    summary = []
    seen = set()
    for row in model_health or []:
        if not isinstance(row, dict):
            continue
        key = (row.get("role"), row.get("model"))
        if key in seen:
            continue
        seen.add(key)
        error = row.get("error")
        summary.append({
            "role": key[0],
            "model": key[1],
            "ok": bool(row.get("ok")),
            "elapsed_ms": float(row.get("elapsed_ms") or 0.0),
            "detections": int(row.get("detections") or 0),
            "error": str(error) if error else None,
        })
    return summary
