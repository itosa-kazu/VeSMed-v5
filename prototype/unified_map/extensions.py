"""Two-stage, judge-custodied extension protocol for W16/W17.

The ordinary candidate protocol deliberately has no notion of a future check or
treatment catalog.  This module is the harness boundary around that protocol:

``opaque commit -> primary source/model/state seal -> reveal -> state-only query``

The pre-reveal object handed to a candidate is only :class:`ExtensionCommitment`.
The clear extension pack, its hiding nonce, and the encryption key stay in the
judge-owned :class:`OpaqueExtensionCustody` object.  Python object privacy is
not treated as a sandbox: a real run must keep the custody object and this
repository outside the candidate process.  The helpers below additionally
seal/scan a candidate bundle, model bytes, and primary state payloads so the
test fixture can prove that the clear extension markers were not already in
those artifacts.

This is benchmark-fixture cryptography, not a general-purpose cryptographic
library.  It uses a 256-bit random one-time key, a 256-bit random stream nonce,
HMAC-SHA256 as the stream PRF/authenticator, and a *separate*, secret 256-bit
commitment blinder.  In particular, it is not the old low-entropy
``hash(extension JSON)`` pseudo-seal.
"""

from __future__ import annotations

import difflib
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

from .candidate_protocol import ResultStatus
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    domain_digest,
    validate_json_like,
)
from .schema import VisibleDelta, VisibleHistory
from .state import CandidateStateInput, SealedState, StatePayload, seal_state


COMMIT_PROTOCOL = "ucm-extension-commitment/2"
REVEAL_PROTOCOL = "ucm-extension-reveal/2"
PRIMARY_SEAL_PROTOCOL = "ucm-extension-primary-seal/1"
FIRST_QUERY_PROTOCOL = "ucm-extension-first-query/1"
MIGRATION_PROTOCOL = "ucm-extension-migration/1"

_COMMIT_DOMAIN = b"UCM_EXTENSION_HIDING_COMMITMENT_V2\0"
_STREAM_DOMAIN = b"UCM_EXTENSION_OPAQUE_STREAM_V1\0"
_TAG_DOMAIN = b"UCM_EXTENSION_OPAQUE_TAG_V1\0"
_TREE_DOMAIN = b"UCM_CANDIDATE_TREE_V1\0"


def _require_digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} is not hexadecimal") from exc
    return value


def _xor(left: bytes, right: bytes) -> bytes:
    if len(left) != len(right):
        raise ProtocolViolation("opaque stream length mismatch")
    return bytes(a ^ b for a, b in zip(left, right, strict=True))


def _stream(key: bytes, nonce: bytes, size: int) -> bytes:
    blocks: list[bytes] = []
    counter = 0
    while sum(map(len, blocks)) < size:
        blocks.append(
            hmac.new(
                key,
                _STREAM_DOMAIN + nonce + counter.to_bytes(8, "big"),
                hashlib.sha256,
            ).digest()
        )
        counter += 1
    return b"".join(blocks)[:size]


