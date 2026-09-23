from __future__ import annotations

from hashlib import sha256
from typing import Any


def canonical_fields_from_profile(field_profile: dict[str, Any]) -> list[str]:
    mappings = field_profile.get("mappings")
    if not isinstance(mappings, dict):
        return []

    fields = {
        canonical_field
        for mapping in mappings.values()
        if isinstance(mapping, dict)
        and isinstance(canonical_field := mapping.get("canonical_field"), str)
        and canonical_field.strip()
    }
    return sorted(fields)


def build_schema_fingerprint(
    field_profile: dict[str, Any],
    *,
    context_pack_name: str,
    context_pack_version: str,
) -> tuple[str, dict[str, Any]]:
    canonical_fields = canonical_fields_from_profile(field_profile)
    digest = sha256(",".join(canonical_fields).encode("utf-8")).hexdigest()
    detail = {
        "version": 1,
        "canonical_fields": canonical_fields,
        "computed_with_pack": {
            "name": context_pack_name,
            "version": context_pack_version,
        },
    }
    return f"v1:{digest}", detail
