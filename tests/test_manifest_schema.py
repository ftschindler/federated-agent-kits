"""The published schema, against the parser it describes.

The schema is not used at runtime: `manifest.py` reads a manifest and its
refusals name a line and a fix, which is better than anything a validator says.
What the schema is for is an editor and a pre-commit hook, and the risk that
comes with a second description of one format is that the two stop agreeing
without anybody noticing. So the corpus below is run through both, and a shape
one accepts and the other refuses fails here.

**Three things the schema cannot see, by construction.** Whether a name is
subscribed to twice, whether a pin resolves, and whether a destination is one
the harness actually offers are all facts about something other than this file.
They are the parser's or a command's, and they are absent from the corpus rather
than forgotten.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator
from ruamel.yaml import YAML

from federated_agent_kits import editing
from federated_agent_kits import schema as published
from federated_agent_kits.manifest import SUPPORTED_VERSION, ManifestError, Scope, parse

pytestmark = pytest.mark.unit

SCHEMA_PATH = Path(__file__).resolve().parent.parent / published.SCHEMA_FILE

#: Every shape `akit help manifest` documents, each of which both readers take.
ACCEPTED: dict[str, str] = {
    "nothing but the version": "version: 1\n",
    "both block styles, a wildcard and a pin": """version: 1

skills:
  owner/repo#9f2c1ab: [writing, caveman]   # frozen: v2
  acme/kits#4d7e08b: ["*"]                 # frozen: main

rules:
- owner/repo#1c04f7e: prose-style
- acme/kits#4d7e08b: security-review

agents:
  acme/kits#4d7e08b: [reviewer]
""",
    "one kit written as a bare string": "version: 1\nskills:\n  owner/repo: writing\n",
    "a kit installed under another name": """version: 1
skills:
  acme/kits#4d7e08b:
  - name: kb
    as: upstream-kb
""",
    "a kit renamed without a list around it": """version: 1
skills:
  acme/kits#4d7e08b:
    name: kb
    as: upstream-kb
""",
    "a harness list, bare and with a destination": """version: 1
harnesses: [detected, copilot-ci, {cursor-cloud: {rules: project}}]
rules:
- owner/repo#1c04f7e: prose-style
""",
    "a path source, which has no pin": "version: 1\nskills:\n  ./kits: writing\n",
    "an empty block, which a withdrawal can leave behind for a moment": "version: 1\nskills: {}\nrules: []\n",
}

#: Every refusal in `manifest.py` that is a fact about this file alone. Each of
#: these is rejected by the parser and by the schema, and the test says so of
#: both rather than trusting that one implies the other.
REFUSED: dict[str, str] = {
    "an empty file": "",
    "a document that is a list": "- version: 1\n",
    "no version": "skills:\n  owner/repo: writing\n",
    "a version this build does not read": "version: 2\n",
    "a key a manifest does not have": "version: 1\nharness: [detected]\n",
    "rules written as a mapping, which has no order": "version: 1\nrules:\n  owner/repo: prose-style\n",
    "skills written as a list": "version: 1\nskills:\n- owner/repo: writing\n",
    "a subscription that is a number": "version: 1\nskills:\n  owner/repo: 3\n",
    "a kit that is a number": "version: 1\nskills:\n  owner/repo: [3]\n",
    "a kit mapping with no name": "version: 1\nskills:\n  owner/repo:\n  - as: upstream-kb\n",
    "a kit mapping carrying a key it has no use for": """version: 1
skills:
  owner/repo:
  - name: kb
    pin: 9f2c1ab
""",
    "a harness list that is not a list": "version: 1\nharnesses: detected\n",
    "one entry naming two harnesses": "version: 1\nharnesses:\n- {copilot-ci: {rules: instructions}, opencode: {rules: agents}}\n",
    "a harness entry that is not a mapping of kinds": "version: 1\nharnesses:\n- {copilot-ci: instructions}\n",
    "a harness naming something that is not a kind": "version: 1\nharnesses:\n- {copilot-ci: {prompts: instructions}}\n",
    "a destination that is not a name": "version: 1\nharnesses:\n- {copilot-ci: {rules: [instructions]}}\n",
}


@pytest.fixture(scope="module")
def validator() -> Validator:
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(document)


def loaded(text: str) -> object:
    """The manifest as plain data, which is what a validator is handed."""
    return YAML(typ="safe").load(text)


def parses(text: str) -> bool:
    try:
        parse(text, scope=Scope.PROJECT)
    except ManifestError:
        return False
    return True


@pytest.mark.parametrize("text", ACCEPTED.values(), ids=list(ACCEPTED))
def test_both_readers_take_every_documented_shape(text: str, validator: Validator) -> None:
    assert parses(text), "the parser refuses a shape the manifest help documents"
    assert validator.is_valid(loaded(text)), "the schema refuses a shape the parser takes"


@pytest.mark.parametrize("text", REFUSED.values(), ids=list(REFUSED))
def test_both_readers_refuse_the_same_malformed_files(text: str, validator: Validator) -> None:
    assert not parses(text), "the parser takes a file this test expects it to refuse"
    assert not validator.is_valid(loaded(text)), "the schema takes a file the parser refuses"


def test_the_schema_pins_the_version_this_build_reads() -> None:
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert document["properties"]["version"]["const"] == SUPPORTED_VERSION


def test_the_published_url_names_the_file_that_is_in_this_repository() -> None:
    assert SCHEMA_PATH.is_file()
    assert published.url().endswith(f"/{published.SCHEMA_FILE}")


def test_a_release_publishes_its_schema_at_its_own_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(published, "version", lambda: "1.2.3")
    assert published.url() == f"{published.REPOSITORY}/v1.2.3/{published.SCHEMA_FILE}"


def test_a_source_tree_that_was_never_released_points_at_the_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(published, "version", lambda: published.UNRELEASED)
    assert published.url() == f"{published.REPOSITORY}/main/{published.SCHEMA_FILE}"


def test_a_manifest_akit_creates_carries_the_line_an_editor_reads(validator: Validator) -> None:
    """The header is a comment, so the file it heads is still the schema's business."""
    text = editing.empty()
    assert text.startswith(published.DIRECTIVE)
    assert parses(text)
    assert validator.is_valid(loaded(text))
