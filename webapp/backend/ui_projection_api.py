"""Read-only HTTP transport for the engine-owned ui_projection/1 contract.

This module changes transport shape only. Source documents are validated whole before
selection or pagination; the engine is the sole owner of values, states and caveats.
"""
from __future__ import annotations

from copy import deepcopy
from contextvars import ContextVar
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
import re
import secrets
from threading import Lock
from types import MappingProxyType
from typing import Annotated, Any, ClassVar, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi import Path as PathParam
from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError
from pydantic import ConfigDict, JsonValue, RootModel, model_validator
from referencing import Registry
from referencing.exceptions import NoSuchResource

from . import engine, serve

View = Literal["overview", "trust", "inventory", "findings", "topology", "device"]
VIEWS = {"overview": "Overview", "trust": "Trust", "inventory": "Inventory",
         "findings": "Findings", "topology": "Topology", "device": "DevicePage"}
TRANSPORT_SCHEMA = "ui_projection_transport/1"
MAX_PAGE_SIZE = 200
_OWNER = engine.ui_projection_schema()
Draft202012Validator.check_schema(_OWNER)
_DEFS = _OWNER["$defs"]
_MAX_CONSTRUCTION_NODES = 8192
_NO_RETRIEVAL = Registry()
_RESOLVER_TYPE = type(_NO_RETRIEVAL.resolver())
_NATIVE_VERSION = "0.58.6"
_NATIVE_TRANSPORT_KINDS = frozenset({"view", "list", "carriage"})
# Independent review pin for the private legacy resolver interface below.
_LEGACY_RESOLVER_REVIEWED_VERSION = "4.26.0"
# W51 contract train: the combined schema of main f797444e (W34 / G15 stored STP
# facts, pins 16b80957.../bca688bd...), #629 + #628 (W28 trust inputs, pins
# 6aa9a264.../a3021b67...; #629 at f6323759 carries both, pins 0553957c.../3ee0af7f...)
# and the G41 + G17 + G16 + G05 + G21 + G24 deltas
# (W37-W42): compact ensure_ascii JSON plus LF, in owner key order. Re-pinned once
# on the combined schema; every parent's extract reproduces its own committed pins.
# Reviewed delta in the W51 pull request (against predicted main: 20 definitions
# added, 9 changed, none removed or reordered, keyword profile unchanged). Per-slice
# notes: docs/w34-stp-root-facts-validation-2026-10-09.md,
# docs/w37-snapshot-identity-validation-2026-10-09.md,
# docs/w38-peer-host-validation-2026-10-09.md,
# docs/w39-gateway-detail-validation-2026-10-09.md,
# docs/w40-axis-unassessed-validation-2026-10-09.md,
# docs/w41-punch-facets-validation-2026-10-09.md,
# docs/w42-cross-layer-validation-2026-10-09.md
# (prior: docs/w28-trust-inputs-validation-2026-10-08.md).
# W52 / G14 (Claude takeover of #631): that W51 schema plus the G14 stored cable/VLAN
# carriage delta (9 Carriage* definitions, VlanSelections.carriage, the stored_vlan_carriage_scope
# limitation id, four unranked carriage vocabularies, Trust limitations 32 -> 33). Recomputed
# statically on the merged schema with this module's own _native_schema_hash; the same method
# reproduces every parent's committed pins. Hosted CI must confirm.
# W52 / G14 v2 (vlan_carriage/2): VlanSelections.carriage is now the closed CarriageSummary
# (CarriageList removed); CarriagePage, Carriage and CarriageDocument are added for the lazy
# page route. The previous pins (414419ba.../0f6d3e3d...) were reproduced on the v1 head with
# this module's own _native_schema_hash before these were computed the same way, as a pure call.
# These are audit pins, never populated from the schemas present at runtime.
# A schema change requires a new equivalence review before changing these pins.
# Round 2: actual hosted 8a3c04d3/tree8dfd99b6 emitted the complete page-resource
# delta. All four whole schemas, local refs, unchanged domain and canonical types
# were independently reviewed before adopting these literals; no runtime auto-pin.
_NATIVE_SCHEMA_HASHES = MappingProxyType({
    "view": "2f70b393a3d682063a34a930026e3b4cf145278dbb387037fbaf6b30aff28714",
    "list": "82ca31f0505c3c30ee8f97503d0b1396a8d45d0f16ae9f7123f129720cd72bb7",
    # W52 v2 whole Carriage, including the reviewed round-two page-resource fields.
    "carriage": "55d75f4efeb2eb627071cffb29a64a7756618da00480a50edbe06730310cd95b",
    # Full OWNER root with all 251 definitions. Internal admission never marks transport smoke.
    "document": "2b8f96d67afef4a24d1f2e26865fd087dc82b6d4258477b94fd452692a7bd13e",
})
_NATIVE_UNSAFE_STRING = re.compile("[\r\n\u2028\u2029\ud800-\udfff]")
_NATIVE_SMOKE_TRACE: ContextVar[dict[str, bool] | None] = ContextVar("ui_projection_native_smoke", default=None)