def _opaque_tag(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    return hmac.new(key, _TAG_DOMAIN + nonce + ciphertext, hashlib.sha256).digest()


def _state_snapshot(state: SealedState) -> str:
    """Digest all immutable S0 bytes and harness lineage fields."""

    record = state.record
    payload = state.candidate_input.payload
    return digest_json(
        {
            "record": {
                "state_instance_id": record.state_instance_id,
                "state_id": record.state_id,
                "state_hash": record.state_hash,
                "parent_state_hash": record.parent_state_hash,
                "operation": record.operation,
                "delta_digest": record.delta_digest,
                "candidate_bundle_digest": record.candidate_bundle_digest,
                "model_digest": record.model_digest,
                "scope_digest": record.scope_digest,
                "catalog_digest": record.catalog_digest,
                "as_of_available_at": record.as_of_available_at,
                "payload_size_bytes": record.payload_size_bytes,
            },
            "payload": {
                "bytes_digest": digest_bytes(payload.payload),
                "codec": payload.codec,
                "schema_version": payload.schema_version,
                "state_class": payload.state_class.value,
            },
        }
    )


def _read_candidate_tree(root: Path) -> dict[str, bytes]:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise ProtocolViolation("candidate_root must be a directory")
    result: dict[str, bytes] = {}
    for path in sorted(resolved.rglob("*")):
        if path.is_symlink():
            raise ProtocolViolation("candidate bundle symlinks are forbidden")
        if not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(resolved).as_posix())
        if any(part in {"__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        result[str(relative)] = path.read_bytes()
    if not result:
        raise ProtocolViolation("candidate bundle must contain at least one file")
    return result


def candidate_tree_digest(root: Path | str) -> str:
    """Seal exact relative paths and bytes of a candidate directory."""

    files = _read_candidate_tree(Path(root))
    manifest = canonical_json_bytes(
        {
            "protocol": "ucm-candidate-tree/1",
            "files": [
                {
                    "path": path,
                    "size_bytes": len(content),
                    "digest": digest_bytes(content),
                }
                for path, content in files.items()
            ],
        }
    )
    return domain_digest(_TREE_DOMAIN, [manifest])


def _assert_markers_absent(
    artifacts: Iterable[tuple[str, bytes]], markers: Sequence[bytes]
) -> None:
    for marker in markers:
        if type(marker) is not bytes or len(marker) < 3:
            raise ProtocolViolation("hiding markers must be exact bytes of length >= 3")
        for label, content in artifacts:
            if marker in content:
                raise ProtocolViolation(
                    f"clear extension marker is present before reveal in {label}"
                )


def assert_candidate_tree_has_no_extension_plaintext(
    root: Path | str, markers: Sequence[bytes]
) -> None:
    files = _read_candidate_tree(Path(root))
    _assert_markers_absent(files.items(), markers)


@dataclass(frozen=True, slots=True)
class ExtensionCommitment:
    world_id: str
    commitment: str
    ciphertext_digest: str
    ciphertext_size_bytes: int

    def __post_init__(self) -> None:
        if type(self.world_id) is not str or not self.world_id:
            raise ProtocolViolation("world_id must be non-empty")
        _require_digest(self.commitment, "commitment")
        _require_digest(self.ciphertext_digest, "ciphertext_digest")
        if (
            type(self.ciphertext_size_bytes) is not int
            or self.ciphertext_size_bytes <= 0
        ):
            raise ProtocolViolation("ciphertext_size_bytes must be positive")

    def to_wire(self) -> dict[str, Any]:
        # ``world_id`` is judge-only too: candidate projections may not reveal
        # benchmark/world/test identity.  The commitment remains bound to it.
        return {
            "protocol": COMMIT_PROTOCOL,
            "commitment": self.commitment,
            "ciphertext_digest": self.ciphertext_digest,
            "ciphertext_size_bytes": self.ciphertext_size_bytes,
        }


@dataclass(frozen=True, slots=True)
class RevealedExtensionPack:
    world_id: str
    commitment: str
    pack_bytes: bytes
    pack: dict[str, Any]
    hiding_nonce_hex: str
    encryption_key_hex: str
    encryption_nonce_hex: str

    def __post_init__(self) -> None:
        _require_digest(self.commitment, "commitment")
        if type(self.pack_bytes) is not bytes:
            raise ProtocolViolation("pack_bytes must be exact bytes")
        if type(self.pack) is not dict:
            raise ProtocolViolation("pack must be an exact dict")
        if canonical_json_bytes(self.pack) != self.pack_bytes:
            raise ProtocolViolation("revealed pack bytes are not canonical")
        for value, label in (
            (self.hiding_nonce_hex, "hiding_nonce_hex"),
            (self.encryption_key_hex, "encryption_key_hex"),
            (self.encryption_nonce_hex, "encryption_nonce_hex"),
        ):
            if type(value) is not str:
                raise ProtocolViolation(f"{label} must be a hex string")
            try:
                raw = bytes.fromhex(value)
            except ValueError as exc:
                raise ProtocolViolation(f"{label} is not hexadecimal") from exc
            if len(raw) != 32:
                raise ProtocolViolation(f"{label} must encode 32 bytes")
        expected = domain_digest(
            _COMMIT_DOMAIN,
            [self.world_id.encode("utf-8"), bytes.fromhex(self.hiding_nonce_hex), self.pack_bytes],
        )
        if not hmac.compare_digest(expected, self.commitment):
            raise ProtocolViolation("revealed pack does not open the commitment")

    @property
    def pack_digest(self) -> str:
        return digest_bytes(self.pack_bytes)

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": REVEAL_PROTOCOL,
            "world_id": self.world_id,
            "commitment": self.commitment,
            "pack": self.pack,
            "pack_digest": self.pack_digest,
            "hiding_nonce_hex": self.hiding_nonce_hex,
            "encryption_key_hex": self.encryption_key_hex,
            "encryption_nonce_hex": self.encryption_nonce_hex,
        }


@dataclass(frozen=True, slots=True)
class OpaqueExtensionCustody:
    """Judge-only encrypted pack.  Never serialize this into a candidate view."""

    public: ExtensionCommitment
    ciphertext: bytes
    authentication_tag: bytes
    encryption_nonce: bytes
    encryption_key: bytes
    hiding_nonce: bytes
    hiding_markers: tuple[bytes, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.ciphertext, "ciphertext"),
            (self.authentication_tag, "authentication_tag"),
            (self.encryption_nonce, "encryption_nonce"),
            (self.encryption_key, "encryption_key"),
            (self.hiding_nonce, "hiding_nonce"),
        ):
            if type(value) is not bytes:
                raise ProtocolViolation(f"{label} must be exact bytes")
        if len(self.authentication_tag) != 32:
            raise ProtocolViolation("authentication tag must be 32 bytes")
        if len(self.encryption_nonce) != 32 or len(self.encryption_key) != 32:
            raise ProtocolViolation("opaque encryption key/nonce must be 32 bytes")
        if len(self.hiding_nonce) != 32:
            raise ProtocolViolation("commitment hiding nonce must be 32 bytes")
        if digest_bytes(self.ciphertext) != self.public.ciphertext_digest:
            raise ProtocolViolation("ciphertext digest mismatch")


