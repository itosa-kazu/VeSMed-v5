from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compile_sanitized_role_registries as compiler


class SanitizedRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model, cls.model_sha = compiler.load_model_pack()
        cls.mapper = compiler.build_mapper_registry(cls.model, cls.model_sha)
        cls.oracle = compiler.build_oracle_registry(cls.model, cls.model_sha)

    def test_mapper_exact_top_level_contract(self) -> None:
        self.assertEqual(
            set(self.mapper),
            {"schema_version", "source_model_pack_sha256", "observations", "actions"},
        )

    def test_mapper_rows_are_minimal(self) -> None:
        for row in self.mapper["observations"]:
            self.assertEqual(set(row), {"concept_id", "value_type", "unit"})
            self.assertIn(row["value_type"], {"BOOLEAN", "NUMBER", "ORDINAL", "CATEGORICAL"})
        for row in self.mapper["actions"]:
            self.assertEqual(set(row), {"action_id", "entity_type", "unit"})
            self.assertEqual(row["entity_type"], "ACTION")
            self.assertIsNone(row["unit"])

    def test_mapper_is_complete_and_unique(self) -> None:
        expected_observations = sorted(row["concept_id"] for row in self.model["observations"])
        actual_observations = [row["concept_id"] for row in self.mapper["observations"]]
        expected_actions = sorted(row["action_id"] for row in self.model["actions"])
        actual_actions = [row["action_id"] for row in self.mapper["actions"]]
        self.assertEqual(actual_observations, expected_observations)
        self.assertEqual(actual_actions, expected_actions)
        self.assertEqual(len(actual_observations), len(set(actual_observations)))
        self.assertEqual(len(actual_actions), len(set(actual_actions)))

    def test_mapper_excludes_model_content(self) -> None:
        forbidden = {
            "process_id", "emissions", "joint_likelihoods", "reference_likelihood",
            "unknown_likelihood", "prior", "factor_id", "coordinates", "effects",
            "activation_effects", "topology", "outcomes", "causal_status",
        }
        seen_keys: set[str] = set()

        def walk(value):
            if isinstance(value, dict):
                seen_keys.update(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(self.mapper)
        self.assertFalse(forbidden & seen_keys)

    def test_oracle_exact_contract_and_minimal_rows(self) -> None:
        self.assertEqual(set(self.oracle), {"schema_version", "source_model_pack_sha256", "processes"})
        for row in self.oracle["processes"]:
            self.assertEqual(
                set(row),
                {"process_id", "name_ja", "name_en", "neutral_description", "domain"},
            )

    def test_oracle_is_complete_unique_and_parameter_free(self) -> None:
        expected = sorted(row["process_id"] for row in self.model["processes"])
        actual = [row["process_id"] for row in self.oracle["processes"]]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))
        serialized = json.dumps(self.oracle, ensure_ascii=False)
        for forbidden in (
            "activation_prior", "coordinates", "mode_guards", "modes", "edges",
            "observations", "actions", "joint_likelihoods", "runtime_output",
        ):
            self.assertNotIn(f'"{forbidden}"', serialized)

    def test_source_hash_is_exact_model_pack_hash(self) -> None:
        actual = hashlib.sha256(compiler.MODEL_PACK.read_bytes()).hexdigest()
        self.assertEqual(self.mapper["source_model_pack_sha256"], actual)
        self.assertEqual(self.oracle["source_model_pack_sha256"], actual)

    def test_compiler_is_byte_deterministic(self) -> None:
        compiler.compile_registries()
        first_mapper = compiler.MAPPER_REGISTRY.read_bytes()
        first_oracle = compiler.ORACLE_REGISTRY.read_bytes()
        compiler.compile_registries()
        self.assertEqual(first_mapper, compiler.MAPPER_REGISTRY.read_bytes())
        self.assertEqual(first_oracle, compiler.ORACLE_REGISTRY.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
