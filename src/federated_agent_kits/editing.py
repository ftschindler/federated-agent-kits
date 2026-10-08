"""Writing a manifest: which file gets edited, and the edits themselves.

Reading a manifest uses both scopes, always. Writing picks one and gets asked,
which is the asymmetry DESIGN.md section 6 spends a paragraph on, so choosing
the file is a step with its own refusals rather than a flag somewhere in
`add`.

**Every edit here goes through the document, never through the text.** The
dataclasses a command reasons about are derived; the `CommentedMap` the manifest
was parsed into is what gets written back, so a pin moving cannot reflow the
thirty lines around it. That is also why each function hands back a freshly
parsed `Manifest` rather than a patched one: the file on disk and the
subscriptions in memory then cannot disagree, and an edit that produced
something unreadable is found here instead of on the next command.

**A kind block's shape is not a choice.** Skills and agents are mappings and
rules are a list, because only rules have an order (DESIGN.md section 6), and a
block created here is created in the shape its kind demands.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from federated_agent_kits import manifest as manifests
from federated_agent_kits.exits import UsageError
from federated_agent_kits.manifest import Kind, Manifest, Scope, Subscription

EMPTY = f"version: {manifests.SUPPORTED_VERSION}\n"


@dataclass(frozen=True)
class Chosen:
    """The one manifest a writing command was pointed at."""

    path: Path
    scope: Scope
    manifest: Manifest
    existed: bool
    """Whether the file was there, so the command can say it created one."""


def blank(scope: Scope, path: Path) -> Manifest:
    """A manifest with nothing in it but the version, for a file that is not there yet."""
    return manifests.parse(EMPTY, scope=scope, path=path)


def _read_or_blank(path: Path, scope: Scope) -> Chosen:
    existed = path.is_file()
    found = manifests.read(path, scope=scope) if existed else blank(scope, path)
    return Chosen(path=path, scope=scope, manifest=found, existed=existed)


def choose(
    start: Path,
    *,
    only_global: bool = False,
    only_project: bool = False,
    named: Path | None = None,
    user_path: Path | None = None,
) -> Chosen:
    """Which manifest this command writes to, with the refusals DESIGN.md section 6 asks for.

    The repository's is the default, and a repository without one is an error
    naming the other two ways in rather than a quiet write to somebody's
    personal file: a subscription that lands in the repository by accident shows
    up in `git status` within seconds, and one that lands in your own file shows
    up when a colleague clones and does not get it.
    """
    if only_global and only_project:
        raise UsageError(
            "--global and --project ask for two different files.\n"
            "  Name one. Without either, this writes the repository's manifest."
        )
    if named is not None:
        scope = Scope.USER if named == (user_path or manifests.user_manifest_path()) else Scope.PROJECT
        return _read_or_blank(named, scope)
    if only_global:
        return _read_or_blank(user_path or manifests.user_manifest_path(), Scope.USER)
    root = manifests.worktree_root(start)
    if root is None:
        raise UsageError(
            f"{start} is not inside a git repository, so there is no repository manifest to write.\n"
            "  Run this with --global to write your own, or --manifest <path> to name a file."
        )
    found = root / manifests.PROJECT_MANIFEST
    if not found.is_file() and not only_project:
        raise UsageError(
            f"{root} has no {manifests.PROJECT_MANIFEST}, and writing one is not the default.\n"
            "  Run this with --project to create it, or --global to subscribe on this machine only."
        )
    return _read_or_blank(found, Scope.PROJECT)


def _reparsed(found: Manifest) -> Manifest:
    """The document back through the parser, so an edit cannot leave an unreadable file."""
    return manifests.parse(manifests.dump(found), scope=found.scope, path=found.path)


def _block(document: CommentedMap, kind: Kind) -> CommentedMap | CommentedSeq:
    """The kind's block, created in the shape that kind demands if it is not there.

    Placed before `harnesses:` when there is one, because the harness list reads
    as the file's footer and a block appended after it looks like an afterthought
    in a file somebody edits by hand.
    """
    found = document.get(kind.value)
    if isinstance(found, CommentedMap | CommentedSeq):
        return found
    fresh: CommentedMap | CommentedSeq = CommentedSeq() if kind in manifests.ORDERED else CommentedMap()
    keys = [str(key) for key in document]
    position = keys.index("harnesses") if "harnesses" in keys else len(keys)
    document.insert(position, kind.value, fresh)
    return fresh


def _entry_for(block: CommentedMap | CommentedSeq, key: str) -> tuple[CommentedMap, str] | None:
    """The mapping a key's kits live in, and the key, wherever the block's shape put it."""
    if isinstance(block, CommentedSeq):
        for item in block:
            if isinstance(item, CommentedMap) and key in item:
                return item, key
        return None
    return (block, key) if key in block else None


def _kit(name: str, rename: str | None) -> str | CommentedMap:
    """One kit as it is written: its name, or the mapping a kit that needs more becomes."""
    if rename is None:
        return name
    written = CommentedMap()
    written["name"] = name
    written["as"] = rename
    return written


def _appended(value: object, kit: str | CommentedMap) -> CommentedSeq:
    """An entry's value with one more kit in it, whatever shape it was written in."""
    listed = CommentedSeq()
    if isinstance(value, CommentedSeq):
        listed.extend(value)
        listed.ca.items.update(value.ca.items)
    else:
        listed.append(value)
    listed.append(kit)
    return listed