def make_opaque_extension_pack(
    world_id: str,
    pack: dict[str, Any],
    *,
    hiding_markers: Sequence[bytes],
) -> OpaqueExtensionCustody:
    """Create a fresh computationally hiding commitment and opaque fixture."""

    if type(world_id) is not str or not world_id:
        raise ProtocolViolation("world_id must be non-empty")
    if type(pack) is not dict:
        raise ProtocolViolation("extension pack must be an exact dict")
    validate_json_like(pack, path="$.extension_pack")
    pack_bytes = canonical_json_bytes(pack)
    markers = tuple(hiding_markers)
    if not markers:
        raise ProtocolViolation("at least one extension-specific hiding marker is required")
    for marker in markers:
        if marker not in pack_bytes:
            raise ProtocolViolation("every hiding marker must occur in the clear pack")

    key = secrets.token_bytes(32)
    encryption_nonce = secrets.token_bytes(32)
    hiding_nonce = secrets.token_bytes(32)
    ciphertext = _xor(pack_bytes, _stream(key, encryption_nonce, len(pack_bytes)))
    tag = _opaque_tag(key, encryption_nonce, ciphertext)
    commitment = domain_digest(
        _COMMIT_DOMAIN,
        [world_id.encode("utf-8"), hiding_nonce, pack_bytes],
    )
    public = ExtensionCommitment(
        world_id=world_id,
        commitment=commitment,
        ciphertext_digest=digest_bytes(ciphertext),
        ciphertext_size_bytes=len(ciphertext),
    )
    # A probabilistic ciphertext could contain a marker by chance.  Regenerate
    # instead of giving the pre-seal artifact a literal extension token.
    if any(marker in ciphertext or marker in tag for marker in markers):
        return make_opaque_extension_pack(
            world_id, pack, hiding_markers=hiding_markers
        )
    return OpaqueExtensionCustody(
        public=public,
        ciphertext=ciphertext,
        authentication_tag=tag,
        encryption_nonce=encryption_nonce,
        encryption_key=key,
        hiding_nonce=hiding_nonce,
        hiding_markers=markers,
    )


def _open_custody(custody: OpaqueExtensionCustody) -> RevealedExtensionPack:
    expected_tag = _opaque_tag(
        custody.encryption_key, custody.encryption_nonce, custody.ciphertext
    )
    if not hmac.compare_digest(expected_tag, custody.authentication_tag):
        raise ProtocolViolation("opaque extension authentication failed")
    pack_bytes = _xor(
        custody.ciphertext,
        _stream(
            custody.encryption_key,
            custody.encryption_nonce,
            len(custody.ciphertext),
        ),
    )
    try:
        decoded = json.loads(pack_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("revealed extension pack is invalid JSON") from exc
    if type(decoded) is not dict or canonical_json_bytes(decoded) != pack_bytes:
        raise ProtocolViolation("revealed extension pack is not canonical")
    return RevealedExtensionPack(
        world_id=custody.public.world_id,
        commitment=custody.public.commitment,
        pack_bytes=pack_bytes,
        pack=decoded,
        hiding_nonce_hex=custody.hiding_nonce.hex(),
        encryption_key_hex=custody.encryption_key.hex(),
        encryption_nonce_hex=custody.encryption_nonce.hex(),
    )


@dataclass(frozen=True, slots=True)
class PrimarySeal:
    candidate_bundle_digest: str
    model_digest: str
    primary_catalog_digest: str
    state_hashes: tuple[str, ...]
    state_snapshot_digest: str
    seal_digest: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.candidate_bundle_digest, "candidate_bundle_digest"),
            (self.model_digest, "model_digest"),
            (self.primary_catalog_digest, "primary_catalog_digest"),
            (self.state_snapshot_digest, "state_snapshot_digest"),
            (self.seal_digest, "seal_digest"),
        ):
            _require_digest(value, label)
        if not self.state_hashes:
            raise ProtocolViolation("primary seal requires at least one state")
        for value in self.state_hashes:
            _require_digest(value, "state_hash")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": PRIMARY_SEAL_PROTOCOL,
            "candidate_bundle_digest": self.candidate_bundle_digest,
            "model_digest": self.model_digest,
            "primary_catalog_digest": self.primary_catalog_digest,
            "state_hashes": list(self.state_hashes),
            "state_snapshot_digest": self.state_snapshot_digest,
            "seal_digest": self.seal_digest,
        }