def _offline_registry(registry):
    if type(registry) is not Registry:
        raise ValueError("Unsupported offline reference registry")
    return _NO_RETRIEVAL.with_resources(registry.items())


def _deny_remote_reference(uri):
    raise NoSuchResource(ref=uri)


def _reviewed_legacy_resolver_type():
    """Fail closed before using private resolver internals from another release."""
    message = "Legacy resolver requires reviewed jsonschema 4.26.0"
    try:
        installed = version("jsonschema")
    except PackageNotFoundError:
        raise RuntimeError(message) from None
    if installed != _LEGACY_RESOLVER_REVIEWED_VERSION:
        raise RuntimeError(message)
    try:
        from jsonschema.validators import _RefResolver
    except (ImportError, AttributeError):
        raise RuntimeError("Reviewed jsonschema legacy resolver is unavailable") from None
    if not isinstance(_RefResolver, type):
        raise RuntimeError("Reviewed jsonschema legacy resolver is unavailable")
    return _RefResolver


def _offline_context(changes):
    """Retain explicit in-memory contexts without inheriting retrieval callbacks."""
    changes = dict(changes)
    if "registry" in changes:
        changes["registry"] = _offline_registry(changes["registry"])
    resolver = changes.get("_resolver")
    if resolver is not None:
        if type(resolver) is not _RESOLVER_TYPE:
            raise ValueError("Unsupported offline reference resolver")
        changes["_resolver"] = _RESOLVER_TYPE(
            base_uri=resolver._base_uri, registry=_offline_registry(resolver._registry), previous=resolver._previous,
        )
    legacy = changes.get("resolver")
    if legacy is not None:
        legacy_type = _reviewed_legacy_resolver_type()
        if type(legacy) is not legacy_type:
            raise ValueError("Unsupported offline legacy reference resolver")
        closed = legacy_type(base_uri=legacy.base_uri, referrer=legacy.referrer,
                             store=dict(legacy.store), cache_remote=False, handlers={})
        closed._scopes_stack = list(legacy._scopes_stack)
        closed.resolve_remote = _deny_remote_reference
        changes["resolver"] = closed
    return changes


def _stock_validator(schema):
    return Draft202012Validator(schema, registry=_NO_RETRIEVAL)


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
            yield from _stock_validator(self.schema).iter_errors(instance, _schema)
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
        yield from _stock_validator(self.schema).iter_errors(instance)

    def validate(self, *args, **kwargs) -> None:
        for error in self.iter_errors(*args, **kwargs):
            raise error

    def is_valid(self, instance: Any, _schema: Any = None) -> bool:
        if _schema is not None:
            return _stock_validator(self.schema).is_valid(instance, _schema)
        return next(self.iter_errors(instance), None) is None

    def evolve(self, **changes):
        return _stock_validator(self.schema).evolve(**_offline_context(changes))


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
        return _stock_validator(original)
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
        return _stock_validator(original)
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
    stock_properties = Draft202012Validator.VALIDATORS["properties"]
    references: dict[str, Any] = {}
    property_plans: dict[int, tuple[Any, tuple[tuple[str, Any], ...]]] = {}
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

    def properties(validator, members, instance, containing_schema):
        plan = property_plans.get(id(members)) if owned_context(validator) else None
        if plan is not None and plan[0] is members:
            if validator.is_type(instance, "object"):
                for name, child in plan[1]:
                    if name in instance:
                        # Each child retains its complete keyword plan and exact root
                        # context. As with private descend, failures never escape:
                        # the facade replays them through the public stock schema.
                        yield from child.iter_errors(instance[name])
            return
        yield from stock_properties(validator, members, instance, containing_schema)

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

    validator_class = validators.extend(Draft202012Validator,
                                        {"oneOf": one_of, "$ref": reference, "properties": properties})
    compiled = validator_class(schema, registry=_NO_RETRIEVAL)
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
        for node in owned_nodes.values():
            members = node.get("properties") if type(node) is dict else None
            if (type(members) is dict and all(type(name) is str and type(child) in (dict, bool)
                                             for name, child in members.items())):
                # Only eagerly retained private children are eligible. No request
                # key, instance, generator, outcome or validation error is cached.
                plan = tuple((name, constructions[id(child)][1]) for name, child in members.items())
                property_plans[id(members)] = (members, plan)
    for name, definition in schema.get("$defs", {}).items():
        if not any(escape in name for escape in ("/", "~", "%")):
            references["#/$defs/" + name] = compiled.evolve(schema=definition)
            register_context(references["#/$defs/" + name])
    for identity, branches in branch_schemas.items():
        branch_validators[identity] = [compiled.evolve(schema=branch) for branch in branches]
        for validator in branch_validators[identity]:
            register_context(validator)
    return _OwnedSchemaValidator(original, compiled, fingerprint)


