"""审核规则引擎：纯函数，不读写文件，方便单测。"""

from __future__ import annotations

from typing import Any

REQUIRED_FIELDS = ("duration_minutes", "category", "publish_date", "requested_time")


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def missing_fields(material: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_FIELDS if is_blank(material.get(field))]


def _field_text(material: dict[str, Any], field: str) -> str:
    value = material.get(field)
    return "" if value is None else str(value)


def evaluate(material: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """按规则逐条检查素材，返回风险、是否需要补充、是否阻断。"""
    risks: list[dict[str, Any]] = []

    for rule in rules:
        rule_type = rule.get("type")
        rule_id = rule.get("rule_id", "")
        name = rule.get("name", "")
        level = rule.get("level", "low")
        action = rule.get("action", "confirm")

        if rule_type == "keyword":
            hits: list[str] = []
            for field in rule.get("fields", []):
                text = _field_text(material, field)
                for keyword in rule.get("keywords", []):
                    if keyword and keyword in text and keyword not in hits:
                        hits.append(keyword)
            if hits:
                risks.append(
                    {
                        "rule_id": rule_id,
                        "name": name,
                        "level": level,
                        "action": action,
                        "reason": f"命中{name}关键词：{'、'.join(hits)}",
                    }
                )

        elif rule_type == "required_fields":
            missing = [
                field
                for field in rule.get("fields", [])
                if is_blank(material.get(field))
            ]
            if missing:
                risks.append(
                    {
                        "rule_id": rule_id,
                        "name": name,
                        "level": level,
                        "action": action,
                        "reason": f"缺少字段：{'、'.join(missing)}",
                    }
                )

        elif rule_type == "max_duration":
            duration = material.get("duration_minutes")
            max_minutes = rule.get("max_minutes", 60)
            if isinstance(duration, (int, float)) and duration > max_minutes:
                risks.append(
                    {
                        "rule_id": rule_id,
                        "name": name,
                        "level": level,
                        "action": action,
                        "reason": f"时长 {duration} 分钟超过 {max_minutes} 分钟",
                    }
                )

    high_risk = any(risk["level"] == "high" for risk in risks)
    needs_supplement = any(risk["action"] == "supplement" for risk in risks)
    confirmations = [
        f"{risk['rule_id']}：{risk['reason']}"
        for risk in risks
        if risk["action"] == "confirm"
    ]

    return {
        "passed": not risks,
        "blocked": high_risk or needs_supplement,
        "high_risk": high_risk,
        "needs_supplement": needs_supplement,
        "risks": risks,
        "confirmations": confirmations,
        "missing_fields": missing_fields(material),
    }