@dataclass(frozen=True, slots=True)
class ExtensionFirstQueryRequest:
    state: CandidateStateInput
    state_hash: str
    extension_pack_digest: str
    extension_pack: dict[str, Any]
    query: dict[str, Any]

    def __post_init__(self) -> None:
        if type(self.state) is not CandidateStateInput:
            raise ProtocolViolation("first query requires CandidateStateInput")
        _require_digest(self.state_hash, "state_hash")
        _require_digest(self.extension_pack_digest, "extension_pack_digest")
        if type(self.extension_pack) is not dict:
            raise ProtocolViolation("revealed extension pack must be an exact dict")
        validate_json_like(self.extension_pack, path="$.revealed_extension_pack")
        if digest_json(self.extension_pack) != self.extension_pack_digest:
            raise ProtocolViolation("revealed extension pack digest mismatch")
        if type(self.query) is not dict:
            raise ProtocolViolation("extension query must be an exact dict")
        validate_json_like(self.query, path="$.extension_query")
        forbidden = {
            "history",
            "public_history",
            "events",
            "raw_history",
            "trainer_targets",
            "oracle",
            "hidden_state",
            "generator_seed",
        }
        normalized = canonical_json_bytes(self.query).lower()
        if any(key.encode("ascii") in normalized for key in forbidden):
            raise ProtocolViolation("first extension query contains forbidden history/truth")

    def to_wire(self) -> dict[str, Any]:
        payload = self.state.payload
        return {
            "protocol": FIRST_QUERY_PROTOCOL,
            "state": {
                "payload_hex": payload.payload.hex(),
                "codec": payload.codec,
                "schema_version": payload.schema_version,
                "state_class": payload.state_class.value,
            },
            "state_hash": self.state_hash,
            "extension_pack_digest": self.extension_pack_digest,
            "extension_pack": self.extension_pack,
            "query": self.query,
        }


@dataclass(frozen=True, slots=True)
class ExtensionFirstQueryResult:
    status: ResultStatus
    prediction: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not ResultStatus:
            raise ProtocolViolation("extension result status must use ResultStatus")
        if self.status is ResultStatus.OK:
            if type(self.prediction) is not dict or not self.prediction:
                raise ProtocolViolation("ok extension result requires a prediction")
            validate_json_like(self.prediction, path="$.extension_prediction")
        elif self.prediction is not None:
            raise ProtocolViolation("non-ok extension result cannot claim a prediction")


class ExtensionVerdict(str, Enum):
    PASS = "PASS"
    HONEST_LIMIT = "HONEST_LIMIT"
    HARD_FAILURE = "HARD_FAILURE"
    UNSCORED_OK = "UNSCORED_OK"


@dataclass(frozen=True, slots=True)
class FirstQueryTranscript:
    request_digest: str
    primary_state_hash: str
    state_snapshot_before: str
    state_snapshot_after: str
    status: ResultStatus
    verdict: ExtensionVerdict
    max_numeric_error: float | None