def _comment(node: CommentedMap, key: str, text: str | None) -> None:
    """Write or replace the comment beside a key, where and how the old one sat.

    Two things ruamel keeps inside the comment token rather than beside it: the
    column it starts at, which is the alignment somebody chose, and the newlines
    after it, the second of which is the blank line between two blocks. A
    replacement that rebuilt the token from the text alone would close that gap
    up and shift the comment left, in a file nobody asked us to reformat.
    """
    if text is None:
        return
    existing = node.ca.items.get(key)
    trailing = "\n"
    column = None
    if existing is not None and existing[2] is not None:
        token = existing[2]
        trailing = token.value[len(token.value.rstrip("\n")) :]
        column = token.start_mark.column
        del node.ca.items[key]
    node.yaml_add_eol_comment(f"# {text}{trailing}", key, column=column)


@dataclass(frozen=True)
class Entry:
    """One subscription as it is about to be written: where it goes and what it says."""

    kind: Kind
    key: str
    """The source with its pin already on it, which is what the manifest keys on."""

    name: str
    rename: str | None = None
    comment: str | None = None
    """What goes beside the key, saying what the pin follows. Nothing parses it."""


def subscribe(found: Manifest, entry: Entry) -> Manifest:
    """Write one subscription into a manifest, beside whatever else names that key."""
    document = found.document
    block = _block(document, entry.kind)
    kit = _kit(entry.name, entry.rename)
    key = entry.key
    found_at = _entry_for(block, key)
    if found_at is None:
        holder: CommentedMap = CommentedMap() if isinstance(block, CommentedSeq) else block
        holder[key] = kit
        if isinstance(block, CommentedSeq):
            block.append(holder)
        _comment(holder, key, entry.comment)
    else:
        node, at = found_at
        node[at] = _appended(node[at], kit)
        _comment(node, at, entry.comment)
    return _reparsed(found)


def _without(value: object, name: str, rename: str | None) -> object:
    """An entry's value with one kit taken out, or `None` when that was the last one."""

    def wanted(item: object) -> bool:
        if isinstance(item, CommentedMap):
            return str(item.get("name")) == name and (item.get("as") is None or str(item["as"]) == rename)
        return str(item) == name and rename is None

    if not isinstance(value, CommentedSeq):
        return None if wanted(value) else value
    kept = CommentedSeq(item for item in value if not wanted(item))
    if not kept:
        return None
    return kept[0] if len(kept) == 1 and not isinstance(kept[0], CommentedMap) else kept


def unsubscribe(found: Manifest, subscription: Subscription) -> Manifest:
    """Take one subscription out, and whatever became empty around it.

    A source key holding nothing goes, and so does a kind block holding no
    sources, because a manifest that accumulates empty scaffolding is a file
    somebody has to tidy by hand.
    """
    document = found.document
    kind = subscription.kind
    block = document[kind.value]
    entry = _entry_for(block, subscription.key)
    if entry is None:  # pragma: no cover - the caller found this subscription in this file
        raise UsageError(f"{found.path}: `{subscription.key}` is not in this manifest")
    node, at = entry
    remaining = _without(node[at], subscription.name, subscription.rename)
    if remaining is None:
        del node[at]
        node.ca.items.pop(at, None)
        if isinstance(block, CommentedSeq) and not node:
            block.remove(node)
    else:
        node[at] = remaining
    if not block:
        del document[kind.value]
        document.ca.items.pop(kind.value, None)
    return _reparsed(found)


def _rename_key(node: CommentedMap, old: str, new: str) -> None:
    """One key renamed where it stands, with its comment and the keys around it kept.

    ruamel has no rename, and assigning the new key would put it at the end of
    the block. The order of a manifest is the order somebody wrote it in, so the
    whole mapping is rebuilt in place and the comment index is moved with it.
    """
    if old == new:
        return
    items = list(node.items())
    comments = dict(node.ca.items)
    for key in list(node):
        del node[key]
    for key, value in items:
        node[new if key == old else key] = value
    node.ca.items.clear()
    for key, comment in comments.items():
        node.ca.items[new if key == old else key] = comment


def repin(found: Manifest, *, kind: Kind, key: str, pin: str, comment: str | None = None) -> Manifest:
    """Move one key's commit, and say in the comment what it now follows."""
    block = found.document[kind.value]
    entry = _entry_for(block, key)
    if entry is None:  # pragma: no cover - the caller read this key out of this file
        raise UsageError(f"{found.path}: `{key}` is not in this manifest")
    node, at = entry
    source, _ = manifests.split_pin(at)
    _rename_key(node, at, f"{source}{manifests.PIN}{pin}")
    _comment(node, f"{source}{manifests.PIN}{pin}", comment)
    return _reparsed(found)


def name_harness(found: Manifest, name: str) -> Manifest:
    """Add a harness to the list, writing the list out when it was only implied.

    An absent `harnesses:` means `[detected]`, so the first `harness add` has to
    write both names: dropping the implied one would turn every harness on this
    machine off as a side effect of naming one more.
    """
    document = found.document
    if "harnesses" not in document:
        listed = CommentedSeq(manifests.DEFAULT_HARNESSES)
        listed.fa.set_flow_style()
        document["harnesses"] = listed
    named = document["harnesses"]
    if name not in [str(entry) for entry in named]:
        named.append(name)
    return _reparsed(found)


def unname_harness(found: Manifest, name: str) -> Manifest:
    """Drop a harness from the list, writing the implied list out first if it was implied."""
    document = found.document
    if "harnesses" not in document:
        listed = CommentedSeq(manifests.DEFAULT_HARNESSES)
        listed.fa.set_flow_style()
        document["harnesses"] = listed
    named = document["harnesses"]
    for index, entry in enumerate(named):
        if str(entry) == name:
            del named[index]
            break
    return _reparsed(found)


__all__ = [
    "Chosen",
    "Entry",
    "blank",
    "choose",
    "name_harness",
    "repin",
    "subscribe",
    "unname_harness",
    "unsubscribe",
]