def _native_instance_allowed(value: Any) -> bool:
    """Audited native domain; rejection selects Python, never rejects the response."""
    active: set[int] = set()

    def visit(node, depth):
        if depth > 128:
            return False
        kind = type(node)
        if node is None or kind is bool:
            return True
        if kind is int:
            return -(2**53 - 1) <= node <= 2**53 - 1
        if kind is str:
            return _NATIVE_UNSAFE_STRING.search(node) is None
        if kind not in (dict, list) or id(node) in active:
            return False
        active.add(id(node))
        try:
            if kind is dict:
                return all(type(key) is str and visit(key, depth + 1) and visit(child, depth + 1)
                           for key, child in node.items())
            return all(visit(child, depth + 1) for child in node)
        finally:
            active.remove(id(node))

    try:
        return visit(value, 0)
    except (RecursionError, RuntimeError):
        return False


def _native_schema_hash(schema):
    fingerprint = _schema_fingerprint(schema)
    if fingerprint is None:
        return None
    try:
        fingerprint.encode("utf-8", errors="strict")  # no astral/surrogate-pair hash alias
        raw = json.dumps(schema, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    except (ValueError, TypeError, RecursionError, RuntimeError):
        return None


def _native_provider():
    try:
        if version("jsonschema-rs") != _NATIVE_VERSION:
            return None
        import jsonschema_rs
        return jsonschema_rs
    except (PackageNotFoundError, ImportError, OSError):
        return None


class _NativeTransportValidator:
    """Native acceptance only for literal-pinned complete schemas and their audited instance domain.

    Python remains the source of public errors and unsupported/context behavior.
    No instances or validation results are retained between calls.
    """
    __slots__ = ("schema", "__original", "__fingerprint", "__python", "__native", "__transport_proof")

    def __init__(self, schema, kind, *, transport_proof=True):
        self.schema = self.__original = schema
        # Internal document admission must never certify a later Python-only transport.
        self.__transport_proof = (transport_proof is True and type(kind) is str
                                  and kind in _NATIVE_TRANSPORT_KINDS)
        self.__fingerprint = _schema_fingerprint(schema)
        self.__python = _compiled_validator(schema)
        self.__native = None
        expected = _NATIVE_SCHEMA_HASHES.get(kind)
        if expected is None or _native_schema_hash(schema) != expected:
            return
        provider = _native_provider()
        if provider is None:
            return
        try:
            owned = deepcopy(schema)
            # Bind construction to the exact owned bytes, even if the public schema
            # changes during the copy. Future schemas never certify themselves.
            if (_schema_fingerprint(owned) != self.__fingerprint
                    or _native_schema_hash(owned) != expected):
                return
            self.__native = provider.Draft202012Validator(
                owned, offline=True, validate_formats=False, ignore_unknown_formats=True,
            )
        except Exception:
            pass  # Unavailable native construction remains an offline Python path.

    def iter_errors(self, instance, _schema=None):
        if _schema is not None:
            yield from _stock_validator(self.schema).iter_errors(instance, _schema)
            return
        unchanged = self.schema is self.__original and _schema_fingerprint(self.schema) == self.__fingerprint
        if unchanged and self.__native is not None and _native_instance_allowed(instance):
            try:
                accepted = self.__native.is_valid(instance)
            except Exception:
                pass
            else:
                if (accepted is True and self.schema is self.__original
                        and _schema_fingerprint(self.schema) == self.__fingerprint):
                    trace = _NATIVE_SMOKE_TRACE.get()
                    if trace is not None and self.__transport_proof:
                        trace["native"] = True
                    return
        if self.schema is self.__original and _schema_fingerprint(self.schema) == self.__fingerprint:
            yield from self.__python.iter_errors(instance)
        else:
            yield from _stock_validator(self.schema).iter_errors(instance)

    def validate(self, *args, **kwargs):
        for error in self.iter_errors(*args, **kwargs):
            raise error

    def is_valid(self, instance, _schema=None):
        return next(self.iter_errors(instance, _schema), None) is None

    def evolve(self, **changes):
        return _stock_validator(self.schema).evolve(**_offline_context(changes))


class _NativeValidationSmoke:
    """Nonce-bound, request-local frozen smoke proof; absent in normal operation."""
    def __init__(self, app):
        self.app = app
        self.nonce = (os.environ.get("ASSESSHUB_INSTANCE_NONCE", "").encode("utf-8")
                      if os.environ.get("ASSESSHUB_NATIVE_VALIDATION_SMOKE") == "1" else b"")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        nonces = [value for key, value in scope.get("headers", []) if key.lower() == b"x-atlas-native-smoke-nonce"]
        enabled = (bool(self.nonce) and len(nonces) == 1 and secrets.compare_digest(nonces[0], self.nonce)
                   and scope.get("method") == "GET" and "/ui-projection/" in scope.get("path", ""))
        trace = {"native": False, "complete": False} if enabled else None
        token = _NATIVE_SMOKE_TRACE.set(trace)

        async def checked_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() != b"x-atlas-native-validation"]
                if trace is not None and trace["complete"] and 200 <= message["status"] < 300:
                    headers.append((b"x-atlas-native-validation", b"jsonschema-rs/0.58.6"))
                message["headers"] = headers
            await send(message)

        try:
            return await self.app(scope, receive, checked_send)
        finally:
            _NATIVE_SMOKE_TRACE.reset(token)


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