def _max_numeric_error(actual: Any, expected: Any, path: str = "$") -> float:
    if type(actual) is not type(expected):
        raise ProtocolViolation(f"{path}: prediction shape/type mismatch")
    if type(expected) in {int, float}:
        return abs(float(actual) - float(expected))
    if type(expected) is dict:
        if set(actual) != set(expected):
            raise ProtocolViolation(f"{path}: prediction keys mismatch")
        return max(
            (_max_numeric_error(actual[k], expected[k], f"{path}.{k}") for k in expected),
            default=0.0,
        )
    if type(expected) is list:
        if len(actual) != len(expected):
            raise ProtocolViolation(f"{path}: prediction list length mismatch")
        return max(
            (_max_numeric_error(a, e, f"{path}[{i}]") for i, (a, e) in enumerate(zip(actual, expected, strict=True))),
            default=0.0,
        )
    return 0.0 if actual == expected else float("inf")


@dataclass(frozen=True, slots=True)
class ExtensionUpdateRequest:
    state: CandidateStateInput
    state_hash: str
    delta: VisibleDelta
    seed: int
    extension_pack_digest: str
    extension_pack: dict[str, Any]

    def __post_init__(self) -> None:
        if type(self.state) is not CandidateStateInput:
            raise ProtocolViolation("extension update requires CandidateStateInput")
        _require_digest(self.state_hash, "state_hash")
        if type(self.delta) is not VisibleDelta:
            raise ProtocolViolation("extension update requires VisibleDelta")
        if type(self.seed) is not int or self.seed < 0 or self.seed >= 2**64:
            raise ProtocolViolation("extension update seed must be uint64")
        _require_digest(self.extension_pack_digest, "extension_pack_digest")
        if type(self.extension_pack) is not dict:
            raise ProtocolViolation("extension update pack must be an exact dict")
        if digest_json(self.extension_pack) != self.extension_pack_digest:
            raise ProtocolViolation("extension update pack digest mismatch")


@dataclass(frozen=True, slots=True)
class MigrationCostEvidence:
    replay_history_bytes: int
    old_state_bytes: int
    new_state_bytes: int
    state_growth_bytes: int
    candidate_changed_bytes: int
    candidate_core_diff_loc: int
    model_artifact_bytes: int
    model_changed_bytes: int
    training_examples: int
    training_bytes: int


@dataclass(frozen=True, slots=True)
class MigrationOutcome:
    protocol: str
    authorization_digest: str
    primary_state_hash: str
    migrated_state: SealedState
    cost: MigrationCostEvidence
    s0_snapshot_before: str
    s0_snapshot_after: str


def _tree_change_cost(old: Mapping[str, bytes], new: Mapping[str, bytes]) -> tuple[int, int]:
    changed_bytes = 0
    diff_loc = 0
    for path in sorted(set(old) | set(new)):
        left = old.get(path, b"")
        right = new.get(path, b"")
        if left == right:
            continue
        changed_bytes += len(right)
        left_lines = left.decode("utf-8", errors="replace").splitlines()
        right_lines = right.decode("utf-8", errors="replace").splitlines()
        for line in difflib.ndiff(left_lines, right_lines):
            if line.startswith(("+ ", "- ")):
                diff_loc += 1
    return changed_bytes, diff_loc


