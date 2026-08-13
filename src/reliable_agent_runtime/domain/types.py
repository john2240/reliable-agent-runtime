"""JSON-compatible type aliases used across the domain layer."""

# PEP 695 named recursive aliases avoid the implicit-recursion ambiguity that
# older ``TypeAlias`` declarations create for runtime schema generators.
type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