def _copy_carriage_document(value: Any) -> Any:
    """Own the already checked page without generic copy dispatch for every immutable JSON leaf.

    Keep one memo for the complete output, including repeated mutable aliases and cycles. Foreign
    values retain stdlib deepcopy and its hooks; this helper does not replace native/schema admission.
    Snapshot inputs, cached source documents and validator schemas keep their existing copy paths.
    """
    memo: dict[int, Any] = {}
    missing = object()
    foreign_history = False

    def clone(node: Any, recurse: Any) -> Any:
        nonlocal foreign_history
        if foreign_history:
            # A real copy hook may have changed ANY memo entry. Preserve this interpreter's
            # original lookup/atomic-dispatch semantics for every later value and key.
            return deepcopy(node, memo)
        kind = type(node)
        if node is None or kind in (str, bool, int, float):
            return node
        identity = id(node)
        retained = memo.get(identity, missing)
        if retained is not missing:
            return retained
        if kind is dict:
            result: Any = {}
            memo[identity] = result
            for key, child in node.items():
                copied = recurse(child, recurse)  # Match stdlib's value-before-key hook order.
                if not foreign_history and type(key) is str:
                    result[key] = copied
                else:
                    result[recurse(key, recurse)] = copied
        elif kind is list:
            result = []
            memo[identity] = result
            for child in node:
                result.append(recurse(child, recurse))
        else:
            foreign_history = True
            return deepcopy(node, memo)
        # A child hook can delete or replace its parent's entry; stdlib restores the completed copy.
        memo[identity] = result
        # Match deepcopy's keepalive rule if a foreign fallback removes a source object mid-copy.
        try:
            memo[id(memo)].append(node)
        except KeyError:
            memo[id(memo)] = [node]
        return result

    # Explicit recursion avoids a function/closure cycle retaining the complete source and copy memo.
    return clone(value, clone)


