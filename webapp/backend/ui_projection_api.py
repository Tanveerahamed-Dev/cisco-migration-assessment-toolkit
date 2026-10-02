"""Read-only HTTP transport for the engine-owned ui_projection/1 contract.

This module changes transport shape only. Source documents are validated whole before
selection or pagination; the engine is the sole owner of values, states and caveats.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Annotated, Any, ClassVar, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi import Path as PathParam
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from pydantic import ConfigDict, JsonValue, RootModel, model_validator

from . import engine

View = Literal["overview", "trust", "inventory", "findings", "device"]
VIEWS = {"overview": "Overview", "trust": "Trust", "inventory": "Inventory",
         "findings": "Findings", "device": "DevicePage"}
TRANSPORT_SCHEMA = "ui_projection_transport/1"
MAX_PAGE_SIZE = 200
_OWNER = engine.ui_projection_schema()
Draft202012Validator.check_schema(_OWNER)
_DEFS = _OWNER["$defs"]
_DOCUMENT_VALIDATOR = Draft202012Validator(_OWNER)
_DEVICE_VALIDATOR = Draft202012Validator({"$ref": "#/$defs/DeviceDocument", "$defs": _DEFS})


def _rewrite_refs(value: Any) -> Any:
    """Hoist only local owner definitions into a collision-resistant OpenAPI namespace."""
    if isinstance(value, dict):
        return {k: ("#/components/schemas/UiProjection1_" + v.removeprefix("#/$defs/")
                    if k == "$ref" and isinstance(v, str) and v.startswith("#/$defs/")
                    else _rewrite_refs(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_refs(item) for item in value]
    return value


def openapi_owner_definitions() -> dict[str, Any]:
    """Fresh, mechanically rewritten copy; never mutate the engine schema or cached validators."""
    return {"UiProjection1_" + name: _rewrite_refs(schema) for name, schema in _DEFS.items()}


def _closed(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


_IDENTITY = _closed({
    "snapshot_id": {"type": "integer", "minimum": -(2**63), "maximum": 2**63 - 1},
    "sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "bytes": {"type": "integer", "minimum": 0},
    "digest_form": {"const": "assesshub-store-blob"},
})


def _require_json_native(value: Any) -> None:
    """Reject non-JSON Python values without replacing or serializing any source value.

    JSON Schema evaluates Python numbers, where NaN can pass numeric bounds. Some HTTP
    response adapters can also serialize an accepted NaN to null. Check both boundaries
    explicitly before schema validation, selection or Pydantic conversion.
    """
    active: set[int] = set()

    def visit(node: Any) -> None:
        kind = type(node)
        if node is None or kind in (str, bool, int):
            return
        if kind is float:
            if not math.isfinite(node):
                raise ValueError("Projection contains a non-finite JSON number")
            return
        if kind not in (dict, list):
            raise ValueError("Projection contains a non-JSON-native value")
        identity = id(node)
        if identity in active:
            raise ValueError("Projection contains a cyclic value")
        active.add(identity)
        try:
            if kind is dict:
                for key, child in node.items():
                    if type(key) is not str:
                        raise ValueError("Projection contains a non-string JSON object key")
                    visit(child)
            else:
                for child in node:
                    visit(child)
        finally:
            active.remove(identity)

    visit(value)


def _source_document(store: Any, snapshot_id: int, view: View, host: str | None):
    if view == "device" and host is None:
        raise HTTPException(422, "The device view requires a host query parameter")
    if view != "device" and host is not None:
        raise HTTPException(422, "The host query parameter belongs to the device view")
    bound = store.get_bound_snapshot(snapshot_id)
    if bound is None:
        raise HTTPException(404, "Snapshot not found")
    snapshot, binding = bound
    document = engine.ui_projection(snapshot, host if view == "device" else None)
    _require_json_native(document)
    (_DEVICE_VALIDATOR if view == "device" else _DOCUMENT_VALIDATOR).validate(document)
    registry = document["device"]["limitations"] if view == "device" else document["trust"]["limitations"]
    common = {
        "schema": TRANSPORT_SCHEMA, "projection_schema": document["schema"],
        "identity": {"snapshot_id": snapshot_id, "sha256": binding["sha256"],
                     "bytes": binding["bytes"], "digest_form": "assesshub-store-blob"},
        "view": view, "engine": document["engine"], "limitations": registry,
    }
    return document, common


def _list_name(schema: dict[str, Any]) -> str | None:
    ref = schema.get("$ref", "")
    name = ref.removeprefix("#/$defs/")
    target = _DEFS.get(name, {})
    branches = target.get("oneOf", [])
    if branches and all({"state", "items"} <= set(branch.get("properties", {})) for branch in branches):
        return name
    return None


def _list_catalog(schema: dict[str, Any], prefix: str = "") -> dict[str, str]:
    name = _list_name(schema)
    if name:
        return {prefix: name}
    if "$ref" in schema:
        return _list_catalog(_DEFS[schema["$ref"].removeprefix("#/$defs/")], prefix)
    result = {}
    # Rows remain whole owner records. Pagination applies to these primary view lists,
    # not arbitrary arrays inside a row or a Fact value.
    for key, child in schema.get("properties", {}).items():
        token = key.replace("~", "~0").replace("/", "~1")
        result.update(_list_catalog(child, prefix + "/" + token))
    return result


LIST_CATALOG = {view: _list_catalog(_DEFS[name]) for view, name in VIEWS.items()}
_TRANSPORT_DEFS: dict[str, Any] = {}
for _name in sorted({name for lists in LIST_CATALOG.values() for name in lists.values()}):
    _source = deepcopy(_DEFS[_name])
    _item_schemas = []
    for _branch in _source["oneOf"]:
        _item_schemas.append(_branch["properties"].pop("items")["items"])
        _branch["required"].remove("items")
    if not all(item == _item_schemas[0] for item in _item_schemas):
        raise ValueError("Owner FactList branches disagree on item schema")
    _TRANSPORT_DEFS["Source_" + _name] = _source
    _TRANSPORT_DEFS["Page_" + _name] = _closed({
        "pointer": {"type": "string"},
        "source_list": {"$ref": "#/$defs/Source_" + _name},
        "page": _closed({
            "offset": {"type": "integer", "minimum": 0, "maximum": 2**53 - 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_SIZE},
            "returned": {"type": "integer", "minimum": 0, "maximum": MAX_PAGE_SIZE},
            "total": {"type": "integer", "minimum": 0},
            "has_more": {"type": "boolean"},
            "items": {"type": "array", "maxItems": MAX_PAGE_SIZE, "items": _item_schemas[0]},
        }),
    })


def _view_schema(schema: dict[str, Any], pointer: str = "") -> dict[str, Any]:
    name = _list_name(schema)
    if name:
        return {"allOf": [{"$ref": "#/$defs/Page_" + name},
                          {"properties": {"pointer": {"const": pointer}}}]}
    if not _list_catalog(schema):
        return deepcopy(schema)
    if "$ref" in schema:
        return _view_schema(_DEFS[schema["$ref"].removeprefix("#/$defs/")], pointer)
    result = deepcopy(schema)
    result["properties"] = {name: _view_schema(child, pointer + "/" + name.replace("~", "~0").replace("/", "~1"))
                            for name, child in schema["properties"].items()}
    return result


def _common_schema(view: str) -> dict[str, Any]:
    registry = _DEFS["DevicePage" if view == "device" else "Trust"]["properties"]["limitations"]
    return {"schema": {"const": TRANSPORT_SCHEMA}, "projection_schema": {"const": _OWNER["properties"]["schema"]["const"]},
            "identity": _IDENTITY, "view": {"const": view},
            "engine": {"$ref": "#/$defs/Engine"}, "limitations": deepcopy(registry)}


_VIEW_SCHEMA = {"oneOf": [_closed({**_common_schema(view), "payload": _view_schema(_DEFS[name])})
                           for view, name in VIEWS.items()]}
_LIST_SCHEMA = {"oneOf": [
    _closed({**_common_schema(view), "list": {
        "allOf": [{"$ref": "#/$defs/Page_" + name},
                  {"properties": {"pointer": {"const": pointer}}}],
    }}) for view, catalog in LIST_CATALOG.items() for pointer, name in catalog.items()
]}
for _schema in (_VIEW_SCHEMA, _LIST_SCHEMA):
    _schema["$defs"] = {**_DEFS, **_TRANSPORT_DEFS}
    Draft202012Validator.check_schema(_schema)
_VALIDATORS = {"view": Draft202012Validator(_VIEW_SCHEMA), "list": Draft202012Validator(_LIST_SCHEMA)}


class _ProjectionResponse(RootModel[dict[str, JsonValue]]):
    model_config = ConfigDict(strict=True, allow_inf_nan=False, revalidate_instances="always")
    kind: ClassVar[str]

    @model_validator(mode="before")
    @classmethod
    def json_native_contract(cls, value: Any) -> Any:
        _require_json_native(value.root if isinstance(value, cls) else value)
        return value

    @model_validator(mode="after")
    def owner_transport_contract(self):
        try:
            _VALIDATORS[self.kind].validate(self.root)
        except ValidationError as exc:
            # API consumers do not receive a partial/freshened fallback on a broken contract.
            raise ValueError("Engine projection transport failed its owner contract") from exc
        wrappers = ([self.root["list"]] if self.kind == "list" else
                    [_at_pointer(self.root["payload"], pointer) for pointer in LIST_CATALOG[self.root["view"]]])
        for wrapper in wrappers:
            page = wrapper["page"]
            expected = min(max(page["total"] - page["offset"], 0), page["limit"])
            if (page["returned"] != len(page["items"]) or page["returned"] != expected
                    or page["has_more"] != (page["offset"] + page["returned"] < page["total"])
                    or (wrapper["source_list"]["state"] == "published" and page["total"] == 0)):
                raise ValueError("Projection page metadata disagrees with its items")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, _core_schema, _handler):
        # Pydantic cannot resolve another schema's #/$defs. The app finalizer installs
        # the actual schema plus mechanically hoisted components after its own generation.
        return {"type": "object", "title": cls.__name__}


class UiProjectionViewResponse(_ProjectionResponse):
    kind = "view"


class UiProjectionListResponse(_ProjectionResponse):
    kind = "list"


def _at_pointer(value: Any, pointer: str) -> Any:
    for token in pointer.removeprefix("/").split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


def _page(value: dict[str, Any], pointer: str, offset: int, limit: int) -> dict[str, Any]:
    items = value["items"]
    selected = items[offset:offset + limit]
    return {"pointer": pointer, "source_list": {key: value for key, value in value.items() if key != "items"},
            "page": {"offset": offset, "limit": limit, "returned": len(selected), "total": len(items),
                     "has_more": offset + len(selected) < len(items), "items": selected}}


def _page_view(value: dict[str, Any], view: str, limit: int) -> dict[str, Any]:
    result = deepcopy(value)
    for pointer in LIST_CATALOG[view]:
        parent_pointer, _, final = pointer.rpartition("/")
        parent = _at_pointer(result, parent_pointer) if parent_pointer else result
        parent[final] = _page(_at_pointer(value, pointer), pointer, 0, limit)
    return result


def install_routes(app: FastAPI, store: Any) -> None:
    """Register guarded /api GETs; ordinary dict returns enforce declared response validation."""
    @app.get("/api/snapshots/{snapshot_id}/ui-projection/{view}",
             response_model=UiProjectionViewResponse, operation_id="get_ui_projection_view")
    def projection_view(
        snapshot_id: Annotated[int, PathParam(ge=-(2**63), le=2**63 - 1)], view: View,
        response: Response, host: str | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    ) -> dict[str, Any]:
        document, common = _source_document(store, snapshot_id, view, host)
        response.headers["Cache-Control"] = "no-store"
        return {**common, "payload": _page_view(document[view], view, limit)}

    @app.get("/api/snapshots/{snapshot_id}/ui-projection/{view}/lists",
             response_model=UiProjectionListResponse, operation_id="get_ui_projection_list")
    def projection_list(
        snapshot_id: Annotated[int, PathParam(ge=-(2**63), le=2**63 - 1)], view: View,
        response: Response, pointer: str, host: str | None = None,
        offset: Annotated[int, Query(ge=0, le=2**53 - 1)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    ) -> dict[str, Any]:
        if pointer not in LIST_CATALOG[view]:
            raise HTTPException(422, "Unknown projection list selector")
        document, common = _source_document(store, snapshot_id, view, host)
        response.headers["Cache-Control"] = "no-store"
        return {**common, "list": _page(_at_pointer(document[view], pointer), pointer, offset, limit)}

    original_openapi = app.openapi

    def projection_openapi():
        if app.openapi_schema is None:
            api = original_openapi()
            schemas = api.setdefault("components", {}).setdefault("schemas", {})
            schemas.update(openapi_owner_definitions())
            schemas.update({"UiProjection1_" + name: _rewrite_refs(schema)
                            for name, schema in _TRANSPORT_DEFS.items()})
            for name, source in (("UiProjectionViewResponse", _VIEW_SCHEMA),
                                 ("UiProjectionListResponse", _LIST_SCHEMA)):
                schemas[name] = _rewrite_refs({key: value for key, value in source.items() if key != "$defs"})
                schemas[name]["x-engine-schema-id"] = _OWNER["$id"]
            app.openapi_schema = api
        return app.openapi_schema

    app.openapi = projection_openapi
