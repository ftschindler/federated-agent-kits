#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Check .mailmap for missing entries, duplicate emails, and unsorted lines.

Roughly based on:
https://github.com/pymor/pymor/blob/0dfec244b20186b938b34e678d8c06ddcab79588/.ci/gitlab/check_mailmap.py
"""

import sys
from collections import defaultdict
from pathlib import Path
from subprocess import check_output

namesep = "??"
fmtsep = "||"
cmd = ["git", "log", f"--format=%an{namesep}%ae{fmtsep}%aN{namesep}%aE"]
seen_set = set()
seen = defaultdict(list)
for user in (f.split(fmtsep) for f in set(check_output(cmd, text=True).strip().split("\n"))):
    if user[0] != user[1]:
        # has a mailmap entry
        continue
    name, email = user[0].split(namesep)
    seen_set.add((name, email))
    seen[name].append(email)

mailmap_location = ".mailmap"
mailmap = Path(mailmap_location).resolve()
if not mailmap.exists():
    print(
        f"No mailmap found at {mailmap_location}, "
        "please add one (see https://git-scm.com/docs/gitmailmap) in a separate commit.\n"
        "First time contributors: please ensure at least a single line of the form\n"
        "    Proper Name <github_or_other_representative_email>"
    )
    sys.exit(1)

contents = mailmap.read_text(encoding="utf-8")
assert len(contents) > 0

# completely missing from mailmap
missing_complete_entry = [(u, e) for u, e in seen_set if u not in contents or e not in contents]
# name is in mailmap, but email is new
missing_email = [(u, e) for u, e in seen_set if u in contents and e not in contents]
# name occurs with multiple emails, but no mailmap entry
duplicates = [(u, mails) for u, mails in seen.items() if len(mails) > 1]

lines = [line for line in contents.splitlines() if not line.startswith("#")]
sorted_lines = sorted(lines, key=lambda line: line.lower())
unsorted = [u for u, t in zip(lines, sorted_lines, strict=True) if t != u]

for user, email in set(missing_email + missing_complete_entry):
    print(f"missing mailmap entry for {user} <{email}>")
for user, emails in duplicates:
    print(f"multiple emails for {user}: {emails}")
for line in unsorted:
    print(f"line not sorted properly: {line}")

num_failures = len(missing_complete_entry) + len(missing_email) + len(duplicates) + len(unsorted)
if num_failures > 0:
    sys.exit(1)