_DOCUMENT_VALIDATOR = _NativeTransportValidator(_OWNER, "document", transport_proof=False)
_DEVICE_VALIDATOR = _compiled_validator({"$ref": "#/$defs/DeviceDocument", "$defs": _DEFS})
_PATH_DOCUMENT_VALIDATOR = _compiled_validator({"$ref": "#/$defs/PathDocument", "$defs": _DEFS})
_PROJECTION_VERSION = (
    engine.ENGINE_SCHEMA_VERSION, serve._release_version(),
    hashlib.sha256(json.dumps(_OWNER, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
)


def _require_engine_source(document: dict[str, Any], digest: str, size: int) -> None:
    """A published engine source identity (G41) must name the exact store bytes this cache entry was admitted from.

    The owner publishes it only from the exact-byte marker that ``bind_ui_projection_snapshot`` mints over
    these same bytes, so both digests are taken over one byte string, not compared across forms. A
    withheld identity is left exactly as the owner wrote it: the transport never writes an engine fact.
    """
    block = document["engine"]
    for key, expected in (("snapshot_sha256", digest), ("snapshot_bytes", size)):
        fact = block[key]
        if fact["state"] == "published" and fact["value"] != expected:
            raise ValueError("Engine projection names other source bytes than the store read")


class _SnapshotProjection:
    def __init__(self) -> None:
        self.lock = Lock()
        self.snapshot: dict[str, Any] | None = None
        self.documents: dict[str | None, dict[str, Any]] = {}
        # G14 v2: the engine's read-only carriage admission (validation, join, basis gaps), built once per digest.
        self.carriage: Any = None
        self.prepared_document = False


class _ProjectionCache:
    """One app/store lifetime, with single-flight admission per immutable byte digest.

    There is deliberately no size eviction: moving between snapshots, hosts and pages
    must not repeatedly compute and validate the same document. Memory is released
    with the owning app; nothing is persisted, shared between stores, or served without
    a fresh authoritative store read. A restart discards the cache with the old code.
    """
    def __init__(self, store: Any = None) -> None:
        self.lock = Lock()
        self.entries: dict[tuple[Any, ...], _SnapshotProjection] = {}
        self.store = store

    def document(self, raw: bytes, digest: str, host: str | None, *,
                 snapshot_id: int | None = None) -> dict[str, Any]:
        key = (*_PROJECTION_VERSION, digest)
        with self.lock:
            entry = self.entries.setdefault(key, _SnapshotProjection())
            cached = entry.documents.get(host)
        if cached is not None:
            self._verify_prepared_hit(raw, digest, host, snapshot_id)
            return cached
        # Never wait for a builder while holding the publication lock: an unrelated
        # cold host must not prevent reads of already validated documents.
        with entry.lock:
            with self.lock:
                cached = entry.documents.get(host)
            if cached is not None:
                self._verify_prepared_hit(raw, digest, host, snapshot_id)
                return cached
            prepared = None
            if self.store is not None and host is None:
                if snapshot_id is None:
                    raise ValueError("Stored projection requires its snapshot identity")
                prepared = self.store.get_carriage_document(snapshot_id)
                if prepared is None:
                    raise ValueError("Stored projection preparation is unavailable")
            if prepared is not None:
                produced, binding = prepared
                if binding["sha256"] != digest or binding["bytes"] != len(raw):
                    raise ValueError("Stored projection names another snapshot source")
                # The ingest owner already performed every carriage admission/count operation.
                # Do not decode/bind/copy its full snapshot or load its cable/code/role tables here.
                entry.prepared_document = True
            else:
                if entry.snapshot is None:
                    entry.snapshot = engine.bind_ui_projection_snapshot(raw)
                # Standalone pure-owner callers and lazy device views retain their original path.
                # HTTP fleet documents always supply Store/ID and never regenerate on a request.
                if host is None:
                    if entry.carriage is None:
                        entry.carriage = engine.ui_projection_carriage_admission(entry.snapshot)
                    produced = engine.ui_projection(deepcopy(entry.snapshot), host, entry.carriage)
                else:
                    produced = engine.ui_projection(deepcopy(entry.snapshot), host)
            # The producer may retain aliases. Cache only an owned complete document
            # after both guards succeed; an exception leaves this host retryable.
            _require_json_native(produced)
            document = deepcopy(produced)
            (_DEVICE_VALIDATOR if host is not None else _DOCUMENT_VALIDATOR).validate(document)
            _require_engine_source(document, digest, len(raw))
            with self.lock:
                entry.documents[host] = document
            return document

    def _verify_prepared_hit(self, raw: bytes, digest: str, host: str | None,
                             snapshot_id: int | None) -> None:
        if self.store is not None and host is None:
            if snapshot_id is None:
                raise ValueError("Stored projection requires its snapshot identity")
            binding = self.store.verify_carriage_document(snapshot_id)
            if binding is None or binding["sha256"] != digest or binding["bytes"] != len(raw):
                raise ValueError("Stored projection names another snapshot source")


    def source_copy(self, raw: bytes, digest: str) -> dict[str, Any]:
        """Own query input briefly; callers compute paths after both locks are released."""
        key = (*_PROJECTION_VERSION, digest)
        with self.lock:
            entry = self.entries.setdefault(key, _SnapshotProjection())
        with entry.lock:
            if entry.snapshot is None:
                entry.snapshot = engine.bind_ui_projection_snapshot(raw)
            return deepcopy(entry.snapshot)

    def carriage_source(self, raw: bytes, digest: str) -> tuple[dict[str, Any], Any]:
        """The bound snapshot and its carriage admission, built once per digest (basis gaps included).

        Neither is copied: a carriage page reads the cached snapshot read-only and only its result is owned.
        """
        key = (*_PROJECTION_VERSION, digest)
        with self.lock:
            entry = self.entries.setdefault(key, _SnapshotProjection())
        with entry.lock:
            if entry.snapshot is None:
                entry.snapshot = engine.bind_ui_projection_snapshot(raw)
            if entry.carriage is None:
                entry.carriage = engine.ui_projection_carriage_admission(entry.snapshot)
            return entry.snapshot, entry.carriage

    def carriage_window(self, raw: bytes, digest: str, snapshot_id: int, vlan_index: int,
                        offset: int, limit: int) -> tuple[Any, Any]:
        """Read only the Store-verified selected window; no request-time preparation fallback."""
        if self.store is not None:
            prepared = self.store.get_carriage_page_source(snapshot_id, vlan_index, offset, limit)
            if prepared is None:
                raise ValueError("Stored carriage preparation is unavailable")
            pack, binding = prepared
            if binding["sha256"] != digest or binding["bytes"] != len(raw):
                raise ValueError("Stored carriage window names another snapshot source")
            return engine.PreparedCarriagePage(pack), None
        return self.carriage_source(raw, digest)


def _common_document(document: dict[str, Any], binding: dict[str, Any], snapshot_id: int, view: str):
    registry = document["device"]["limitations"] if view == "device" else document["trust"]["limitations"]
    return {
        "schema": TRANSPORT_SCHEMA, "projection_schema": document["schema"],
        "identity": {"snapshot_id": snapshot_id, "sha256": binding["sha256"],
                     "bytes": binding["bytes"], "digest_form": "assesshub-store-blob"},
        "view": view, "engine": deepcopy(document["engine"]), "limitations": deepcopy(registry),
    }


def _source_document(store: Any, cache: _ProjectionCache, snapshot_id: int, view: View, host: str | None):
    if view == "device" and host is None:
        raise HTTPException(422, "The device view requires a host query parameter")
    if view != "device" and host is not None:
        raise HTTPException(422, "The host query parameter belongs to the device view")
    bound = store.get_snapshot_blob(snapshot_id)
    if bound is None:
        raise HTTPException(404, "Snapshot not found")
    raw, binding = bound
    document = cache.document(raw, binding["sha256"], host if view == "device" else None, snapshot_id=snapshot_id)
    return document, _common_document(document, binding, snapshot_id, view)


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
_VALIDATORS = {"view": _NativeTransportValidator(_VIEW_SCHEMA, "view"),
               "list": _NativeTransportValidator(_LIST_SCHEMA, "list")}
_PATH_SCHEMA = {
    **_closed({**_common_schema("path"), "payload": {"$ref": "#/$defs/Path"}}),
    "$defs": _DEFS,
}
Draft202012Validator.check_schema(_PATH_SCHEMA)
# Query documents are a separate Python-validated contract, never a native profile.
_PATH_VALIDATOR = _compiled_validator(_PATH_SCHEMA)
# G14 v2: one VLAN row's lazy carriage page, beside the path route. The payload is exactly the owner's Carriage
# definition; MAX_PAGE_SIZE binds it in the route and in _require_carriage_page. Its complete pinned native
# profile uses the same audited domain and full Python/stock fallbacks as the existing view/list profiles.
_CARRIAGE_SCHEMA = {
    **_closed({**_common_schema("carriage"), "payload": {"$ref": "#/$defs/Carriage"}}),
    "$defs": _DEFS,
}
Draft202012Validator.check_schema(_CARRIAGE_SCHEMA)
# Whole-schema source admission still requires actual hosted provider controls. Unsupported
# instances/context and public errors retain full Python behavior; no runtime auto-pin.
_CARRIAGE_VALIDATOR = _NativeTransportValidator(_CARRIAGE_SCHEMA, "carriage")
_CARRIAGE_BYTE_LIMIT = _DEFS["CarriagePage"]["properties"]["byte_limit"]["const"]


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
        trace = _NATIVE_SMOKE_TRACE.get()
        if trace is not None:
            trace.update(native=False, complete=False)
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
        if trace is not None:
            trace["complete"] = trace["native"]
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


class UiProjectionPathResponse(RootModel[dict[str, JsonValue]]):
    """A complete query response; it has no view/list pagination assumptions."""
    model_config = ConfigDict(strict=True, allow_inf_nan=False, revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def json_native_contract(cls, value: Any) -> Any:
        _require_json_native(value.root if isinstance(value, cls) else value)
        return value

    @model_validator(mode="after")
    def owner_path_contract(self):
        trace = _NATIVE_SMOKE_TRACE.get()
        if trace is not None:
            trace.update(native=False, complete=False)
        try:
            _PATH_VALIDATOR.validate(self.root)
        except ValidationError as exc:
            raise ValueError("Engine path transport failed its owner contract") from exc
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, _core_schema, _handler):
        return {"type": "object", "title": cls.__name__}


class UiProjectionCarriageResponse(RootModel[dict[str, JsonValue]]):
    """One VLAN row's carriage page; its summary is the inventory row's summary, compared before it is served."""
    model_config = ConfigDict(strict=True, allow_inf_nan=False, revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def json_native_contract(cls, value: Any) -> Any:
        _require_json_native(value.root if isinstance(value, cls) else value)
        return value

    @model_validator(mode="after")
    def owner_carriage_contract(self):
        trace = _NATIVE_SMOKE_TRACE.get()
        if trace is not None:
            trace.update(native=False, complete=False)
        try:
            _CARRIAGE_VALIDATOR.validate(self.root)
        except ValidationError as exc:
            raise ValueError("Engine carriage transport failed its owner contract") from exc
        _require_carriage_page(self.root["payload"])
        if len(json.dumps(self.root, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")) > _CARRIAGE_BYTE_LIMIT:
            raise ValueError("Carriage complete response exceeds its owner byte bound")
        if trace is not None:
            trace["complete"] = trace["native"]
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, _core_schema, _handler):
        return {"type": "object", "title": cls.__name__}


def _require_carriage_page(payload: dict[str, Any]) -> None:
    """Page metadata must agree with its items and with the summary it echoes: where the summary publishes its
    assessed cables a page totals them, or nothing when the row's codes are not readable; a row whose counts
    publish totals every one. (A withheld assessed count, under a failed source, binds no total.)"""
    page, summary = payload["page"], payload["summary"]
    expected = min(max(page["total"] - page["offset"], 0), page["limit"])
    assessed = summary["assessed"]["value"] if summary["assessed"]["state"] == "published" else None
    counted = summary["forwarding"]["state"] == "published"
    unsupported = page["state"] == "unverified"
    if ((page["state"] == "published" and page["reason"] is not None)
            or (unsupported and (page["returned"] != 0 or not isinstance(page["reason"], str)
                                 or not page["reason"].startswith("unsupported:")))
            or page["state"] not in ("published", "unverified")):
        raise ValueError("Carriage page resource state disagrees with its complete items")
    if (page["limit"] > MAX_PAGE_SIZE or len(page["items"]) > MAX_PAGE_SIZE
            or page["returned"] != len(page["items"]) or (not unsupported and page["returned"] != expected)
            or page["has_more"] != (page["offset"] + page["returned"] < page["total"])
            or (assessed is not None and page["total"] not in (0, assessed))
            or (counted and page["total"] != assessed)):
        raise ValueError("Carriage page metadata disagrees with its items")


def carriage_page(cache: _ProjectionCache, raw: bytes, binding: dict[str, Any], snapshot_id: int,
                  vlan_index: int, offset: int, limit: int) -> dict[str, Any]:
    """Build one carriage page response from the cached admission; the caller validates the transport.

    The page summary must equal the summary the admitted inventory document carries for the same VLAN row, and the
    engine block must equal that document's: the client and this server both refuse drift.
    """
    main = (cache.document(raw, binding["sha256"], None, snapshot_id=snapshot_id)
            if isinstance(cache, _ProjectionCache) and cache.store is not None
            else cache.document(raw, binding["sha256"], None))
    rows = main["inventory"]["vlans"]["rows"]["items"]
    if not 0 <= vlan_index < len(rows):
        raise HTTPException(404, "VLAN row not found")
    snapshot, admission = (cache.carriage_window(raw, binding["sha256"], snapshot_id, vlan_index, offset, limit)
                           if isinstance(cache, _ProjectionCache) and cache.store is not None
                           else cache.carriage_source(raw, binding["sha256"]))
    common = _common_document(main, binding, snapshot_id, "carriage")
    def wire_size(value: Any) -> int:
        return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))
    owner_context = {"schema": main["schema"], "engine": main["engine"], "carriage": None, "vocab": main["vocab"]}
    overhead = max(0, wire_size({**common, "payload": None}) - wire_size(owner_context))
    produced = engine.ui_projection_carriage(snapshot, vlan_index, offset, limit, admission,
                                             transport_overhead=overhead)
    _require_json_native(produced)
    document = _copy_carriage_document(produced)
    if (document["engine"] != main["engine"]
            or document["carriage"]["summary"] != rows[vlan_index]["selections"]["carriage"]
            or document["carriage"]["vlan_index"] != vlan_index
            or document["carriage"]["page"]["offset"] != offset
            or document["carriage"]["page"]["limit"] > limit):
        raise ValueError("Engine carriage page changed its source, VLAN row or summary")
    response = {**common, "payload": document["carriage"]}
    if wire_size(response) > _CARRIAGE_BYTE_LIMIT:
        raise ValueError("Carriage complete response exceeds its owner byte bound")
    return response


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
    if engine.carriage_page_limits()[1] != MAX_PAGE_SIZE:
        raise RuntimeError("Carriage storage and transport page limits disagree")
    cache = _ProjectionCache(store)
    app.add_middleware(_NativeValidationSmoke)
    @app.get("/api/snapshots/{snapshot_id}/ui-projection/inventory/carriage",
             response_model=UiProjectionCarriageResponse, operation_id="get_ui_projection_carriage")
    def projection_carriage(
        snapshot_id: Annotated[int, PathParam(ge=-(2**63), le=2**63 - 1)], response: Response,
        vlan_index: Annotated[int, Query(ge=0, le=2**53 - 1)],
        offset: Annotated[int, Query(ge=0, le=2**53 - 1)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    ) -> dict[str, Any]:
        bound = store.get_snapshot_blob(snapshot_id)
        if bound is None:
            raise HTTPException(404, "Snapshot not found")
        raw, binding = bound
        page = carriage_page(cache, raw, binding, snapshot_id, vlan_index, offset, limit)
        response.headers["Cache-Control"] = "no-store"
        return page

    @app.get("/api/snapshots/{snapshot_id}/ui-projection/topology/path",
             response_model=UiProjectionPathResponse, operation_id="get_ui_projection_path")
    def projection_path(
        snapshot_id: Annotated[int, PathParam(ge=-(2**63), le=2**63 - 1)], response: Response,
        src_ip: Annotated[str, Query(min_length=1, max_length=128)],
        dst_ip: Annotated[str, Query(min_length=1, max_length=128)],
    ) -> dict[str, Any]:
        bound = store.get_snapshot_blob(snapshot_id)
        if bound is None:
            raise HTTPException(404, "Snapshot not found")
        raw, binding = bound
        # Admit the complete source document and preserve its global context. Query
        # work uses a separate owned input and never holds a cache lock while tracing.
        main = cache.document(raw, binding["sha256"], None, snapshot_id=snapshot_id)
        source = cache.source_copy(raw, binding["sha256"])
        produced = engine.ui_projection_path(source, src_ip, dst_ip)
        _require_json_native(produced)
        document = deepcopy(produced)
        _PATH_DOCUMENT_VALIDATOR.validate(document)
        expected_query = {"src_ip": src_ip, "dst_ip": dst_ip, "max_hops": 32,
                          "required_mtu": None, "disclose": True}
        if document["engine"] != main["engine"] or document["path"]["query"] != expected_query:
            raise ValueError("Engine path changed its source or query context")
        response.headers["Cache-Control"] = "no-store"
        return {**_common_document(main, binding, snapshot_id, "path"), "payload": document["path"]}

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
                                 ("UiProjectionListResponse", _LIST_SCHEMA),
                                 ("UiProjectionPathResponse", _PATH_SCHEMA),
                                 ("UiProjectionCarriageResponse", _CARRIAGE_SCHEMA)):
                schemas[name] = _rewrite_refs({key: value for key, value in source.items() if key != "$defs"})
                schemas[name]["x-engine-schema-id"] = _OWNER["$id"]
            app.openapi_schema = api
        return app.openapi_schema

    app.openapi = projection_openapi