class ExtensionRunner:
    """Fail-closed state machine enforcing the W16/W17 two-stage boundary."""

    def __init__(
        self,
        custody: OpaqueExtensionCustody,
        *,
        primary_catalog_digest: str,
    ) -> None:
        if type(custody) is not OpaqueExtensionCustody:
            raise ProtocolViolation("runner requires OpaqueExtensionCustody")
        self._custody = custody
        self._primary_catalog_digest = _require_digest(
            primary_catalog_digest, "primary_catalog_digest"
        )
        self._primary_seal: PrimarySeal | None = None
        self._reveal: RevealedExtensionPack | None = None
        self._states: dict[str, SealedState] = {}
        self._histories: dict[str, VisibleHistory] = {}
        self._snapshots: dict[str, str] = {}
        self._first_queries: dict[str, FirstQueryTranscript] = {}
        self._candidate_tree: dict[str, bytes] = {}
        self._candidate_root: Path | None = None
        self._model_bytes = b""
        self._history_digests: dict[str, str] = {}

    @property
    def public_commitment(self) -> ExtensionCommitment:
        return self._custody.public

    @property
    def primary_seal(self) -> PrimarySeal | None:
        return self._primary_seal

    def seal_primary(
        self,
        *,
        candidate_root: Path | str,
        model_artifact: bytes,
        states: Sequence[SealedState],
        histories: Mapping[str, VisibleHistory],
    ) -> PrimarySeal:
        if self._primary_seal is not None:
            raise ProtocolViolation("primary extension seal is append-only")
        if type(model_artifact) is not bytes:
            raise ProtocolViolation("model_artifact must be exact bytes")
        if not states:
            raise ProtocolViolation("at least one primary state must be sealed")
        root = Path(candidate_root)
        tree = _read_candidate_tree(root)
        bundle_digest = candidate_tree_digest(root)
        model_digest = digest_bytes(model_artifact)

        artifacts: list[tuple[str, bytes]] = list(tree.items())
        artifacts.append(("model_artifact", model_artifact))
        for state in states:
            artifacts.append(
                (
                    f"state:{state.record.state_hash}",
                    state.candidate_input.payload.payload,
                )
            )
        _assert_markers_absent(artifacts, self._custody.hiding_markers)

        state_map: dict[str, SealedState] = {}
        snapshots: dict[str, str] = {}
        history_map: dict[str, VisibleHistory] = {}
        for state in states:
            record = state.record
            if record.candidate_bundle_digest != bundle_digest:
                raise ProtocolViolation("primary state candidate bundle seal mismatch")
            if record.model_digest != model_digest:
                raise ProtocolViolation("primary state model seal mismatch")
            if record.catalog_digest != self._primary_catalog_digest:
                raise ProtocolViolation("primary state catalog seal mismatch")
            if record.state_hash in state_map:
                raise ProtocolViolation("duplicate primary state hash")
            history = histories.get(record.state_hash)
            if type(history) is not VisibleHistory:
                raise ProtocolViolation("every primary state requires judge-custodied history")
            if history.catalog_digest != self._primary_catalog_digest:
                raise ProtocolViolation("primary history catalog mismatch")
            if history.as_of_available_at != record.as_of_available_at:
                raise ProtocolViolation("primary history/state cut mismatch")
            state_map[record.state_hash] = state
            history_map[record.state_hash] = history
            snapshots[record.state_hash] = _state_snapshot(state)

        state_hashes = tuple(sorted(state_map))
        snapshot_digest = digest_json(
            [{"state_hash": value, "snapshot": snapshots[value]} for value in state_hashes]
        )
        unsigned = {
            "protocol": PRIMARY_SEAL_PROTOCOL,
            "candidate_bundle_digest": bundle_digest,
            "model_digest": model_digest,
            "primary_catalog_digest": self._primary_catalog_digest,
            "state_hashes": list(state_hashes),
            "state_snapshot_digest": snapshot_digest,
            "extension_commitment": self.public_commitment.commitment,
        }
        primary = PrimarySeal(
            candidate_bundle_digest=bundle_digest,
            model_digest=model_digest,
            primary_catalog_digest=self._primary_catalog_digest,
            state_hashes=state_hashes,
            state_snapshot_digest=snapshot_digest,
            seal_digest=digest_json(unsigned),
        )
        self._candidate_tree = tree
        self._candidate_root = root.resolve(strict=True)
        self._model_bytes = model_artifact
        self._states = state_map
        self._histories = history_map
        self._history_digests = {
            key: value.digest for key, value in history_map.items()
        }
        self._snapshots = snapshots
        self._primary_seal = primary
        return primary

    def reveal(self) -> RevealedExtensionPack:
        if self._primary_seal is None:
            raise ProtocolViolation(
                "extension reveal requires candidate, model, and primary state seals"
            )
        self._assert_primary_immutable()
        if self._reveal is None:
            self._reveal = _open_custody(self._custody)
        return self._reveal

    def _assert_primary_immutable(self) -> None:
        if self._primary_seal is None or self._candidate_root is None:
            raise ProtocolViolation("primary artifacts are not sealed")
        if _read_candidate_tree(self._candidate_root) != self._candidate_tree:
            raise ProtocolViolation("sealed primary candidate bundle changed")
        if candidate_tree_digest(self._candidate_root) != self._primary_seal.candidate_bundle_digest:
            raise ProtocolViolation("sealed primary candidate digest changed")
        if digest_bytes(self._model_bytes) != self._primary_seal.model_digest:
            raise ProtocolViolation("sealed primary model digest changed")
        for state_hash in self._primary_seal.state_hashes:
            self._assert_s0_immutable(state_hash)
            if self._histories[state_hash].digest != self._history_digests[state_hash]:
                raise ProtocolViolation("judge-custodied primary history changed")

    def _assert_s0_immutable(self, state_hash: str) -> None:
        state = self._states[state_hash]
        if _state_snapshot(state) != self._snapshots[state_hash]:
            raise ProtocolViolation("sealed S0 state was mutated")

    def first_state_only_query(
        self,
        *,
        state_hash: str,
        query: dict[str, Any],
        invoke: Callable[[ExtensionFirstQueryRequest], ExtensionFirstQueryResult],
        expected_prediction: dict[str, Any] | None = None,
        tolerance: float = 1e-9,
    ) -> FirstQueryTranscript:
        if self._reveal is None:
            raise ProtocolViolation("extension must be revealed before first query")
        if state_hash not in self._states:
            raise ProtocolViolation("unknown primary state hash")
        if state_hash in self._first_queries:
            raise ProtocolViolation("the sealed-state first query is single-use")
        if type(tolerance) not in {int, float} or tolerance < 0:
            raise ProtocolViolation("prediction tolerance must be non-negative")

        self._assert_primary_immutable()
        state = self._states[state_hash]
        before = _state_snapshot(state)
        request = ExtensionFirstQueryRequest(
            state=state.candidate_input,
            state_hash=state_hash,
            extension_pack_digest=self._reveal.pack_digest,
            extension_pack=self._reveal.pack,
            query=query,
        )
        # This wire object is the complete candidate request.  Its construction
        # makes accidental history injection testable rather than conventional.
        request_wire = request.to_wire()
        request_digest = digest_json(request_wire)
        result = invoke(request)
        if type(result) is not ExtensionFirstQueryResult:
            raise ProtocolViolation("extension callback returned the wrong envelope")
        after = _state_snapshot(state)
        if digest_json(request.to_wire()) != request_digest:
            raise ProtocolViolation("candidate mutated the first-query request")
        self._assert_primary_immutable()
        if before != after:
            raise ProtocolViolation("first query mutated the sealed primary state")

        error: float | None = None
        if result.status is ResultStatus.SCOPE_INSUFFICIENT:
            verdict = ExtensionVerdict.HONEST_LIMIT
        elif result.status is ResultStatus.OK:
            if expected_prediction is None:
                verdict = ExtensionVerdict.UNSCORED_OK
            else:
                try:
                    error = _max_numeric_error(result.prediction, expected_prediction)
                except ProtocolViolation:
                    error = float("inf")
                verdict = (
                    ExtensionVerdict.PASS
                    if error <= float(tolerance)
                    else ExtensionVerdict.HARD_FAILURE
                )
        else:
            verdict = ExtensionVerdict.HARD_FAILURE
        transcript = FirstQueryTranscript(
            request_digest=request_digest,
            primary_state_hash=state_hash,
            state_snapshot_before=before,
            state_snapshot_after=after,
            status=result.status,
            verdict=verdict,
            max_numeric_error=error,
        )
        self._first_queries[state_hash] = transcript
        return transcript

    def update_from_sealed_state(
        self,
        *,
        state_hash: str,
        delta: VisibleDelta,
        seed: int,
        invoke: Callable[[ExtensionUpdateRequest], StatePayload],
        extension_catalog_digest: str,
    ) -> SealedState:
        """Apply a newly available event without replaying the old history."""

        if self._reveal is None:
            raise ProtocolViolation("extension must be revealed before update")
        if state_hash not in self._states:
            raise ProtocolViolation("unknown primary state hash")
        _require_digest(extension_catalog_digest, "extension_catalog_digest")
        self._assert_primary_immutable()
        old = self._states[state_hash]
        request = ExtensionUpdateRequest(
            old.candidate_input,
            state_hash,
            delta,
            seed,
            self._reveal.pack_digest,
            self._reveal.pack,
        )
        delta_digest = digest_json(delta.to_wire())
        payload = invoke(request)
        if type(payload) is not StatePayload:
            raise ProtocolViolation("extension update must return StatePayload")
        new_scope = digest_json(
            {
                "protocol": "ucm-extension-scope/1",
                "primary_scope_digest": old.record.scope_digest,
                "extension_pack_digest": self._reveal.pack_digest,
            }
        )
        updated = seal_state(
            payload,
            candidate_bundle_digest=old.record.candidate_bundle_digest,
            model_digest=old.record.model_digest,
            scope_digest=new_scope,
            catalog_digest=extension_catalog_digest,
            as_of_available_at=delta.advance_to,
            operation="update",
            parent_state_hash=old.record.state_hash,
            delta_digest=delta_digest,
        )
        if digest_json(delta.to_wire()) != delta_digest:
            raise ProtocolViolation("candidate mutated the extension delta")
        self._assert_primary_immutable()
        return updated

    def authorize_migration(
        self,
        *,
        state_hash: str,
        migrate: Callable[[VisibleHistory, RevealedExtensionPack], StatePayload],
        extension_catalog_digest: str,
        migrated_candidate_root: Path | str | None = None,
        migrated_model_artifact: bytes | None = None,
        training_examples: Sequence[bytes] = (),
    ) -> MigrationOutcome:
        """Explicitly replay history only after an honest first-query limit."""

        if self._reveal is None or self._primary_seal is None:
            raise ProtocolViolation("migration requires a revealed extension")
        transcript = self._first_queries.get(state_hash)
        if transcript is None or transcript.status is not ResultStatus.SCOPE_INSUFFICIENT:
            raise ProtocolViolation(
                "history migration is authorized only after scope_insufficient"
            )
        _require_digest(extension_catalog_digest, "extension_catalog_digest")
        if any(type(row) is not bytes for row in training_examples):
            raise ProtocolViolation("training examples must be exact bytes")
        self._assert_primary_immutable()
        old = self._states[state_hash]
        before = _state_snapshot(old)
        history = self._histories[state_hash]
        payload = migrate(history, self._reveal)
        if type(payload) is not StatePayload:
            raise ProtocolViolation("migration must return StatePayload")

        new_tree = (
            self._candidate_tree
            if migrated_candidate_root is None
            else _read_candidate_tree(Path(migrated_candidate_root))
        )
        new_bundle_digest = (
            old.record.candidate_bundle_digest
            if migrated_candidate_root is None
            else candidate_tree_digest(Path(migrated_candidate_root))
        )
        new_model = (
            self._model_bytes
            if migrated_model_artifact is None
            else migrated_model_artifact
        )
        if type(new_model) is not bytes:
            raise ProtocolViolation("migrated model artifact must be exact bytes")
        new_model_digest = digest_bytes(new_model)
        new_scope = digest_json(
            {
                "protocol": "ucm-extension-scope/1",
                "primary_scope_digest": old.record.scope_digest,
                "extension_pack_digest": self._reveal.pack_digest,
                "migration": True,
            }
        )
        authorization_digest = digest_json(
            {
                "protocol": MIGRATION_PROTOCOL,
                "primary_seal_digest": self._primary_seal.seal_digest,
                "primary_state_hash": state_hash,
                "history_digest": history.digest,
                "extension_pack_digest": self._reveal.pack_digest,
                "new_candidate_bundle_digest": new_bundle_digest,
                "new_model_digest": new_model_digest,
            }
        )
        migrated = seal_state(
            payload,
            candidate_bundle_digest=new_bundle_digest,
            model_digest=new_model_digest,
            scope_digest=new_scope,
            catalog_digest=extension_catalog_digest,
            as_of_available_at=history.as_of_available_at,
            operation="replay",
            parent_state_hash=old.record.state_hash,
            delta_digest=history.digest,
        )
        changed_bytes, changed_loc = _tree_change_cost(self._candidate_tree, new_tree)
        cost = MigrationCostEvidence(
            replay_history_bytes=len(canonical_json_bytes(history.to_wire())),
            old_state_bytes=len(old.candidate_input.payload.payload),
            new_state_bytes=len(payload.payload),
            state_growth_bytes=len(payload.payload)
            - len(old.candidate_input.payload.payload),
            candidate_changed_bytes=changed_bytes,
            candidate_core_diff_loc=changed_loc,
            model_artifact_bytes=len(new_model),
            model_changed_bytes=(
                0 if new_model == self._model_bytes else len(new_model)
            ),
            training_examples=len(training_examples),
            training_bytes=sum(map(len, training_examples)),
        )
        self._assert_primary_immutable()
        after = _state_snapshot(old)
        if before != after:
            raise ProtocolViolation("migration rewrote the sealed S0 state")
        return MigrationOutcome(
            protocol=MIGRATION_PROTOCOL,
            authorization_digest=authorization_digest,
            primary_state_hash=state_hash,
            migrated_state=migrated,
            cost=cost,
            s0_snapshot_before=before,
            s0_snapshot_after=after,
        )


__all__ = [
    "COMMIT_PROTOCOL",
    "ExtensionCommitment",
    "ExtensionFirstQueryRequest",
    "ExtensionFirstQueryResult",
    "ExtensionRunner",
    "ExtensionUpdateRequest",
    "ExtensionVerdict",
    "FirstQueryTranscript",
    "MigrationCostEvidence",
    "MigrationOutcome",
    "OpaqueExtensionCustody",
    "PrimarySeal",
    "RevealedExtensionPack",
    "assert_candidate_tree_has_no_extension_plaintext",
    "candidate_tree_digest",
    "make_opaque_extension_pack",
]
