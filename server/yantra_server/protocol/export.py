"""Protocol JSON Schemas for the TS type generator and docs/PROTOCOL.md."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .messages import NOTIFICATIONS, REQUESTS, RESULTS


def _schema_of(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema(ref_template="#/$defs/{model}")


def protocol_schemas() -> dict[str, Any]:
    """{requests: {method: {params, result?}}, notifications: {method: schema}, defs: {...}}."""
    defs: dict[str, Any] = {}

    def hoist(model: type[BaseModel]) -> dict[str, Any]:
        schema = _schema_of(model)
        defs.update(schema.pop("$defs", {}))
        title = schema.get("title", model.__name__)
        defs[title] = schema
        return {"$ref": f"#/$defs/{title}"}

    requests: dict[str, Any] = {}
    for method, params_model in REQUESTS.items():
        entry: dict[str, Any] = {"params": hoist(params_model)}
        if method in RESULTS:
            entry["result"] = hoist(RESULTS[method])
        requests[method] = entry

    notifications = {method: hoist(cls) for method, cls in NOTIFICATIONS.items()}
    return {"requests": requests, "notifications": notifications, "$defs": defs}
