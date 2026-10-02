"""Read-only HTTP transport for the engine-owned ui_projection/1 contract.

This module changes transport shape only. Source documents are validated whole before
selection or pagination; the engine is the sole owner of values, states and caveats.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from threading import Lock
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi import Path as PathParam
from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError
from pydantic import ConfigDict, JsonValue, RootModel, model_validator

from . import engine, serve

View = Literal["overview", "trust", "inventory", "findings", "device"]
VIEWS = {"overview": "Overview", "trust": "Trust", "inventory": "Inventory",
         "findings": "Findings", "device": "DevicePage"}
TRANSPORT_SCHEMA = "ui_projection_transport/1"
MAX_PAGE_SIZE = 200
_OWNER = engine.ui_projection_schema()
Draft202012Validator.check_schema(_OWNER)
_DEFS = _OWNER["$defs"]
_MAX_CONSTRUCTION_NODES = 8192


def _schema_fingerprint(schema: Any) -> str | None:
    """Exact JSON types, code points and ordering; unsupported schemas stay stock."""
    try:
        _require_json_native(schema)
        return json.dumps(schema, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError, RecursionError, OverflowError, RuntimeError):
        return None


class _OwnedSchemaValidator:
    """Private-helper facade, not the full mutable DraftValidator attribute API.

    Public schema edits are honored by fresh stock validation. Other context changes
    use ``evolve`` (which returns stock); direct context assignments are rejected by
    slots. The optimized graph has no supported public alias, including through errors.
    The fingerprint is a call-entry observation, not atomicity over concurrent writers.
    """
    __slots__ = ("schema", "__compiled", "__fingerprint")

    def __init__(self, schema: dict[str, Any], compiled: Any, fingerprint: str) -> None:
        self.schema = schema
        self.__compiled = compiled
        self.__fingerprint = fingerprint

    def iter_errors(self, instance: Any, _schema: Any = None):
        if _schema is not None:
            yield from Draft202012Validator(self.schema).iter_errors(instance, _schema)
            return
        if _schema_fingerprint(self.schema) == self.__fingerprint:
            try:
                error = next(self.__compiled.iter_errors(instance), None)
            except Exception:
                # References and other exceptional paths must also use the public
                # schema/context, never expose the private construction graph.
                pass
            else:
                if error is None:
                    return
        yield from Draft202012Validator(self.schema).iter_errors(instance)

    def validate(self, *args, **kwargs) -> None:
        for error in self.iter_errors(*args, **kwargs):
            raise error

    def is_valid(self, instance: Any, _schema: Any = None) -> bool:
        if _schema is not None:
            return Draft202012Validator(self.schema).is_valid(instance, _schema)
        return next(self.iter_errors(instance), None) is None

    def evolve(self, **changes):
        return Draft202012Validator(self.schema).evolve(**changes)


def _compiled_validator(schema: dict[str, Any]):
    """Compile discriminators and direct references without dropping schema constraints.

    A required object property restricted to a finite string domain proves which
    oneOf branches cannot possibly match. Only those impossible branches are skipped;
    all applicable branches and their complete schemas still use jsonschema. Direct
    root definition references reuse validators with the same root resolver, avoiding
    reconstruction for every repeated Fact/Ref leaf. Schemas
    without that proof keep the stock oneOf implementation. The canonical schemas,
    including OpenAPI, are never rewritten. A private copy owns the construction
    cache; a public facade detects schema edits once per outer validation and routes
    them, all failures, and requested alternate contexts through fresh stock behavior.
    """
    original = schema
    if type(schema) is not dict or _schema_fingerprint(schema) is None:
        return Draft202012Validator(original)
    schema = deepcopy(schema)
    fingerprint = _schema_fingerprint(schema)
    def nested_resource(node: Any) -> bool:
        if isinstance(node, dict):
            return (node is not schema and ("$id" in node or "$schema" in node)) or bool(
                {"$dynamicRef", "$dynamicAnchor", "$recursiveRef", "$recursiveAnchor"} & node.keys()
            ) or any(
                nested_resource(value) for value in node.values()
            )
        return isinstance(node, list) and any(nested_resource(value) for value in node)

    # One Python schema node can be aliased into several resources. Avoid compiling
    # any resource/dialect-changing document, rather than caching a root-scoped proof
    # that could accidentally be reused under another URI or vocabulary.
    if (fingerprint is None
            or schema.get("$schema", Draft202012Validator.META_SCHEMA["$id"]) != Draft202012Validator.META_SCHEMA["$id"]
            or nested_resource(schema)):
        return Draft202012Validator(original)
    dispatch: dict[int, tuple[str, dict[str, list[int]]]] = {}
    branch_schemas: dict[int, list[dict[str, Any]]] = {}
    branch_validators: dict[int, list[Any]] = {}
    owned_nodes: dict[int, Any] = {}

    def domain(node: Any) -> set[str] | None:
        if not isinstance(node, dict):
            return None
        if set(node) == {"$ref"} and node["$ref"].startswith("#/$defs/"):
            name = node["$ref"].removeprefix("#/$defs/")
            # This compiler supports only direct, unescaped owner definition names.
            # Other JSON pointers keep the reference resolver's ordinary behavior.
            if any(escape in name for escape in ("/", "~", "%")):
                return None
            node = schema.get("$defs", {}).get(name, {})
            if not isinstance(node, dict):
                return None
        if isinstance(node.get("const"), str):
            return {node["const"]}
        values = node.get("enum")
        if isinstance(values, list) and values and all(type(value) is str for value in values):
            return set(values)
        return None

    def compile_node(node: Any) -> None:
        if type(node) in (dict, bool):
            owned_nodes[id(node)] = node
        if isinstance(node, dict):
            branches = node.get("oneOf")
            if isinstance(branches, list) and branches and all(
                isinstance(branch, dict) and branch.get("type") == "object" for branch in branches
            ):
                for key in branches[0].get("required", []):
                    domains = [domain(branch.get("properties", {}).get(key))
                               if key in branch.get("required", []) else None for branch in branches]
                    if all(domains):
                        by_value: dict[str, list[int]] = {}
                        for index, values in enumerate(domains):
                            for value in values:
                                by_value.setdefault(value, []).append(index)
                        if max(map(len, by_value.values())) == len(branches):
                            continue
                        dispatch[id(branches)] = (key, by_value)
                        branch_schemas[id(branches)] = branches
                        break
            for value in node.values():
                compile_node(value)
        elif isinstance(node, list):
            for value in node:
                compile_node(value)

    compile_node(schema)
    stock_one_of = Draft202012Validator.VALIDATORS["oneOf"]
    stock_ref = Draft202012Validator.VALIDATORS["$ref"]
    references: dict[str, Any] = {}
    context_members: dict[int, Any] = {}
    contexts = MappingProxyType(context_members)

    def owned_context(validator) -> bool:
        # Registered objects never escape the facade or change context after setup.
        # Strong identity preserves the exact checked context without per-leaf
        # attribute checks; an unknown/evolved object cannot inherit an old ID.
        return contexts.get(id(validator)) is validator

    def register_context(validator) -> None:
        if (type(validator) is validator_class and validator._ref_resolver is None
                and validator._resolver is root_resolver and validator._registry is root_registry
                and validator.format_checker is None
                and owned_nodes.get(id(validator.schema)) is validator.schema):
            context_members[id(validator)] = validator

    def reference(validator, ref, instance, containing_schema):
        target = references.get(ref) if owned_context(validator) else None
        if target is not None:
            yield from target.iter_errors(instance)
        else:
            yield from stock_ref(validator, ref, instance, containing_schema)

    def one_of(validator, branches, instance, containing_schema):
        rule = dispatch.get(id(branches)) if owned_context(validator) else None
        if rule is not None and isinstance(instance, dict):
            key, by_value = rule
            value = instance.get(key)
            if type(value) is str and value in by_value:
                indexes = by_value[value]
                if len(indexes) == 1:
                    index = indexes[0]
                    # All other branches are impossible under this proven domain.
                    # Keep failures private for the facade's one public-stock replay;
                    # retrying here would multiply work in nested invalid oneOfs.
                    yield from branch_validators[id(branches)][index].iter_errors(instance)
                    return
                branches = [branches[index] for index in indexes]
        yield from stock_one_of(validator, branches, instance, containing_schema)

    validator_class = validators.extend(Draft202012Validator, {"oneOf": one_of, "$ref": reference})
    compiled = validator_class(schema)
    root_resolver, root_registry = compiled._resolver, compiled._registry
    stock_evolve, stock_descend = validator_class.evolve, validator_class.descend
    register_context(compiled)
    # Construction is eager and bounded by the privately retained schema graph.
    # No cache writes, instance keys, generators, errors, or validation outcomes occur
    # during requests. Explicit dialect/resource roots keep stock construction.
    if len(owned_nodes) <= _MAX_CONSTRUCTION_NODES:
        constructions = MappingProxyType({
            identity: (node, stock_evolve(compiled, schema=node, _resolver=root_resolver))
            for identity, node in owned_nodes.items()
            if type(node) is bool or not ({"$id", "$schema"} & node.keys())
        })
        for _node, validator in constructions.values():
            register_context(validator)

        def evolve(validator, **changes):
            target = changes.get("schema", validator.schema)
            retained = constructions.get(id(target))
            if (not changes.keys() - {"schema", "_resolver"} and owned_context(validator)
                    and changes.get("_resolver", root_resolver) is root_resolver
                    and retained is not None and retained[0] is target):
                return retained[1]
            return stock_evolve(validator, **changes)

        def descend(validator, instance, schema, path=None, schema_path=None, resolver=None):
            retained = constructions.get(id(schema))
            if (resolver is None and owned_context(validator)
                    and retained is not None and retained[0] is schema):
                # In this proven no-$id context, in_subresource returns this exact
                # resolver. Reuse the complete stock keyword plan without rebuilding
                # descent/evolve dispatch. Relative errors stay inside the private
                # graph: keyword validity depends on their existence, not their paths,
                # and the facade replays every public failure through fresh stock.
                # Do not probe then retry here: nested invalid subtrees would multiply.
                return retained[1].iter_errors(instance)
            return stock_descend(validator, instance, schema, path=path,
                                 schema_path=schema_path, resolver=resolver)

        validator_class.evolve = evolve
        validator_class.descend = descend
    for name, definition in schema.get("$defs", {}).items():
        if not any(escape in name for escape in ("/", "~", "%")):
            references["#/$defs/" + name] = compiled.evolve(schema=definition)
            register_context(references["#/$defs/" + name])
    for identity, branches in branch_schemas.items():
        branch_validators[identity] = [compiled.evolve(schema=branch) for branch in branches]
        for validator in branch_validators[identity]:
            register_context(validator)
    return _OwnedSchemaValidator(original, compiled, fingerprint)


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


_DOCUMENT_VALIDATOR = _compiled_validator(_OWNER)
_DEVICE_VALIDATOR = _compiled_validator({"$ref": "#/$defs/DeviceDocument", "$defs": _DEFS})
_PROJECTION_VERSION = (
    engine.ENGINE_SCHEMA_VERSION, serve._release_version(),
    hashlib.sha256(json.dumps(_OWNER, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
)


class _SnapshotProjection:
    def __init__(self) -> None:
        self.lock = Lock()
        self.snapshot: dict[str, Any] | None = None
        self.documents: dict[str | None, dict[str, Any]] = {}


class _ProjectionCache:
    """One app/store lifetime, with single-flight admission per immutable byte digest.

    There is deliberately no size eviction: moving between snapshots, hosts and pages
    must not repeatedly compute and validate the same document. Memory is released
    with the owning app; nothing is persisted, shared between stores, or served without
    a fresh authoritative store read. A restart discards the cache with the old code.
    """
    def __init__(self) -> None:
        self.lock = Lock()
        self.entries: dict[tuple[Any, ...], _SnapshotProjection] = {}

    def document(self, raw: bytes, digest: str, host: str | None) -> dict[str, Any]:
        key = (*_PROJECTION_VERSION, digest)
        with self.lock:
            entry = self.entries.setdefault(key, _SnapshotProjection())
            if host in entry.documents:
                return entry.documents[host]
        # Never wait for a builder while holding the publication lock: an unrelated
        # cold host must not prevent reads of already validated documents.
        with entry.lock:
            with self.lock:
                if host in entry.documents:
                    return entry.documents[host]
            if entry.snapshot is None:
                entry.snapshot = engine.bind_ui_projection_snapshot(raw)
            # A producer may retain its input too. Its later mutation must not
            # poison the private bound source used by another lazy host document.
            produced = engine.ui_projection(deepcopy(entry.snapshot), host)
            # The producer may retain aliases. Cache only an owned complete document
            # after both guards succeed; an exception leaves this host retryable.
            _require_json_native(produced)
            document = deepcopy(produced)
            (_DEVICE_VALIDATOR if host is not None else _DOCUMENT_VALIDATOR).validate(document)
            with self.lock:
                entry.documents[host] = document
            return document


def _source_document(store: Any, cache: _ProjectionCache, snapshot_id: int, view: View, host: str | None):
    if view == "device" and host is None:
        raise HTTPException(422, "The device view requires a host query parameter")
    if view != "device" and host is not None:
        raise HTTPException(422, "The host query parameter belongs to the device view")
    bound = store.get_snapshot_blob(snapshot_id)
    if bound is None:
        raise HTTPException(404, "Snapshot not found")
    raw, binding = bound
    document = cache.document(raw, binding["sha256"], host if view == "device" else None)
    registry = document["device"]["limitations"] if view == "device" else document["trust"]["limitations"]
    common = {
        "schema": TRANSPORT_SCHEMA, "projection_schema": document["schema"],
        "identity": {"snapshot_id": snapshot_id, "sha256": binding["sha256"],
                     "bytes": binding["bytes"], "digest_form": "assesshub-store-blob"},
        "view": view, "engine": deepcopy(document["engine"]), "limitations": deepcopy(registry),
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
_VALIDATORS = {"view": _compiled_validator(_VIEW_SCHEMA), "list": _compiled_validator(_LIST_SCHEMA)}


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
    selected = deepcopy(items[offset:offset + limit])
    return {"pointer": pointer, "source_list": deepcopy({key: value for key, value in value.items() if key != "items"}),
            "page": {"offset": offset, "limit": limit, "returned": len(selected), "total": len(items),
                     "has_more": offset + len(selected) < len(items), "items": selected}}


def _page_view(value: dict[str, Any], view: str, limit: int) -> dict[str, Any]:
    def selected(node: Any, pointer: str) -> Any:
        if pointer in LIST_CATALOG[view]:
            return _page(node, pointer, 0, limit)
        if any(path.startswith(pointer + "/") for path in LIST_CATALOG[view]):
            return {key: selected(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
                    for key, child in node.items()}
        return deepcopy(node)
    return selected(value, "")


def install_routes(app: FastAPI, store: Any) -> None:
    """Register guarded /api GETs; ordinary dict returns enforce declared response validation."""
    cache = _ProjectionCache()
    @app.get("/api/snapshots/{snapshot_id}/ui-projection/{view}",
             response_model=UiProjectionViewResponse, operation_id="get_ui_projection_view")
    def projection_view(
        snapshot_id: Annotated[int, PathParam(ge=-(2**63), le=2**63 - 1)], view: View,
        response: Response, host: str | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    ) -> dict[str, Any]:
        document, common = _source_document(store, cache, snapshot_id, view, host)
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
        document, common = _source_document(store, cache, snapshot_id, view, host)
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
