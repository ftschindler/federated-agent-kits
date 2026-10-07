# fixture-rule

A rule the `federation` test layer reads from this repository over the network.
A rule is one markdown file whose stem is its name, so this file is the whole of
it, and what a test asserts is that the walk found it under `rules/` and called
it `fixture-rule`.
